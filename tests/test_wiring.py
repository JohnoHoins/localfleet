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

def test_return_to_base_all_assets():
    fm = FleetManager()
    # Dispatch a command to move assets away
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

    # Step a few times so they start moving
    for _ in range(20):
        fm.step(0.25)

    # Trigger return to base
    fm.return_to_base()

    # All vessels should be RETURNING
    for vid in ("alpha", "bravo", "charlie"):
        assert fm.vessels[vid]["status"] == AssetStatus.RETURNING

    # Drone should be RETURNING
    assert fm.drone.status == AssetStatus.RETURNING

    # Mission should be cleared
    assert fm.active_mission is None
    assert fm.formation == FormationType.INDEPENDENT


def test_return_to_base_targets_home():
    fm = FleetManager()
    fm.return_to_base()

    # Alpha's last waypoint should be its home position (0.0, 0.0) in nmi
    alpha_wp_x = fm.vessels["alpha"]["waypoints_x"][-1]
    alpha_wp_y = fm.vessels["alpha"]["waypoints_y"][-1]
    assert abs(alpha_wp_x) < 0.01
    assert abs(alpha_wp_y) < 0.01

    # Drone's waypoint should be home (200, -100)
    assert len(fm.drone.waypoints) == 1
    assert abs(fm.drone.waypoints[0].x - 200.0) < 0.01
    assert abs(fm.drone.waypoints[0].y - (-100.0)) < 0.01
