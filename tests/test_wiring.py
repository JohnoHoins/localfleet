"""Tests for demo wiring: DroneCoordinator, formations, return-to-base."""
import math
from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, Waypoint,
    DomainType, MissionType, FormationType, DronePattern, AssetStatus,
)


def _patrol_with_formation():
    return FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha", domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=1000.0, y=0.0)], speed=5.0,
            ),
            AssetCommand(
                asset_id="bravo", domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=1000.0, y=0.0)], speed=5.0,
            ),
        ],
        formation=FormationType.ECHELON,
        spacing_meters=200.0,
    )


def _orbit_command():
    return FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="eagle-1", domain=DomainType.AIR,
                waypoints=[Waypoint(x=500.0, y=300.0)],
                altitude=120.0, drone_pattern=DronePattern.ORBIT,
            ),
        ],
    )


def _sweep_command():
    return FleetCommand(
        mission_type=MissionType.SEARCH,
        assets=[
            AssetCommand(
                asset_id="eagle-1", domain=DomainType.AIR,
                waypoints=[Waypoint(x=0.0, y=0.0), Waypoint(x=400.0, y=400.0)],
                altitude=80.0, drone_pattern=DronePattern.SWEEP,
            ),
        ],
    )


def _track_command():
    return FleetCommand(
        mission_type=MissionType.ESCORT,
        assets=[
            AssetCommand(
                asset_id="eagle-1", domain=DomainType.AIR,
                waypoints=[Waypoint(x=300.0, y=200.0)],
                altitude=100.0, drone_pattern=DronePattern.TRACK,
            ),
        ],
    )


# ---- Formation wiring ----

def test_echelon_offsets_waypoints():
    fm = FleetManager()
    fm.dispatch_command(_patrol_with_formation())

    # Both should be executing
    assert fm.vessels["alpha"]["status"] == AssetStatus.EXECUTING
    assert fm.vessels["bravo"]["status"] == AssetStatus.EXECUTING

    # Bravo's final waypoint should differ from alpha's due to echelon offset
    alpha_x = fm.vessels["alpha"]["waypoints_x"][-1]
    alpha_y = fm.vessels["alpha"]["waypoints_y"][-1]
    bravo_x = fm.vessels["bravo"]["waypoints_x"][-1]
    bravo_y = fm.vessels["bravo"]["waypoints_y"][-1]
    assert (alpha_x, alpha_y) != (bravo_x, bravo_y), \
        "Echelon should offset bravo from alpha"


def test_independent_no_offset():
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha", domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=1000.0, y=0.0)], speed=5.0,
            ),
            AssetCommand(
                asset_id="bravo", domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=1000.0, y=0.0)], speed=5.0,
            ),
        ],
        formation=FormationType.INDEPENDENT,
    )
    fm = FleetManager()
    fm.dispatch_command(cmd)

    # With INDEPENDENT, both get the same target waypoint
    alpha_x = fm.vessels["alpha"]["waypoints_x"][-1]
    bravo_x = fm.vessels["bravo"]["waypoints_x"][-1]
    assert alpha_x == bravo_x


# ---- DroneCoordinator wiring ----

def test_orbit_uses_coordinator():
    fm = FleetManager()
    fm.dispatch_command(_orbit_command())

    assert fm.drone.status == AssetStatus.EXECUTING
    assert fm.drone.pattern == DronePattern.ORBIT
    assert fm.drone._orbit_center is not None
    # Coordinator should have generated orbit waypoints (center + circle points)
    assert len(fm.drone.waypoints) > 1
    assert fm.drone.target_altitude == 120.0


def test_sweep_uses_coordinator():
    fm = FleetManager()
    fm.dispatch_command(_sweep_command())

    assert fm.drone.status == AssetStatus.EXECUTING
    assert fm.drone.pattern == DronePattern.SWEEP
    # Sweep should generate raster waypoints (more than 2 input points)
    assert len(fm.drone.waypoints) > 2
    assert fm.drone.target_altitude == 80.0


def test_track_uses_coordinator():
    fm = FleetManager()
    fm.dispatch_command(_track_command())

    assert fm.drone.status == AssetStatus.EXECUTING
    assert fm.drone.pattern == DronePattern.TRACK
    assert fm.drone.target_altitude == 100.0


# ---- Return to base ----

def test_return_to_base_moved_assets():
    fm = FleetManager()
    # Dispatch a command to move ALL assets far from home
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha", domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=5000.0, y=5000.0)], speed=5.0,
            ),
            AssetCommand(
                asset_id="bravo", domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=5000.0, y=5000.0)], speed=5.0,
            ),
            AssetCommand(
                asset_id="charlie", domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=5000.0, y=5000.0)], speed=5.0,
            ),
            AssetCommand(
                asset_id="eagle-1", domain=DomainType.AIR,
                waypoints=[Waypoint(x=3000.0, y=3000.0)],
                altitude=150.0,
            ),
        ],
    )
    fm.dispatch_command(cmd)

    # Step enough so they all move away from home
    for _ in range(40):
        fm.step(0.25)

    # Trigger return to base
    fm.return_to_base()

    # All moved vessels should be RETURNING
    for vid in ("alpha", "bravo", "charlie"):
        assert fm.vessels[vid]["status"] == AssetStatus.RETURNING

    # Drone should be RETURNING
    assert fm.drone.status == AssetStatus.RETURNING

    # Mission should be cleared
    assert fm.active_mission is None
    assert fm.formation == FormationType.INDEPENDENT


def test_return_to_base_already_home_goes_idle():
    """Assets already at home should go IDLE, not stuck RETURNING."""
    fm = FleetManager()
    # Don't move anything — all at home
    fm.return_to_base()

    # Charlie starts at (400, 0) which IS its home — should be IDLE
    assert fm.vessels["charlie"]["status"] == AssetStatus.IDLE
    # Drone starts at (200, -100) which IS its home — should be IDLE
    assert fm.drone.status == AssetStatus.IDLE


def test_return_to_base_targets_home():
    """Moved assets get waypoints pointing to home."""
    fm = FleetManager()
    # Move alpha far away first
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha", domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=5000.0, y=5000.0)], speed=5.0,
            ),
            AssetCommand(
                asset_id="eagle-1", domain=DomainType.AIR,
                waypoints=[Waypoint(x=3000.0, y=3000.0)],
                altitude=150.0,
            ),
        ],
    )
    fm.dispatch_command(cmd)
    for _ in range(40):
        fm.step(0.25)

    fm.return_to_base()

    # Alpha's last waypoint should be its home position (0.0, 0.0) in nmi
    alpha_wp_x = fm.vessels["alpha"]["waypoints_x"][-1]
    alpha_wp_y = fm.vessels["alpha"]["waypoints_y"][-1]
    assert abs(alpha_wp_x) < 0.01
    assert abs(alpha_wp_y) < 0.01

    # Drone should have home waypoint (200, -100)
    assert fm.drone.status == AssetStatus.RETURNING
    assert len(fm.drone.waypoints) == 1
    assert abs(fm.drone.waypoints[0].x - 200.0) < 0.01
    assert abs(fm.drone.waypoints[0].y - (-100.0)) < 0.01
