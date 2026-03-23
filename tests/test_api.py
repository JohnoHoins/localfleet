"""Tests for FastAPI backend — server, routes, WebSocket."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.schemas import (
    FleetCommand, CommandResponse, FleetState, AssetState,
    MissionType, DomainType, AssetStatus, FormationType,
    GpsMode, AssetCommand, Waypoint,
)
from src.fleet.fleet_commander import FleetCommander
from src.api.server import create_app


@pytest.fixture
def commander():
    """FleetCommander with real FleetManager but mocked LLM."""
    return FleetCommander()


@pytest.fixture
def client(commander):
    app = create_app(commander)
    return TestClient(app)


# ===== GET /api/assets =====

class TestGetAssets:
    def test_returns_fleet_state(self, client):
        resp = client.get("/api/assets")
        assert resp.status_code == 200
        data = resp.json()
        assert "assets" in data
        assert "timestamp" in data
        assert len(data["assets"]) == 4  # 3 vessels + 1 drone

    def test_contains_both_domains(self, client):
        resp = client.get("/api/assets")
        data = resp.json()
        domains = {a["domain"] for a in data["assets"]}
        assert "surface" in domains
        assert "air" in domains


# ===== POST /api/command =====

class TestPostCommand:
    def test_command_with_mocked_llm(self, client):
        """Mock the LLM to return a known FleetCommand."""
        fake_cmd = FleetCommand(
            mission_type=MissionType.PATROL,
            assets=[
                AssetCommand(
                    asset_id="alpha",
                    domain=DomainType.SURFACE,
                    waypoints=[Waypoint(x=500, y=500)],
                    speed=5.0,
                ),
            ],
        )
        with patch("src.fleet.fleet_commander.parse_fleet_command", return_value=fake_cmd):
            resp = client.post("/api/command", json={"text": "patrol harbor"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["fleet_command"]["mission_type"] == "patrol"

    def test_command_error_returns_failure(self, client):
        with patch("src.fleet.fleet_commander.parse_fleet_command",
                    side_effect=Exception("LLM timeout")):
            resp = client.post("/api/command", json={"text": "bad command"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "LLM timeout" in data["error"]


# ===== GET /api/mission =====

class TestGetMission:
    def test_no_active_mission(self, client):
        resp = client.get("/api/mission")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_mission"] is None
        assert data["last_command"] is None

    def test_after_command(self, client):
        fake_cmd = FleetCommand(
            mission_type=MissionType.SEARCH,
            assets=[
                AssetCommand(
                    asset_id="bravo",
                    domain=DomainType.SURFACE,
                    waypoints=[Waypoint(x=100, y=200)],
                ),
            ],
        )
        with patch("src.fleet.fleet_commander.parse_fleet_command", return_value=fake_cmd):
            client.post("/api/command", json={"text": "search area"})

        resp = client.get("/api/mission")
        data = resp.json()
        assert data["active_mission"] == "search"
        assert data["last_command"] is not None


# ===== POST /api/gps-mode =====

class TestGpsMode:
    def test_toggle_degraded(self, client, commander):
        resp = client.post("/api/gps-mode", json={
            "mode": "degraded",
            "noise_meters": 30.0,
            "update_rate_hz": 1.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["gps_mode"] == "degraded"
        assert commander.fleet_manager.gps_mode == GpsMode.DEGRADED

    def test_toggle_back_to_full(self, client, commander):
        client.post("/api/gps-mode", json={"mode": "degraded", "noise_meters": 25.0, "update_rate_hz": 1.0})
        client.post("/api/gps-mode", json={"mode": "full", "noise_meters": 0.0, "update_rate_hz": 4.0})
        assert commander.fleet_manager.gps_mode == GpsMode.FULL


# ===== WebSocket /ws =====

class TestWebSocket:
    def test_receives_fleet_state(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert "assets" in data
            assert "timestamp" in data
            assert len(data["assets"]) == 4
