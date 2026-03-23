"""
Integration tests — MissionLogger wired into FleetCommander and API.
Verifies that commands, GPS changes, and log endpoints work end-to-end.
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.schemas import (
    AssetCommand, DomainType, FleetCommand, FormationType,
    GpsDeniedRequest, GpsMode, MissionType, Waypoint,
)
from src.fleet.fleet_commander import FleetCommander
from src.fleet.fleet_manager import FleetManager
from src.logging.mission_logger import MissionLogger
from src.api.server import create_app


def _fake_command():
    return FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=500, y=500)],
                speed=5.0,
            ),
        ],
        raw_text="patrol harbor",
    )


@pytest.fixture
def tmp_logger(tmp_path):
    lg = MissionLogger(db_path=str(tmp_path / "test.db"))
    yield lg
    lg.close()


# ------------------------------------------------------------------
# FleetCommander + Logger integration
# ------------------------------------------------------------------

@patch("src.fleet.fleet_commander.parse_fleet_command")
def test_commander_logs_command_on_success(mock_parse, tmp_logger):
    """Successful command dispatch logs a command event."""
    mock_parse.return_value = _fake_command()

    fc = FleetCommander(logger=tmp_logger)
    resp = fc.handle_text("patrol harbor")

    assert resp.success is True
    events = tmp_logger.get_events(event_type="command")
    assert len(events) == 1
    assert events[0].data["mission_type"] == "patrol"


@patch("src.fleet.fleet_commander.parse_fleet_command")
def test_commander_no_log_on_failure(mock_parse, tmp_logger):
    """Failed command dispatch does NOT log a command event."""
    mock_parse.side_effect = RuntimeError("LLM down")

    fc = FleetCommander(logger=tmp_logger)
    resp = fc.handle_text("bad command")

    assert resp.success is False
    events = tmp_logger.get_events(event_type="command")
    assert len(events) == 0


def test_commander_logs_gps_change(tmp_logger):
    """GPS mode change logs a gps_change event."""
    fc = FleetCommander(logger=tmp_logger)
    fc.handle_gps_mode(GpsDeniedRequest(mode=GpsMode.DEGRADED, noise_meters=40.0))

    events = tmp_logger.get_events(event_type="gps_change")
    assert len(events) == 1
    assert events[0].data["mode"] == "degraded"
    assert events[0].data["noise_meters"] == 40.0


def test_commander_works_without_logger():
    """Commander still works fine with no logger (backwards compat)."""
    fc = FleetCommander()
    assert fc.logger is None
    fc.handle_gps_mode(GpsDeniedRequest(mode=GpsMode.DEGRADED))
    assert fc.fleet_manager.gps_mode == GpsMode.DEGRADED


# ------------------------------------------------------------------
# API log endpoints
# ------------------------------------------------------------------

@pytest.fixture
def app_with_logger(tmp_path):
    logger = MissionLogger(db_path=str(tmp_path / "api_test.db"))
    commander = FleetCommander(logger=logger)
    app = create_app(commander=commander, logger=logger)
    yield TestClient(app), logger
    logger.close()


class TestLogEndpoints:
    def test_get_logs_empty(self, app_with_logger):
        client, _ = app_with_logger
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["count"] == 0

    def test_get_logs_after_command(self, app_with_logger):
        client, _ = app_with_logger
        with patch("src.fleet.fleet_commander.parse_fleet_command", return_value=_fake_command()):
            client.post("/api/command", json={"text": "patrol harbor"})

        resp = client.get("/api/logs")
        data = resp.json()
        assert data["count"] == 1
        assert data["events"][0]["event_type"] == "command"

    def test_get_logs_filter_by_type(self, app_with_logger):
        client, _ = app_with_logger
        with patch("src.fleet.fleet_commander.parse_fleet_command", return_value=_fake_command()):
            client.post("/api/command", json={"text": "patrol"})
        client.post("/api/gps-mode", json={"mode": "degraded", "noise_meters": 25.0, "update_rate_hz": 1.0})

        resp = client.get("/api/logs?event_type=gps_change")
        data = resp.json()
        assert data["count"] == 1
        assert data["events"][0]["event_type"] == "gps_change"

    def test_get_logs_summary(self, app_with_logger):
        client, _ = app_with_logger
        with patch("src.fleet.fleet_commander.parse_fleet_command", return_value=_fake_command()):
            client.post("/api/command", json={"text": "patrol"})
            client.post("/api/command", json={"text": "patrol again"})
        client.post("/api/gps-mode", json={"mode": "degraded", "noise_meters": 25.0, "update_rate_hz": 1.0})

        resp = client.get("/api/logs/summary")
        data = resp.json()
        assert data["total_events"] == 3
        assert data["commands"] == 2
        assert data["gps_changes"] == 1

    def test_get_logs_no_logger(self):
        """Endpoints return empty when no logger is set."""
        commander = FleetCommander()
        app = create_app(commander=commander, logger=None)
        # Manually remove logger from app state to simulate no-logger
        app.state.logger = None
        client = TestClient(app)

        resp = client.get("/api/logs")
        assert resp.json()["count"] == 0

        resp = client.get("/api/logs/summary")
        assert resp.json()["total_events"] == 0
