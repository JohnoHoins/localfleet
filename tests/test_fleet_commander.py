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


# ================================================================
# Audit 7 — Validation Tests
# ================================================================

from src.fleet.fleet_commander import validate_command


def test_waypoint_clamping():
    """Out-of-range waypoints are clamped to ±MAX_RANGE."""
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[
                    Waypoint(x=99999.0, y=-99999.0),
                    Waypoint(x=500.0, y=500.0),
                ],
                speed=5.0,
            ),
        ],
    )
    warnings = validate_command(cmd)
    wp0 = cmd.assets[0].waypoints[0]
    wp1 = cmd.assets[0].waypoints[1]

    assert wp0.x == 5000.0, f"x should be clamped to 5000, got {wp0.x}"
    assert wp0.y == -5000.0, f"y should be clamped to -5000, got {wp0.y}"
    assert wp1.x == 500.0, "In-range waypoint should be unchanged"
    assert wp1.y == 500.0, "In-range waypoint should be unchanged"
    assert any("clamped" in w for w in warnings)


def test_speed_clamping():
    """Speeds are clamped to domain-appropriate ranges."""
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=100.0, y=100.0)],
                speed=50.0,
            ),
            AssetCommand(
                asset_id="eagle-1",
                domain=DomainType.AIR,
                waypoints=[Waypoint(x=200.0, y=200.0)],
                speed=0.5,
                altitude=100.0,
                drone_pattern=DronePattern.ORBIT,
            ),
        ],
    )
    warnings = validate_command(cmd)
    assert cmd.assets[0].speed == 10.0, "Surface speed capped at 10"
    assert cmd.assets[1].speed == 5.0, "Air speed floored at 5"
    assert len([w for w in warnings if "speed" in w]) == 2


def test_invalid_asset_id_filtered():
    """Hallucinated asset IDs are removed from the command."""
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=100.0, y=100.0)],
            ),
            AssetCommand(
                asset_id="delta",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=200.0, y=200.0)],
            ),
            AssetCommand(
                asset_id="eagle-2",
                domain=DomainType.AIR,
                waypoints=[Waypoint(x=300.0, y=300.0)],
                altitude=100.0,
                drone_pattern=DronePattern.ORBIT,
            ),
        ],
    )
    warnings = validate_command(cmd)
    remaining_ids = [ac.asset_id for ac in cmd.assets]

    assert "alpha" in remaining_ids
    assert "delta" not in remaining_ids
    assert "eagle-2" not in remaining_ids
    assert len(cmd.assets) == 1
    assert any("delta" in w for w in warnings)
    assert any("eagle-2" in w for w in warnings)


def test_altitude_clamping():
    """Air asset altitude is clamped to 10-500m."""
    cmd = FleetCommand(
        mission_type=MissionType.AERIAL_RECON,
        assets=[
            AssetCommand(
                asset_id="eagle-1",
                domain=DomainType.AIR,
                waypoints=[Waypoint(x=100.0, y=100.0)],
                speed=15.0,
                altitude=9999.0,
                drone_pattern=DronePattern.ORBIT,
            ),
        ],
    )
    warnings = validate_command(cmd)
    assert cmd.assets[0].altitude == 500.0
    assert any("altitude" in w for w in warnings)


@patch("src.fleet.fleet_commander.parse_fleet_command")
def test_all_invalid_assets_returns_failure(mock_parse):
    """If all assets have hallucinated IDs, the command fails."""
    mock_parse.return_value = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="delta",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=100.0, y=100.0)],
            ),
        ],
    )
    fc = FleetCommander()
    resp = fc.handle_text("delta patrol harbor")
    assert resp.success is False
    assert "No valid assets" in resp.error


@patch("src.fleet.fleet_commander.parse_fleet_command")
def test_dispatch_summary_in_response(mock_parse):
    """Successful command with warnings includes dispatch summary."""
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=99999.0, y=100.0)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="ghost",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=200.0, y=200.0)],
            ),
        ],
    )
    mock_parse.return_value = cmd

    fc = FleetCommander()
    resp = fc.handle_text("patrol with alpha and ghost")

    assert resp.success is True
    # error field used for warnings when success=True
    assert resp.error is not None
    assert "ghost" in resp.error
    assert "clamped" in resp.error
