"""Regression tests for README claims that used to silently not hold.

Each test drives the real simulation (or API) end to end and checks the
behavior the README promises, not internal flags.
"""
import math
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.fleet.fleet_commander import FleetCommander
from src.fleet.fleet_manager import FleetManager, SIM_DT
from src.logging.mission_logger import MissionLogger
from src.schemas import (
    AssetCommand, AssetStatus, DomainType, FleetCommand, FormationType,
    GpsMode, MissionType, Waypoint,
)

DT = SIM_DT


def _surface_cmd(mission, wp, vessels=("alpha", "bravo", "charlie"),
                 speed=5.0, formation=FormationType.INDEPENDENT, **kw):
    return FleetCommand(
        mission_type=mission,
        formation=formation,
        assets=[AssetCommand(asset_id=v, domain=DomainType.SURFACE,
                             waypoints=[Waypoint(x=wp[0], y=wp[1])], speed=speed)
                for v in vessels],
        **kw,
    )


def _run(fm, seconds):
    for _ in range(int(seconds / DT)):
        fm.step(DT)


# ----------------------------------------------------------------------
# Comms-denied: "Each fires exactly once on comms loss — no action spam."
# ----------------------------------------------------------------------

def test_standing_orders_fire_once_when_denied_while_idle():
    fm = FleetManager()
    fm.set_comms_mode("denied")
    _run(fm, 10)
    fallbacks = fm.decision_log.get_by_type("comms_fallback")
    assert len(fallbacks) == 1
    assert len(fm.autonomous_actions) == 1


def test_standing_orders_fire_once_when_denied_mid_mission():
    fm = FleetManager()
    fm.dispatch_command(_surface_cmd(MissionType.PATROL, (1500, 1500),
                                     comms_lost_behavior="hold_position"))
    _run(fm, 5)
    fm.set_comms_mode("denied")
    _run(fm, 10)
    assert len(fm.decision_log.get_by_type("comms_fallback")) == 1


def test_hold_position_is_not_overridden_by_escort_tracking():
    fm = FleetManager()
    fm.spawn_contact("c1", 1000, 1000, 0.0, 2.0)
    fm.dispatch_command(_surface_cmd(MissionType.ESCORT, (1000, 1000),
                                     comms_lost_behavior="hold_position"))
    _run(fm, 5)
    fm.set_comms_mode("denied")
    _run(fm, 10)
    assert all(v["status"] == AssetStatus.IDLE for v in fm.vessels.values())


def test_auto_engage_reports_sim_time_and_delay_is_configurable():
    fm = FleetManager()
    fm.escalation_steps = int(20 / DT)  # 20 sim-second escalation
    fm.spawn_contact("bogey", 1000, 500, math.radians(180), 0.0)
    fm.set_comms_mode("denied")
    _run(fm, 19)
    assert not fm.decision_log.get_by_type("auto_engage")
    _run(fm, 2)
    engage = fm.decision_log.get_by_type("auto_engage")
    assert len(engage) == 1
    assert "Comms denied 20s" in engage[0].rationale
    assert fm.get_fleet_state_dict()["autonomy"]["comms_denied_duration"] == pytest.approx(21.0)


# ----------------------------------------------------------------------
# Kill chain: DETECT -> TRACK -> LOCK -> ENGAGE (-> CONVERGE), once
# ----------------------------------------------------------------------

def _intercept_run(seconds):
    fm = FleetManager()
    fm.spawn_contact("bogey", 2500, 1500, math.radians(225), 3.0)
    dispatched = False
    for _ in range(int(seconds / DT)):
        fm.step(DT)
        if fm.intercept_recommended and not dispatched:
            fm.dispatch_command(_surface_cmd(MissionType.INTERCEPT, (0, 0), speed=8.0,
                                             formation=FormationType.ECHELON))
            dispatched = True
    return fm


def test_kill_chain_completes_once_and_does_not_restart():
    fm = _intercept_run(600)
    transitions = [d.action_taken for d in fm.decision_log.get_by_type("kill_chain_transition")]
    assert transitions == [
        "Kill chain: NONE → DETECT",
        "Kill chain: DETECT → TRACK",
        "Kill chain: TRACK → LOCK",
        "Kill chain: LOCK → ENGAGE",
        "Kill chain: ENGAGE → CONVERGE",
    ]
    assert len(fm.decision_log.get_by_type("intercept_complete")) == 1
    assert fm.kill_chain_phase == "CONVERGE"
    assert fm.kill_chain_target == "bogey"


def test_kill_chain_drops_target_that_leaves_with_other_contacts_present():
    fm = FleetManager()
    fm.spawn_contact("near", 1500, 0, 0.0, 0.0)
    fm.spawn_contact("far", 6500, 0, 0.0, 0.0)
    _run(fm, 2)
    assert fm.kill_chain_target == "near"
    fm.remove_contact("near")
    _run(fm, 2)
    # Chain restarts on the remaining contact rather than sitting on a ghost
    assert fm.kill_chain_target == "far"
    assert fm.kill_chain_phase in ("DETECT", "TRACK", "LOCK")


def test_kill_chain_target_not_hijacked_by_other_detections():
    fm = FleetManager()
    fm.spawn_contact("first", 1500, 300, 0.0, 0.0)
    _run(fm, 2)
    assert fm.kill_chain_target == "first"
    # A second contact right in front of the drone must not steal the chain
    fm.spawn_contact("second", fm.drone.x + 100, fm.drone.y + 100, 0.0, 0.0)
    _run(fm, 5)
    assert fm.kill_chain_target == "first"


# ----------------------------------------------------------------------
# GPS-denied: DR with 0.5% drift, smooth 5-second restore, no snap
# ----------------------------------------------------------------------

def _alpha(fm):
    return next(a for a in fm.get_fleet_state().assets if a.asset_id == "alpha")


def test_dead_reckoning_error_is_only_the_modelled_drift():
    fm = FleetManager()
    fm.dispatch_command(_surface_cmd(MissionType.PATROL, (2000, 1500), vessels=("alpha",), speed=6))
    fm.set_gps_mode(GpsMode.DENIED)
    _run(fm, 300)
    s = fm.vessels["alpha"]["state"]
    dr = fm.dr_states["alpha"]
    true_err = math.hypot(dr.estimated_x - s[0], dr.estimated_y - s[1])
    # Error can never exceed the accumulated drift the dashboard reports
    assert true_err <= dr.drift_error + 1e-6
    # ~0.5% of ~1800m run
    assert 2.0 < dr.drift_error < 15.0


def test_gps_restore_does_not_snap_reported_position():
    fm = FleetManager()
    fm.dispatch_command(_surface_cmd(MissionType.PATROL, (2000, 1500), vessels=("alpha",), speed=6))
    fm.set_gps_mode(GpsMode.DENIED)
    _run(fm, 60)
    fm.dr_states["alpha"].estimated_x += 80.0  # known DR error
    before = _alpha(fm)
    fm.set_gps_mode(GpsMode.FULL)
    after = _alpha(fm)
    assert math.hypot(after.x - before.x, after.y - before.y) < 1e-6

    # Converges to truth over the 5-second blend, in small steps
    prev = after
    for _ in range(int(5 / DT)):
        fm.step(DT)
        cur = _alpha(fm)
        # vessel moves <= 6 m/s * 0.25 s plus 80m/20 steps of blend
        assert math.hypot(cur.x - prev.x, cur.y - prev.y) < 1.5 + 4.0 + 0.5
        prev = cur
    s = fm.vessels["alpha"]["state"]
    assert math.hypot(prev.x - s[0], prev.y - s[1]) < 1e-6


def test_reported_speed_matches_actual_motion():
    fm = FleetManager()
    fm.dispatch_command(_surface_cmd(MissionType.PATROL, (3000, 0), vessels=("alpha",), speed=6))
    _run(fm, 30)
    x0 = fm.vessels["alpha"]["state"][0]
    fm.step(DT)
    moved = math.hypot(fm.vessels["alpha"]["state"][0] - x0,
                       fm.vessels["alpha"]["state"][1])
    assert _alpha(fm).speed == pytest.approx(moved / DT, rel=0.05)

    # A stopped vessel reports zero, not a slowly decaying number
    fm.vessels["alpha"]["status"] = AssetStatus.IDLE
    fm.step(DT)
    assert _alpha(fm).speed == pytest.approx(0.0, abs=1e-9)


def test_drone_reports_fleet_gps_mode():
    fm = FleetManager()
    fm.set_gps_mode(GpsMode.DENIED)
    drone = next(a for a in fm.get_fleet_state().assets if a.asset_id == "eagle-1")
    assert drone.gps_mode == GpsMode.DENIED


# ----------------------------------------------------------------------
# Mission behaviors: escort tracks, formations hold
# ----------------------------------------------------------------------

def test_escort_keeps_station_on_moving_contact():
    fm = FleetManager()
    fm.spawn_contact("c1", 1200, 1200, math.radians(30), 2.0)
    fm.dispatch_command(_surface_cmd(MissionType.ESCORT, (1200, 1200)))
    _run(fm, 1000)
    c = fm.contacts["c1"]
    for slot, vid in enumerate(fm._escort_vessels):
        v = fm.vessels[vid]
        assert v["status"] == AssetStatus.EXECUTING
        sx, sy = fm._escort_station(c, slot, 200.0)
        assert math.hypot(v["state"][0] - sx, v["state"][1] - sy) < 30.0
        assert v["sog"] == pytest.approx(c.speed, abs=0.5)


def test_formation_tracks_with_subset_of_vessels():
    fm = FleetManager()
    fm.dispatch_command(_surface_cmd(MissionType.PATROL, (2500, 2500),
                                     vessels=("bravo", "charlie"),
                                     formation=FormationType.COLUMN))
    _run(fm, 120)
    from src.fleet.formations import apply_formation
    from src.fleet.fleet_manager import METERS_TO_NMI
    lead = fm.vessels["bravo"]["state"]
    hdg = (90 - math.degrees(lead[2])) % 360
    expected = apply_formation(lead[0], lead[1], hdg, ["bravo", "charlie"],
                               FormationType.COLUMN, 200.0)["charlie"]
    # Follower's target is continuously updated to its slot behind bravo
    wp = (fm.vessels["charlie"]["waypoints_x"][-1] / METERS_TO_NMI,
          fm.vessels["charlie"]["waypoints_y"][-1] / METERS_TO_NMI)
    assert math.hypot(wp[0] - expected.x, wp[1] - expected.y) < 30.0
    assert fm.vessels["alpha"]["status"] == AssetStatus.IDLE


# ----------------------------------------------------------------------
# API / infrastructure
# ----------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    logger = MissionLogger(db_path=str(tmp_path / "log.db"))
    app = create_app(commander=FleetCommander(logger=logger), logger=logger)
    with TestClient(app) as c:
        yield c
    logger.close()


def test_monitor_follows_reset(client):
    client.post("/api/contacts", json={"contact_id": "b1", "x": 1000, "y": 0,
                                       "heading": 0, "speed": 1})
    with patch("src.llm.ollama_client.test_connection", return_value=False):
        with client.websocket_connect("/monitor/ws") as ws:
            assert ws.receive_json()["threats"]["contact_count"] == 1
            client.post("/api/reset")
            assert ws.receive_json()["threats"]["contact_count"] == 0
            perf = ws.receive_json()["performance"]
            assert perf["ollama_loaded"] is False  # real status, not hardcoded


def test_logs_endpoint_returns_newest_events(tmp_path):
    logger = MissionLogger(db_path=str(tmp_path / "log.db"))
    from src.schemas import MissionEvent
    for i in range(10):
        logger.log_event(MissionEvent(timestamp=float(i), event_type="state", data={"i": i}))
    newest = logger.get_events(limit=3, newest=True)
    assert [e.data["i"] for e in newest] == [7, 8, 9]
    # Default stays oldest-first for replay
    assert [e.data["i"] for e in logger.get_events(limit=3)] == [0, 1, 2]
    logger.close()


def test_voice_endpoint_without_whisper_returns_clear_error(client):
    with patch("src.voice.whisper_local.mlx_whisper", None):
        r = client.post("/api/voice-command",
                        files={"audio": ("a.wav", b"RIFF0000WAVE", "audio/wav")})
    body = r.json()
    assert body["success"] is False
    assert "mlx-whisper" in body["error"]


def test_direct_commands_are_logged(client):
    cmd = _surface_cmd(MissionType.PATROL, (500, 500), vessels=("alpha",))
    client.post("/api/command-direct", json=cmd.model_dump(mode="json"))
    assert client.get("/api/logs/summary").json()["commands"] == 1
