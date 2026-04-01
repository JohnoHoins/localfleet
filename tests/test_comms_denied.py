"""Tests for comms-denied autonomous behavior."""
import math
import time
from unittest.mock import patch

from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, Waypoint, MissionType,
    DomainType, AssetStatus, FormationType, GpsMode,
)


def _make_fleet_manager():
    """Create a FleetManager with default vessel layout."""
    return FleetManager()


def _make_patrol_command():
    """Create a simple patrol command for all vessels."""
    return FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=1000, y=1000)], speed=5.0),
            AssetCommand(asset_id="bravo", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=1000, y=1000)], speed=5.0),
            AssetCommand(asset_id="charlie", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=1000, y=1000)], speed=5.0),
        ],
        formation=FormationType.INDEPENDENT,
    )


def test_comms_denied_blocks_dispatch():
    fm = _make_fleet_manager()
    fm.set_comms_mode("denied")
    # Verify comms mode is set
    assert fm.comms_mode == "denied"
    assert fm.comms_denied_since is not None


def test_comms_denied_fleet_continues_mission():
    fm = _make_fleet_manager()
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)
    assert any(v["status"] == AssetStatus.EXECUTING for v in fm.vessels.values())
    fm.set_comms_mode("denied")
    for _ in range(100):
        fm.step(0.25)
    # Fleet should still be executing, not stopped
    assert any(v["status"] == AssetStatus.EXECUTING for v in fm.vessels.values())


def test_comms_denied_idle_triggers_rtb():
    fm = _make_fleet_manager()
    # Move vessels away from home so RTB has somewhere to go
    for vid, v in fm.vessels.items():
        v["state"][0] = 5000.0
        v["state"][1] = 5000.0
    # Fleet is idle
    assert not fm._has_active_mission()
    fm.set_comms_mode("denied")
    for _ in range(10):
        fm.step(0.25)
    # Should have triggered RTB
    assert any(v["status"] == AssetStatus.RETURNING for v in fm.vessels.values())


def test_comms_denied_idle_hold_position():
    fm = _make_fleet_manager()
    fm.comms_lost_behavior = "hold_position"
    fm.set_comms_mode("denied")
    for _ in range(10):
        fm.step(0.25)
    # All vessels should be idle (holding)
    assert all(v["status"] == AssetStatus.IDLE for v in fm.vessels.values())


def test_comms_denied_auto_engage_after_delay():
    fm = _make_fleet_manager()
    # Spawn contact at critical range
    fm.spawn_contact("bogey-1", 1500, 0, math.pi, 1.0)
    fm.set_comms_mode("denied")
    # Mock time to simulate delay elapsed
    original_since = fm.comms_denied_since
    fm.comms_denied_since = time.time() - 70  # 70s ago (past 60s delay)
    # Run threat check to set intercept_recommended
    fm._check_threats()
    assert fm.intercept_recommended
    # Now handle comms denied — should auto-engage
    fm._handle_comms_denied()
    assert fm.active_mission == MissionType.INTERCEPT


def test_comms_denied_no_auto_engage_before_delay():
    fm = _make_fleet_manager()
    fm.spawn_contact("bogey-1", 1500, 0, math.pi, 1.0)
    fm.set_comms_mode("denied")
    fm._check_threats()
    assert fm.intercept_recommended
    # Don't manipulate time — delay hasn't elapsed
    fm._handle_comms_denied()
    # Should NOT have auto-engaged yet
    assert fm.active_mission != MissionType.INTERCEPT


def test_comms_restored_accepts_commands():
    fm = _make_fleet_manager()
    fm.set_comms_mode("denied")
    fm.set_comms_mode("full")
    assert fm.comms_mode == "full"
    assert fm.comms_denied_since is None
    # Should be able to dispatch
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)
    assert fm.active_mission == MissionType.PATROL


def test_comms_denied_contacts_still_work():
    fm = _make_fleet_manager()
    fm.set_comms_mode("denied")
    contact = fm.spawn_contact("bogey-1", 5000, 5000, 0, 2.0)
    assert "bogey-1" in fm.contacts


def test_comms_denied_duration_tracks():
    fm = _make_fleet_manager()
    fm.comms_denied_since = time.time() - 10  # 10 seconds ago
    fm.comms_mode = "denied"
    state = fm.get_fleet_state_dict()
    duration = state.get("autonomy", {}).get("comms_denied_duration", 0)
    assert duration >= 9.0  # at least 9 seconds


def test_dual_failure_gps_and_comms():
    fm = _make_fleet_manager()
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)
    fm.set_gps_mode(GpsMode.DENIED)
    fm.set_comms_mode("denied")
    # Run simulation — should not crash
    for _ in range(100):
        fm.step(0.25)
    # Fleet should still be operating
    assert fm.comms_mode == "denied"
    assert fm.gps_mode == GpsMode.DENIED


def test_comms_denied_autonomous_actions_logged():
    fm = _make_fleet_manager()
    fm.set_comms_mode("denied")
    # Idle fleet should trigger RTB and log it
    for _ in range(10):
        fm.step(0.25)
    assert len(fm.autonomous_actions) > 0
    assert "AUTO-RTB" in fm.autonomous_actions[0]


def test_comms_denied_stores_last_command():
    fm = _make_fleet_manager()
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)
    assert fm.last_command is not None
    assert fm.last_command.mission_type == MissionType.PATROL
