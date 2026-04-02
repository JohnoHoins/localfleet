"""Tests for mission-specific fleet behaviors."""
import math
import numpy as np
from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, Waypoint, MissionType,
    DomainType, AssetStatus, FormationType, DronePattern,
)


def _make_fm():
    return FleetManager()


def _make_cmd(mission_type, waypoint_x=1000, waypoint_y=1000, speed=5.0):
    return FleetCommand(
        mission_type=mission_type,
        assets=[
            AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=waypoint_x, y=waypoint_y)], speed=speed),
            AssetCommand(asset_id="bravo", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=waypoint_x, y=waypoint_y)], speed=speed),
            AssetCommand(asset_id="charlie", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=waypoint_x, y=waypoint_y)], speed=speed),
            AssetCommand(asset_id="eagle-1", domain=DomainType.AIR,
                        waypoints=[Waypoint(x=waypoint_x, y=waypoint_y)],
                        speed=15.0, altitude=100.0, drone_pattern=DronePattern.ORBIT),
        ],
    )


def test_patrol_loops_back():
    fm = _make_fm()
    # Use close waypoint so vessel arrives quickly
    cmd = _make_cmd(MissionType.PATROL, waypoint_x=200, waypoint_y=0, speed=8.0)
    fm.dispatch_command(cmd)
    # Run until vessel would normally go IDLE
    for _ in range(400):
        fm.step(0.25)
    # Should still be EXECUTING (looped), not IDLE
    statuses = [v["status"] for v in fm.vessels.values()]
    assert AssetStatus.EXECUTING in statuses


def test_patrol_multiple_loops():
    fm = _make_fm()
    cmd = _make_cmd(MissionType.PATROL, waypoint_x=150, waypoint_y=0, speed=8.0)
    fm.dispatch_command(cmd)
    # Run a long time — should keep looping, never IDLE
    for _ in range(1200):
        fm.step(0.25)
    statuses = [v["status"] for v in fm.vessels.values()]
    assert AssetStatus.EXECUTING in statuses


def test_search_generates_zigzag():
    fm = _make_fm()
    cmd = _make_cmd(MissionType.SEARCH, waypoint_x=1000, waypoint_y=1000)
    fm.dispatch_command(cmd)
    # Alpha should have multiple waypoints (zigzag pattern)
    wpts = fm.vessels["alpha"]["waypoints_x"]
    assert len(wpts) > 3  # start + at least 6 zigzag points


def test_search_loops():
    fm = _make_fm()
    cmd = _make_cmd(MissionType.SEARCH, waypoint_x=200, waypoint_y=0, speed=8.0)
    fm.dispatch_command(cmd)
    for _ in range(800):
        fm.step(0.25)
    statuses = [v["status"] for v in fm.vessels.values()]
    assert AssetStatus.EXECUTING in statuses


def test_loiter_orbits():
    fm = _make_fm()
    cmd = _make_cmd(MissionType.LOITER, waypoint_x=200, waypoint_y=0, speed=8.0)
    fm.dispatch_command(cmd)
    # Run until vessel arrives and should transition to orbit
    for _ in range(600):
        fm.step(0.25)
    # Should still be EXECUTING (orbiting), not IDLE
    statuses = [v["status"] for v in fm.vessels.values()]
    assert AssetStatus.EXECUTING in statuses


def test_loiter_generated_once():
    fm = _make_fm()
    cmd = _make_cmd(MissionType.LOITER, waypoint_x=200, waypoint_y=0, speed=8.0)
    fm.dispatch_command(cmd)
    for _ in range(600):
        fm.step(0.25)
    # Check orbit flag was set
    orbit_flags = [v.get("_loiter_orbit", False) for v in fm.vessels.values()]
    assert any(orbit_flags)


def test_escort_follows():
    fm = _make_fm()
    fm.spawn_contact("tgt-1", x=500, y=0, heading=0, speed=2.0)
    cmd = _make_cmd(MissionType.ESCORT, waypoint_x=500, waypoint_y=0)
    fm.dispatch_command(cmd)
    assert fm._escort_target_id == "tgt-1"
    # Step to trigger escort update
    for _ in range(20):
        fm.step(0.25)
    # Target has moved — last waypoint should track it
    contact = fm.contacts["tgt-1"]
    from src.fleet.fleet_manager import METERS_TO_NMI
    wpts_x_last = fm.vessels["alpha"]["waypoints_x"][-1]
    assert abs(wpts_x_last - contact.x * METERS_TO_NMI) < 0.01


def test_escort_holds_on_remove():
    fm = _make_fm()
    fm.spawn_contact("tgt-1", x=500, y=0, heading=0, speed=2.0)
    cmd = _make_cmd(MissionType.ESCORT, waypoint_x=500, waypoint_y=0)
    fm.dispatch_command(cmd)
    fm.remove_contact("tgt-1")
    # Should not crash when contact removed
    for _ in range(20):
        fm.step(0.25)


def test_aerial_recon_drone_sweeps():
    fm = _make_fm()
    cmd = _make_cmd(MissionType.AERIAL_RECON, waypoint_x=1000, waypoint_y=1000)
    fm.dispatch_command(cmd)
    # Drone should be in SWEEP pattern
    assert fm.drone_coordinator._current_pattern == DronePattern.SWEEP


def test_aerial_recon_surface_loiters():
    fm = _make_fm()
    cmd = _make_cmd(MissionType.AERIAL_RECON, waypoint_x=1000, waypoint_y=1000)
    fm.dispatch_command(cmd)
    # Surface vessels should have waypoints 500m south of recon area
    from src.fleet.fleet_manager import METERS_TO_NMI
    for vid in ("alpha", "bravo", "charlie"):
        wpts_y = fm.vessels[vid]["waypoints_y"]
        # Last waypoint should be at (1000 - 500) = 500 in meters
        assert abs(wpts_y[-1] / METERS_TO_NMI - 500.0) < 1.0


def test_intercept_unchanged():
    fm = _make_fm()
    fm.spawn_contact("tgt-1", x=3000, y=0, heading=math.pi, speed=5.0)
    cmd = _make_cmd(MissionType.INTERCEPT, waypoint_x=3000, waypoint_y=0, speed=8.0)
    fm.dispatch_command(cmd)
    # Run until completion — should go IDLE (not loop)
    for _ in range(2000):
        fm.step(0.25)
    statuses = [v["status"] for v in fm.vessels.values()]
    assert AssetStatus.IDLE in statuses


def test_search_drone_gets_sweep_area():
    """SEARCH with single waypoint and drone_pattern=SWEEP should generate area."""
    fm = _make_fm()
    cmd = FleetCommand(
        mission_type=MissionType.SEARCH,
        assets=[
            AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=1000, y=1000)], speed=5.0),
            AssetCommand(asset_id="eagle-1", domain=DomainType.AIR,
                        waypoints=[Waypoint(x=1000, y=1000)],
                        speed=15.0, altitude=100.0, drone_pattern=DronePattern.SWEEP),
        ],
    )
    fm.dispatch_command(cmd)
    assert fm.drone_coordinator._current_pattern == DronePattern.SWEEP
    assert len(fm.drone.waypoints) > 2


def test_echelon_formation_spacing():
    """Echelon formation spacing should converge toward target during transit."""
    fm = _make_fm()
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=2000, y=1000)], speed=5.0),
            AssetCommand(asset_id="bravo", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=2000, y=1000)], speed=5.0),
            AssetCommand(asset_id="charlie", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=2000, y=1000)], speed=5.0),
        ],
        formation=FormationType.ECHELON,
        spacing_meters=200,
    )
    fm.dispatch_command(cmd)
    for _ in range(400):
        fm.step(0.25)
    # Compute distances
    states = {vid: v["state"] for vid, v in fm.vessels.items()}
    ab = math.sqrt((states["alpha"][0] - states["bravo"][0]) ** 2 +
                   (states["alpha"][1] - states["bravo"][1]) ** 2)
    bc = math.sqrt((states["bravo"][0] - states["charlie"][0]) ** 2 +
                   (states["bravo"][1] - states["charlie"][1]) ** 2)
    target = 200 * math.sqrt(2)  # echelon diagonal ≈ 283m
    assert ab < target * 1.5, f"AB spacing {ab:.0f}m too large"
    assert bc < target * 1.5, f"BC spacing {bc:.0f}m too large"


def test_column_formation_still_works():
    fm = _make_fm()
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=2000, y=0)], speed=5.0),
            AssetCommand(asset_id="bravo", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=2000, y=0)], speed=5.0),
            AssetCommand(asset_id="charlie", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=2000, y=0)], speed=5.0),
        ],
        formation=FormationType.COLUMN,
        spacing_meters=200,
    )
    fm.dispatch_command(cmd)
    for _ in range(400):
        fm.step(0.25)
    states = {vid: v["state"] for vid, v in fm.vessels.items()}
    ab = math.sqrt((states["alpha"][0] - states["bravo"][0]) ** 2 +
                   (states["alpha"][1] - states["bravo"][1]) ** 2)
    assert ab < 200 * 2.0, f"AB spacing {ab:.0f}m too large for column"


def test_formation_updates_continuously():
    """Bravo's last waypoint should change as alpha moves (continuous update)."""
    fm = _make_fm()
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=3000, y=0)], speed=5.0),
            AssetCommand(asset_id="bravo", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=3000, y=0)], speed=5.0),
            AssetCommand(asset_id="charlie", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=3000, y=0)], speed=5.0),
        ],
        formation=FormationType.ECHELON,
        spacing_meters=200,
    )
    fm.dispatch_command(cmd)
    bravo_wp0 = fm.vessels["bravo"]["waypoints_x"][-1]
    for _ in range(200):
        fm.step(0.25)
    bravo_wp1 = fm.vessels["bravo"]["waypoints_x"][-1]
    assert bravo_wp0 != bravo_wp1, "Bravo's last waypoint should update continuously"


def test_mission_type_in_fleet_state():
    fm = _make_fm()
    cmd = _make_cmd(MissionType.PATROL, waypoint_x=1000, waypoint_y=1000)
    fm.dispatch_command(cmd)
    state = fm.get_fleet_state()
    assert state.active_mission == MissionType.PATROL
