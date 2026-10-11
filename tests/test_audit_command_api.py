"""Regression tests for the command path, API server and mission log audit
findings: comms gating, standing-order parsing, command validation, operator
feedback, voice off the event loop, LLM timeouts, model status, decision
persistence, input validation and test isolation of the mission log."""
import io
import math
import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.fleet.decision_log import DecisionLog
from src.fleet.fleet_commander import FleetCommander, validate_command
from src.fleet.fleet_manager import FleetManager
from src.llm import ollama_client
from src.logging.mission_logger import MissionLogger
from src.logging.replay import MissionReplay
from src.navigation.land_check import is_on_land
from src.schemas import (
    AssetCommand, AssetStatus, CommandRequest, DomainType, DronePattern,
    FleetCommand, MissionType, Waypoint,
)

WAV = {"audio": ("cmd.wav", io.BytesIO(b"RIFF0000WAVE"), "audio/wav")}


def _cmd(*assets, mission=MissionType.PATROL, **kw):
    return FleetCommand(mission_type=mission, assets=list(assets), **kw)


def _surface(asset_id="alpha", wps=((800, 600),), domain=DomainType.SURFACE, speed=5.0):
    return AssetCommand(asset_id=asset_id, domain=domain, speed=speed,
                        waypoints=[Waypoint(x=x, y=y) for x, y in wps])


def _drone(asset_id="eagle-1", wps=((900, 600),), domain=DomainType.AIR):
    return AssetCommand(asset_id=asset_id, domain=domain, speed=15.0, altitude=120.0,
                        drone_pattern=DronePattern.ORBIT,
                        waypoints=[Waypoint(x=x, y=y) for x, y in wps])


@pytest.fixture
def logger(tmp_path):
    lg = MissionLogger(db_path=str(tmp_path / "log.db"))
    yield lg
    lg.close()


@pytest.fixture
def app(logger):
    return create_app(commander=FleetCommander(logger=logger), logger=logger)


@pytest.fixture
def client(app):
    return TestClient(app)


def _fm(app) -> FleetManager:
    return app.state.commander.fleet_manager


# ----------------------------------------------------------------------
# Comms denied: no operator command may reach the fleet
# ----------------------------------------------------------------------

def test_voice_command_refused_while_comms_denied(client, app):
    client.post("/api/comms-mode", json={"mode": "denied"})
    transcribe = MagicMock(return_value="all vessels patrol to 1500 800")
    with patch("src.api.routes.transcribe_audio", transcribe), \
         patch("src.fleet.fleet_commander.parse_fleet_command",
               return_value=_cmd(_surface())) as parse:
        body = client.post("/api/voice-command", files=WAV).json()
    assert body["success"] is False
    assert "COMMS DENIED" in body["error"]
    transcribe.assert_not_called()
    parse.assert_not_called()
    assert _fm(app).active_mission is None


def test_command_not_dispatched_if_comms_lost_during_parse(client, app):
    fm = _fm(app)

    def parse_while_operator_cuts_comms(text):
        fm.set_comms_mode("denied")  # RTB standing order fires mid-parse
        return _cmd(_surface("alpha"), _surface("bravo"))

    with patch("src.fleet.fleet_commander.parse_fleet_command",
               side_effect=parse_while_operator_cuts_comms):
        body = client.post("/api/command", json={"text": "patrol 800 600"}).json()
    assert body["success"] is False
    assert "COMMS DENIED" in body["error"]
    assert fm.active_mission is None
    assert all(v["status"] != AssetStatus.EXECUTING for v in fm.vessels.values())


def test_command_not_dispatched_into_a_reset_fleet(client, app):
    commander = app.state.commander

    def parse_during_reset(text):
        commander.fleet_manager = FleetManager()  # /api/reset mid-parse
        return _cmd(_surface())

    with patch("src.fleet.fleet_commander.parse_fleet_command",
               side_effect=parse_during_reset):
        body = client.post("/api/command", json={"text": "patrol"}).json()
    assert body["success"] is False
    assert "reset" in body["error"]
    assert commander.fleet_manager.active_mission is None


def test_handle_command_rechecks_comms_after_parse():
    fc = FleetCommander()

    def parse(text):
        fc.fleet_manager.set_comms_mode("denied")
        return _cmd(_surface())

    with patch("src.fleet.fleet_commander.parse_fleet_command", side_effect=parse):
        resp = fc.handle_text("alpha patrol 800 600")
    assert resp.success is False
    assert fc.fleet_manager.active_mission is None


# ----------------------------------------------------------------------
# Standing orders: free strings no longer silently do nothing
# ----------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("hold position", "hold_position"), ("HOLD_POSITION", "hold_position"),
    ("Hold-Position", "hold_position"), ("hold", "hold_position"),
    ("rtb", "return_to_base"), ("return to base", "return_to_base"),
    ("RETURN_TO_BASE", "return_to_base"), ("continue", "continue_mission"),
    ("continue mission", "continue_mission"), ("self destruct", None), (None, None),
])
def test_comms_lost_behavior_aliases(raw, expected):
    assert _cmd(_surface(), comms_lost_behavior=raw).comms_lost_behavior == expected


def test_comms_lost_behavior_defaults_to_no_change_and_schema_is_an_enum():
    assert _cmd(_surface()).comms_lost_behavior is None
    prop = FleetCommand.model_json_schema()["properties"]["comms_lost_behavior"]
    enums = [opt.get("enum") for opt in prop["anyOf"] if "enum" in opt]
    assert enums == [["return_to_base", "hold_position", "continue_mission"]]


def test_uppercase_hold_position_standing_order_actually_holds():
    fm = FleetManager()
    fm.dispatch_command(_cmd(_surface("alpha", wps=((2000, 0),)),
                             comms_lost_behavior="HOLD_POSITION"))
    assert fm.comms_lost_behavior == "hold_position"
    for _ in range(20):
        fm.step(0.25)
    fm.set_comms_mode("denied")
    for _ in range(8):
        fm.step(0.25)
    assert fm.vessels["alpha"]["desired_speed"] == 0.0


def test_system_prompt_no_longer_resets_standing_orders():
    prompt = ollama_client.SYSTEM_PROMPT
    assert 'comms_lost_behavior: "return_to_base" (the default)' not in prompt
    assert "null" in prompt


# ----------------------------------------------------------------------
# validate_command: aliases, roster domains, duplicates, land, NaN
# ----------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Alpha", "alpha"), ("alfa", "alpha"), ("BRAVO", "bravo"), ("Charlie ", "charlie"),
    ("eagle_1", "eagle-1"), ("eagle1", "eagle-1"), ("Eagle One", "eagle-1"),
    ("eagle 1", "eagle-1"), ("drone", "eagle-1"), ("Eagle", "eagle-1"),
])
def test_asset_ids_are_normalized(raw, expected):
    domain = DomainType.AIR if expected == "eagle-1" else DomainType.SURFACE
    cmd = _cmd(AssetCommand(asset_id=raw, domain=domain, waypoints=[Waypoint(x=500, y=500)]))
    warnings = validate_command(cmd)
    assert [ac.asset_id for ac in cmd.assets] == [expected]
    if raw != expected:
        assert any(raw in w for w in warnings)


def test_domain_is_forced_from_roster():
    cmd = _cmd(_drone(domain=DomainType.SURFACE), _surface("alpha", domain=DomainType.AIR))
    warnings = validate_command(cmd)
    domains = {ac.asset_id: ac.domain for ac in cmd.assets}
    assert domains == {"eagle-1": DomainType.AIR, "alpha": DomainType.SURFACE}
    assert sum("domain" in w for w in warnings) == 2
    # the drone keeps its air speed instead of being clamped as a vessel
    assert cmd.assets[0].speed == 15.0

    fm = FleetManager()
    fm.dispatch_command(cmd)
    assert fm.drone.status == AssetStatus.EXECUTING
    assert fm.vessels["alpha"]["status"] == AssetStatus.EXECUTING


def test_duplicate_entries_are_merged():
    cmd = _cmd(_surface("alpha", wps=((1000, 600),)), _surface("bravo", wps=((1000, 600),)),
               _surface("Alpha", wps=((1000, 600),)), _surface("charlie", wps=((1000, 600),)))
    warnings = validate_command(cmd)
    assert [ac.asset_id for ac in cmd.assets] == ["alpha", "bravo", "charlie"]
    assert len(cmd.assets[0].waypoints) == 1
    assert any("duplicate" in w for w in warnings)


def test_assets_without_waypoints_are_dropped_with_a_warning():
    cmd = _cmd(_surface("alpha", wps=()), _surface("bravo"))
    warnings = validate_command(cmd)
    assert [ac.asset_id for ac in cmd.assets] == ["bravo"]
    assert any("alpha" in w and "no waypoints" in w for w in warnings)

    # intercept/escort vessels get their waypoints from the contact
    cmd = _cmd(_surface("alpha", wps=()), mission=MissionType.INTERCEPT)
    validate_command(cmd)
    assert [ac.asset_id for ac in cmd.assets] == ["alpha"]


def test_land_waypoints_moved_to_water_for_vessels_only():
    cmd = _cmd(_surface("alpha", wps=((-2000, -1500), (-600, -400))),
               _drone(wps=((-2000, -1500),)))
    warnings = validate_command(cmd)
    alpha, drone = cmd.assets
    assert not any(is_on_land(wp.x, wp.y) for wp in alpha.waypoints)
    assert (alpha.waypoints[1].x, alpha.waypoints[1].y) == (-600, -400)  # water: untouched
    assert (drone.waypoints[0].x, drone.waypoints[0].y) == (-2000, -1500)  # may overfly land
    assert any("alpha" in w and "on land" in w for w in warnings)


def test_land_waypoint_with_no_water_nearby_is_removed():
    cmd = _cmd(_surface("alpha", wps=((-4000, -4000), (500, 500))))
    warnings = validate_command(cmd)
    assert [(wp.x, wp.y) for wp in cmd.assets[0].waypoints] == [(500, 500)]
    assert any("on land, removed" in w for w in warnings)


def test_non_finite_waypoints_are_removed():
    cmd = _cmd(_surface("alpha", wps=((math.nan, 100), (500, 500))))
    warnings = validate_command(cmd)
    assert [(wp.x, wp.y) for wp in cmd.assets[0].waypoints] == [(500, 500)]
    assert any("not a number" in w for w in warnings)


def test_capitalized_asset_ids_from_llm_are_dispatched():
    fc = FleetCommander()
    parsed = _cmd(_surface("Alpha"), _surface("Bravo"))
    with patch("src.fleet.fleet_commander.parse_fleet_command", return_value=parsed):
        resp = fc.handle_text("Alpha and Bravo patrol 800 600")
    assert resp.success is True
    for vid in ("alpha", "bravo"):
        assert fc.fleet_manager.vessels[vid]["status"] == AssetStatus.EXECUTING


def test_failure_names_the_rejected_assets():
    fc = FleetCommander()
    with patch("src.fleet.fleet_commander.parse_fleet_command",
               return_value=_cmd(_surface("delta"))):
        resp = fc.handle_text("delta patrol")
    assert resp.success is False
    assert "delta" in resp.error


# ----------------------------------------------------------------------
# Operator feedback: warnings, transcript, failed parses on the monitor
# ----------------------------------------------------------------------

def test_command_response_carries_warnings_not_error(client):
    parsed = _cmd(_surface("alpha", speed=50.0), _surface("ghost"))
    with patch("src.fleet.fleet_commander.parse_fleet_command", return_value=parsed):
        body = client.post("/api/command", json={"text": "patrol"}).json()
    assert body["success"] is True
    assert body["error"] is None
    assert any("ghost" in w for w in body["warnings"])
    assert any("speed clamped" in w for w in body["warnings"])


def test_voice_response_includes_transcript(client):
    with patch("src.api.routes.transcribe_audio", return_value="Alfa patrol to 800 600"), \
         patch("src.fleet.fleet_commander.parse_fleet_command",
               return_value=_cmd(_surface("alfa"))):
        body = client.post("/api/voice-command", files=WAV).json()
    assert body["success"] is True
    assert body["transcript"] == "Alfa patrol to 800 600"

    with patch("src.api.routes.transcribe_audio", return_value="delta go home"), \
         patch("src.fleet.fleet_commander.parse_fleet_command",
               return_value=_cmd(_surface("delta"))):
        body = client.post("/api/voice-command", files=WAV).json()
    assert body["success"] is False
    assert body["transcript"] == "delta go home"


def test_empty_transcript_is_not_sent_to_the_llm(client):
    with patch("src.api.routes.transcribe_audio", return_value="  "), \
         patch("src.fleet.fleet_commander.parse_fleet_command") as parse:
        body = client.post("/api/voice-command", files=WAV).json()
    assert body["success"] is False
    assert "No speech" in body["error"]
    parse.assert_not_called()


def test_failed_parse_reaches_the_monitor(client, app):
    with patch("src.fleet.fleet_commander.parse_fleet_command",
               side_effect=RuntimeError("LLM inference timed out after 60s")):
        client.post("/api/command", json={"text": "patrol"})
    info = app.state.commander.last_parse_info
    assert info["text"] == "patrol"
    assert "timed out" in info["error"]
    with patch("src.llm.ollama_client.test_connection", return_value=False):
        with client.websocket_connect("/monitor/ws") as ws:
            command = ws.receive_json()["command"]
    assert "timed out" in command["error"]


# ----------------------------------------------------------------------
# Voice transcription must not stall the 4Hz sim loop
# ----------------------------------------------------------------------

def test_voice_transcription_runs_off_the_event_loop(app):
    def slow_transcribe(path):
        time.sleep(1.5)
        return ""

    with TestClient(app) as c:
        time.sleep(0.3)
        before = app.state.tick_count
        with patch("src.api.routes.transcribe_audio", side_effect=slow_transcribe), \
             patch("src.fleet.fleet_commander.parse_fleet_command"):
            c.post("/api/voice-command", files=WAV)
        assert app.state.tick_count - before >= 3


def test_sim_loop_survives_a_failing_step(app):
    commander = app.state.commander
    real_step = commander.step
    calls = {"n": 0}

    def flaky_step(dt):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("boom")
        real_step(dt)

    commander.step = flaky_step
    with TestClient(app):
        time.sleep(1.2)
        assert app.state.tick_count >= 3
        assert calls["n"] >= 3


# ----------------------------------------------------------------------
# LLM client: real HTTP timeout, timeouts not retried, keep_alive
# ----------------------------------------------------------------------

def test_llm_client_has_an_http_timeout():
    timeout = ollama_client.chat.__self__._client.timeout
    assert timeout.read == ollama_client.LLM_TIMEOUT_SECONDS


def test_http_timeout_is_an_llm_timeout_and_not_retried():
    with patch("src.llm.ollama_client.chat",
               side_effect=httpx.ReadTimeout("timed out")) as chat:
        with pytest.raises(ollama_client.LLMTimeoutError):
            ollama_client.parse_fleet_command("alpha patrol 500 300")
    assert chat.call_count == 1


def test_chat_keeps_the_model_loaded():
    resp = MagicMock()
    resp.message.content = _cmd(_surface()).model_dump_json()
    with patch("src.llm.ollama_client.chat", return_value=resp) as chat:
        ollama_client.parse_fleet_command("alpha patrol 800 600")
    keep_alive = chat.call_args.kwargs["keep_alive"]
    assert keep_alive == ollama_client.KEEP_ALIVE
    assert keep_alive != "-1"  # Ollama rejects that string
    assert ollama_client._parse_keep_alive("-1") == -1


# ----------------------------------------------------------------------
# Monitor: Ollama model status and SIM asset counts
# ----------------------------------------------------------------------

def _fake_ollama(pulled, loaded):
    return SimpleNamespace(
        list=lambda: SimpleNamespace(models=[SimpleNamespace(model=m) for m in pulled]),
        ps=lambda: SimpleNamespace(models=[SimpleNamespace(model=m) for m in loaded]),
    )


@pytest.mark.parametrize("pulled, loaded, expected", [
    ([], [], "missing"),
    (["qwen2.5:72b"], [], "cold"),
    (["qwen2.5:72b"], ["qwen2.5:72b"], "loaded"),
])
def test_model_status(monkeypatch, pulled, loaded, expected):
    monkeypatch.setattr(ollama_client, "MODEL", "qwen2.5:72b")
    monkeypatch.setattr(ollama_client, "_status_client", _fake_ollama(pulled, loaded))
    assert ollama_client.model_status() == expected


def test_model_status_offline():
    with patch("src.llm.ollama_client.test_connection", return_value=False):
        assert ollama_client.model_status() == "offline"


def test_monitor_does_not_report_a_missing_model_as_loaded(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "_status_client", _fake_ollama([], []))
    with patch("src.llm.ollama_client.test_connection", return_value=True):
        with client.websocket_connect("/monitor/ws") as ws:
            perf = ws.receive_json()["performance"]
    assert perf["ollama_loaded"] is False
    assert perf["ollama_status"] == "missing"


def test_monitor_counts_returning_assets(client, app):
    fm = _fm(app)
    for v in fm.vessels.values():
        v["state"][0] += 1000.0
    fm.drone.x += 1000.0
    fm.return_to_base()
    with patch("src.llm.ollama_client.test_connection", return_value=False):
        with client.websocket_connect("/monitor/ws") as ws:
            sim = ws.receive_json()["sim"]
    assert sim["assets_returning"] == 4
    assert sim["assets_executing"] == 0
    assert sim["assets_idle"] == 0


# ----------------------------------------------------------------------
# Mission log: decisions, comms changes and resets are persisted
# ----------------------------------------------------------------------

def test_decisions_are_persisted_by_the_sim_loop(app, logger):
    entry = DecisionLog().log("auto_engage", "AUTO-INTERCEPT: bogey-1",
                              "Comms denied 60s. No operator.", confidence=0.7,
                              assets=["alpha", "bravo"])
    with TestClient(app):
        _fm(app).decision_log.on_log(entry)
        time.sleep(0.6)
        persisted = [e.data for e in logger.get_events(event_type="decision")]
    [data] = [d for d in persisted if d["id"] == entry.id]
    assert data["type"] == "auto_engage"
    assert data["action"] == "AUTO-INTERCEPT: bogey-1"
    assert data["confidence"] == 0.7
    assert data["assets"] == ["alpha", "bravo"]


def test_reset_keeps_persisting_decisions(client, app, logger):
    def persisted_actions():
        return [e.data["action"] for e in logger.get_events(event_type="decision")]

    old_fm = _fm(app)
    old_fm.decision_log.on_log(DecisionLog().log("comms_fallback", "AUTO-RTB", "x"))
    client.post("/api/reset")
    new_fm = _fm(app)
    assert new_fm is not old_fm
    assert new_fm.decision_log.on_log == app.state.pending_decisions.append
    assert "AUTO-RTB" in persisted_actions()  # flushed before the swap
    assert logger.count_events("reset") == 1

    new_fm.decision_log.on_log(DecisionLog().log("threat_assessment", "WARNING", "y"))
    assert client.get("/api/logs/summary").json()["decisions"] >= 2
    assert "WARNING" in persisted_actions()


def test_comms_changes_are_logged(client, logger):
    client.post("/api/comms-mode", json={"mode": "denied"})
    client.post("/api/comms-mode", json={"mode": "full"})
    events = logger.get_events(event_type="comms_change")
    assert [e.data["mode"] for e in events] == ["denied", "full"]
    assert any("AUTO-RTB" in a for a in events[0].data["autonomous_actions"])


def test_logs_filter_by_asset_and_summary_duration(client, app, logger):
    client.post("/api/command-direct", json=_cmd(_surface("alpha")).model_dump(mode="json"))
    logger.log_state(_fm(app).get_fleet_state())
    alpha = client.get("/api/logs", params={"asset_id": "alpha"}).json()
    assert {"command", "state"} <= {e["event_type"] for e in alpha["events"]}
    eagle = client.get("/api/logs", params={"asset_id": "eagle-1"}).json()
    eagle_types = {e["event_type"] for e in eagle["events"]}
    assert "state" in eagle_types and "command" not in eagle_types  # eagle-1 not commanded
    replay_types = {e.event_type for e in MissionReplay(logger.db_path).get_asset_events("alpha")}
    assert {"command", "state"} <= replay_types
    assert "duration_seconds" in client.get("/api/logs/summary").json()


def test_mission_logger_path_is_overridable(tmp_path, monkeypatch):
    path = str(tmp_path / "elsewhere.db")
    monkeypatch.setenv("LOCALFLEET_LOG_DB", path)
    lg = MissionLogger()
    assert lg.db_path == path
    lg.close()


def test_tests_never_write_the_real_mission_log():
    from src.api import server
    real_dir = os.path.abspath(os.path.join(
        os.path.dirname(server.__file__), "..", "..", "data", "logs"))
    assert not os.path.abspath(server.app.state.logger.db_path).startswith(real_dir)
    lg = MissionLogger()  # what create_app() uses by default
    assert not os.path.abspath(lg.db_path).startswith(real_dir)
    lg.close()


# ----------------------------------------------------------------------
# Input validation at the API boundary
# ----------------------------------------------------------------------

@pytest.mark.parametrize("mode, expected", [("DENIED", "denied"), (" Full ", "full")])
def test_comms_mode_is_case_insensitive(client, app, mode, expected):
    body = client.post("/api/comms-mode", json={"mode": mode}).json()
    assert body["comms_mode"] == expected == _fm(app).comms_mode


def test_unknown_comms_mode_is_rejected(client, app):
    r = client.post("/api/comms-mode", json={"mode": "off"})
    assert r.status_code == 422
    assert r.json()["success"] is False
    assert _fm(app).comms_mode == "full"


def test_non_finite_contact_is_rejected(client, app):
    r = client.post("/api/contacts", headers={"content-type": "application/json"},
                    content='{"contact_id": "nan-1", "x": NaN, "y": 1000, "heading": 0, "speed": 3}')
    assert r.status_code == 422
    assert r.json()["success"] is False
    assert "nan-1" not in _fm(app).contacts
    assert client.get("/api/contacts").status_code == 200


def test_spawn_value_error_becomes_422(client, app):
    with patch.object(FleetManager, "spawn_contact", side_effect=ValueError("bad contact")):
        r = client.post("/api/contacts", json={"contact_id": "b1", "x": 1, "y": 2, "heading": 0})
    assert r.status_code == 422
    assert r.json() == {"success": False, "error": "bad contact"}


def test_respawn_reports_replacement(client):
    contact = {"contact_id": "bogey-1", "x": 2000, "y": 1000, "heading": 3.14, "speed": 3}
    assert client.post("/api/contacts", json=contact).json()["replaced"] is False
    assert client.post("/api/contacts", json=contact).json()["replaced"] is True


def test_negative_gps_noise_is_rejected(client, app):
    r = client.post("/api/gps-mode", json={"mode": "degraded", "noise_meters": -50})
    assert r.status_code == 422
    assert _fm(app).noise_meters != -50


def test_command_direct_is_validated(client, app):
    cmd = _cmd(_surface("Alpha", wps=((800, 600),)))
    body = client.post("/api/command-direct", json=cmd.model_dump(mode="json")).json()
    assert body["success"] is True
    assert any("Alpha" in w for w in body["warnings"])
    assert _fm(app).vessels["alpha"]["status"] == AssetStatus.EXECUTING

    r = client.post("/api/command-direct", headers={"content-type": "application/json"},
                    content='{"mission_type": "patrol", "assets": [{"asset_id": "bravo", '
                            '"domain": "surface", "waypoints": [{"x": NaN, "y": 0}]}]}')
    assert r.status_code == 422
    assert r.json()["success"] is False
    assert _fm(app).vessels["bravo"]["status"] == AssetStatus.IDLE
