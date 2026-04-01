"""Tests for Audit 4 — Mission Lifecycle & Target Intercept."""
import math
from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, Waypoint,
    DomainType, MissionType, FormationType, AssetStatus, DronePattern,
)


def test_spawn_and_remove_contact():
    """Spawn a contact, verify it exists, remove it."""
    fm = FleetManager()
    assert len(fm.contacts) == 0

    contact = fm.spawn_contact("bogey-1", x=2000.0, y=1000.0,
                                heading=math.pi, speed=3.0)
    assert contact.contact_id == "bogey-1"
    assert contact.x == 2000.0
    assert contact.y == 1000.0
    assert contact.speed == 3.0
    assert len(fm.contacts) == 1

    removed = fm.remove_contact("bogey-1")
    assert removed is True
    assert len(fm.contacts) == 0

    # Removing again returns False
    assert fm.remove_contact("bogey-1") is False


def test_contact_moves_in_step():
    """Contact moves in a straight line each simulation step."""
    fm = FleetManager()
    heading = 0.0  # East
    speed = 4.0
    fm.spawn_contact("target-1", x=500.0, y=500.0, heading=heading, speed=speed)

    dt = 0.25
    steps = 40  # 10 seconds
    for _ in range(steps):
        fm.step(dt)

    c = fm.contacts["target-1"]
    expected_x = 500.0 + speed * math.cos(heading) * dt * steps
    expected_y = 500.0 + speed * math.sin(heading) * dt * steps
    assert abs(c.x - expected_x) < 0.01
    assert abs(c.y - expected_y) < 0.01


def test_intercept_dispatch_sets_waypoints():
    """Dispatching an INTERCEPT command sets vessel waypoints and drone pattern."""
    fm = FleetManager()
    target_x, target_y = 1500.0, 800.0

    cmd = FleetCommand(
        mission_type=MissionType.INTERCEPT,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=target_x, y=target_y)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="bravo",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=target_x, y=target_y)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="eagle-1",
                domain=DomainType.AIR,
                waypoints=[Waypoint(x=target_x, y=target_y)],
                speed=15.0,
                altitude=100.0,
                drone_pattern=DronePattern.TRACK,
            ),
        ],
        formation=FormationType.ECHELON,
    )
    fm.dispatch_command(cmd)

    # Surface vessels should be EXECUTING with waypoints set
    assert fm.vessels["alpha"]["status"] == AssetStatus.EXECUTING
    assert fm.vessels["bravo"]["status"] == AssetStatus.EXECUTING
    assert fm.vessels["alpha"]["i_wpt"] == 1

    # Drone should be executing with TRACK pattern
    assert fm.drone.status == AssetStatus.EXECUTING

    # Mission type recorded
    assert fm.active_mission == MissionType.INTERCEPT


def test_contacts_in_fleet_state():
    """FleetState includes active contacts."""
    fm = FleetManager()

    # No contacts initially
    state = fm.get_fleet_state()
    assert state.contacts == []

    # Spawn a contact
    fm.spawn_contact("bogey-1", x=1000.0, y=500.0,
                      heading=math.pi / 2, speed=3.0)
    state = fm.get_fleet_state()
    assert len(state.contacts) == 1
    assert state.contacts[0].contact_id == "bogey-1"
    assert state.contacts[0].x == 1000.0

    # Remove and verify
    fm.remove_contact("bogey-1")
    state = fm.get_fleet_state()
    assert state.contacts == []


def test_intercept_mission_vessels_converge():
    """Integration: dispatch intercept, step 200 times, verify vessels
    moved toward target position."""
    fm = FleetManager()
    target_x, target_y = 1500.0, 0.0

    # Also spawn a contact at that position moving away slowly
    fm.spawn_contact("bogey-1", x=target_x, y=target_y,
                      heading=0.0, speed=2.0)

    cmd = FleetCommand(
        mission_type=MissionType.INTERCEPT,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=target_x, y=target_y)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="bravo",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=target_x, y=target_y)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="charlie",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=target_x, y=target_y)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="eagle-1",
                domain=DomainType.AIR,
                waypoints=[Waypoint(x=target_x, y=target_y)],
                speed=15.0,
                altitude=100.0,
                drone_pattern=DronePattern.TRACK,
            ),
        ],
        formation=FormationType.ECHELON,
    )
    fm.dispatch_command(cmd)

    # Record starting distances
    start_dists = {}
    for vid in ("alpha", "bravo", "charlie"):
        s = fm.vessels[vid]["state"]
        start_dists[vid] = math.sqrt((s[0] - target_x)**2 + (s[1] - target_y)**2)

    dt = 0.25
    for _ in range(200):
        fm.step(dt)

    # All vessels should have moved closer to the target
    for vid in ("alpha", "bravo", "charlie"):
        s = fm.vessels[vid]["state"]
        end_dist = math.sqrt((s[0] - target_x)**2 + (s[1] - target_y)**2)
        assert end_dist < start_dists[vid], (
            f"{vid} should be closer to target: started {start_dists[vid]:.0f}m, "
            f"now {end_dist:.0f}m"
        )

    # Drone should also have moved toward target
    drone_dist = math.sqrt((fm.drone.x - target_x)**2 + (fm.drone.y - target_y)**2)
    drone_start = math.sqrt((200.0 - target_x)**2 + (-100.0 - target_y)**2)
    assert drone_dist < drone_start, "Drone should be closer to target"

    # Contact should have moved (it's heading East at 2 m/s)
    c = fm.contacts["bogey-1"]
    assert c.x > target_x, "Contact should have moved east from spawn point"
