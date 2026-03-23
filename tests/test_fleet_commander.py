"""Tests for FleetCommander — NL → FleetManager bridge."""
import pytest
from unittest.mock import patch

from src.fleet.fleet_commander import FleetCommander
from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, CommandRequest, CommandResponse,
    GpsDeniedRequest, GpsMode, DomainType, MissionType, FormationType,
    Waypoint, DronePattern, AssetStatus,
)


def _fake_command():
    """A canned FleetCommand for mocked tests."""
    return FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=800.0, y=100.0)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="eagle-1",
                domain=DomainType.AIR,
                waypoints=[Waypoint(x=500.0, y=300.0)],
                speed=15.0,
                altitude=120.0,
                drone_pattern=DronePattern.SWEEP,
            ),
        ],
        formation=FormationType.ECHELON,
        raw_text="patrol harbor with alpha, eagle sweep",
    )


@patch("src.fleet.fleet_commander.parse_fleet_command")
def test_handle_command_success(mock_parse):
    mock_parse.return_value = _fake_command()

    fc = FleetCommander()
    resp = fc.handle_command(CommandRequest(text="patrol harbor with alpha"))

    assert resp.success is True
    assert resp.fleet_command is not None
    assert resp.fleet_command.mission_type == MissionType.PATROL
    assert resp.llm_response_time_ms >= 0
    assert fc.last_command is not None
    mock_parse.assert_called_once_with("patrol harbor with alpha")


@patch("src.fleet.fleet_commander.parse_fleet_command")
def test_handle_command_dispatches_to_fleet(mock_parse):
    mock_parse.return_value = _fake_command()

    fm = FleetManager()
    fc = FleetCommander(fleet_manager=fm)
    fc.handle_command(CommandRequest(text="go"))

    # alpha should have received waypoints
    assert fm.vessels["alpha"]["status"] == AssetStatus.EXECUTING
    assert fm.vessels["alpha"]["desired_speed"] == 5.0

    # drone should have received waypoints
    assert fm.drone.status == AssetStatus.EXECUTING
    assert fm.drone.target_altitude == 120.0


@patch("src.fleet.fleet_commander.parse_fleet_command")
def test_handle_command_error(mock_parse):
    mock_parse.side_effect = RuntimeError("Ollama not running")

    fc = FleetCommander()
    resp = fc.handle_text("patrol harbor")

    assert resp.success is False
    assert "Ollama not running" in resp.error
    assert fc.last_command is None


@patch("src.fleet.fleet_commander.parse_fleet_command")
def test_step_advances_simulation(mock_parse):
    mock_parse.return_value = _fake_command()

    fc = FleetCommander()
    fc.handle_text("go")

    state_before = fc.get_state()
    pos_before = {a.asset_id: (a.x, a.y) for a in state_before.assets}

    for _ in range(10):
        fc.step(dt=0.1)

    state_after = fc.get_state()
    pos_after = {a.asset_id: (a.x, a.y) for a in state_after.assets}

    # alpha and eagle-1 should have moved
    assert pos_after["alpha"] != pos_before["alpha"]
    assert pos_after["eagle-1"] != pos_before["eagle-1"]


def test_handle_gps_mode():
    fc = FleetCommander()
    fc.handle_gps_mode(GpsDeniedRequest(mode=GpsMode.DEGRADED, noise_meters=50.0))

    assert fc.fleet_manager.gps_mode == GpsMode.DEGRADED
    assert fc.fleet_manager.noise_meters == 50.0

    state = fc.get_state()
    assert state.gps_mode == GpsMode.DEGRADED


@patch("src.fleet.fleet_commander.parse_fleet_command")
def test_handle_text_convenience(mock_parse):
    mock_parse.return_value = _fake_command()

    fc = FleetCommander()
    resp = fc.handle_text("patrol harbor")

    assert resp.success is True
    mock_parse.assert_called_once_with("patrol harbor")
