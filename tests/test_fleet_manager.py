"""Tests for FleetManager — multi-domain fleet coordinator."""
import math
import numpy as np
from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, Waypoint,
    DomainType, MissionType, FormationType, GpsMode, AssetStatus,
)


def _make_patrol_command():
    """Build a multi-domain patrol command."""
    return FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=1000.0, y=0.0)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="bravo",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=1000.0, y=200.0)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="eagle-1",
                domain=DomainType.AIR,
                waypoints=[Waypoint(x=500.0, y=100.0)],
                altitude=150.0,
            ),
        ],
        formation=FormationType.LINE_ABREAST,
    )


def test_fleet_manager_creates_4_assets():
    fm = FleetManager()
    state = fm.get_fleet_state()
    assert len(state.assets) == 4
    ids = {a.asset_id for a in state.assets}
    assert ids == {"alpha", "bravo", "charlie", "eagle-1"}


def test_dispatch_multi_domain_command():
    fm = FleetManager()
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)

    # Surface vessel alpha got waypoint
    v_alpha = fm.vessels["alpha"]
    assert v_alpha["i_wpt"] == 1
    assert v_alpha["desired_speed"] == 5.0
    assert v_alpha["status"] == AssetStatus.EXECUTING

    # Drone got waypoints (PATROL assigns ORBIT pattern via coordinator)
    assert fm.drone.status == AssetStatus.EXECUTING
    assert len(fm.drone.waypoints) >= 1

    # Mission tracking
    assert fm.active_mission == MissionType.PATROL
    assert fm.formation == FormationType.LINE_ABREAST


def test_step_changes_positions():
    fm = FleetManager()
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)

    state_before = fm.get_fleet_state()
    positions_before = {a.asset_id: (a.x, a.y) for a in state_before.assets}

    dt = 0.1
    for _ in range(10):
        fm.step(dt)

    state_after = fm.get_fleet_state()
    positions_after = {a.asset_id: (a.x, a.y) for a in state_after.assets}

    # alpha and bravo should have moved (they got commands)
    for aid in ("alpha", "bravo"):
        bx, by = positions_before[aid]
        ax, ay = positions_after[aid]
        assert (ax, ay) != (bx, by), f"{aid} should have moved"

    # eagle-1 should have moved
    eb = positions_before["eagle-1"]
    ea = positions_after["eagle-1"]
    assert (ea[0], ea[1]) != (eb[0], eb[1]), "eagle-1 should have moved"


def test_gps_denied_adds_noise():
    fm = FleetManager()

    # Get clean positions
    clean = fm.get_fleet_state()
    clean_pos = {a.asset_id: (a.x, a.y) for a in clean.assets}

    # Enable degraded GPS
    fm.set_gps_mode(GpsMode.DEGRADED, noise_meters=50.0)

    # Sample multiple times — at least one position should differ
    any_different = False
    for _ in range(5):
        degraded = fm.get_fleet_state()
        for a in degraded.assets:
            cx, cy = clean_pos[a.asset_id]
            # GPS noise is Gaussian so almost certainly non-zero
            if abs(a.x - cx) > 0.01 or abs(a.y - cy) > 0.01:
                any_different = True
                break
        if any_different:
            break

    assert any_different, "GPS-denied mode should add noise to positions"
    assert fm.gps_mode == GpsMode.DEGRADED


def test_get_fleet_state_domains():
    fm = FleetManager()
    state = fm.get_fleet_state()

    surface = [a for a in state.assets if a.domain == DomainType.SURFACE]
    air = [a for a in state.assets if a.domain == DomainType.AIR]

    assert len(surface) == 3
    assert len(air) == 1
    assert air[0].asset_id == "eagle-1"
    assert air[0].altitude is not None

    # FleetState metadata
    assert state.gps_mode == GpsMode.FULL
    assert state.timestamp > 0


def test_vessel_reaches_waypoint_and_goes_idle():
    """Vessel should reach a waypoint 1000m away and stop (not circle forever)."""
    fm = FleetManager()
    cmd = FleetCommand(
        mission_type=MissionType.ESCORT,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=1000.0, y=0.0)],
                speed=5.0,
            ),
        ],
    )
    fm.dispatch_command(cmd)

    dt = 0.25
    max_steps = 4000  # 1000 seconds at dt=0.25 — plenty for 1000m at 5m/s
    for step_i in range(max_steps):
        fm.step(dt)
        if fm.vessels["alpha"]["status"] == AssetStatus.IDLE:
            break

    assert fm.vessels["alpha"]["status"] == AssetStatus.IDLE, (
        f"Vessel alpha should be IDLE after reaching waypoint, "
        f"but is {fm.vessels['alpha']['status']} after {step_i+1} steps"
    )

    # Verify it's reasonably close to the target (within 300m)
    final_x = fm.vessels["alpha"]["state"][0]
    final_y = fm.vessels["alpha"]["state"][1]
    dist = math.sqrt((final_x - 1000.0)**2 + (final_y - 0.0)**2)
    assert dist < 300.0, f"Vessel should be near waypoint, but is {dist:.1f}m away"


def test_vessel_does_not_overshoot_on_uturn():
    """Vessel at heading 0° targeting waypoint at 180° should NOT travel
    more than 100m in the wrong direction before correcting course."""
    fm = FleetManager()
    # Place alpha at origin heading East (psi=0), waypoint is West (-1000, 0)
    fm.vessels["alpha"]["state"] = np.array([500.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=-500.0, y=0.0)],
                speed=5.0,
            ),
        ],
    )
    fm.dispatch_command(cmd)

    dt = 0.25
    max_east = 500.0  # starting x
    for _ in range(4000):
        fm.step(dt)
        cur_x = fm.vessels["alpha"]["state"][0]
        if cur_x > max_east:
            max_east = cur_x
        if fm.vessels["alpha"]["status"] == AssetStatus.IDLE:
            break

    overshoot = max_east - 500.0
    assert overshoot < 100.0, (
        f"Vessel overshot {overshoot:.1f}m in the wrong direction during U-turn"
    )


def test_return_to_base_no_loop():
    """Vessel 500m from home should return in under 150s without looping."""
    fm = FleetManager()
    # Place alpha 500m away from home (0,0)
    fm.vessels["alpha"]["state"] = np.array([400.0, 300.0, 0.0, 0.0, 0.0, 0.0])

    fm.return_to_base()

    dt = 0.25
    straight_line_dist = math.sqrt(400.0**2 + 300.0**2)  # 500m
    max_dist_from_home = 0.0
    steps = 0

    for steps in range(4000):  # 1000 seconds max
        fm.step(dt)
        sx = fm.vessels["alpha"]["state"][0]
        sy = fm.vessels["alpha"]["state"][1]
        d = math.sqrt(sx**2 + sy**2)
        if d > max_dist_from_home:
            max_dist_from_home = d
        if fm.vessels["alpha"]["status"] == AssetStatus.IDLE:
            break

    elapsed = (steps + 1) * dt
    assert fm.vessels["alpha"]["status"] == AssetStatus.IDLE, (
        f"Vessel should be IDLE after RTB, but is {fm.vessels['alpha']['status']}"
    )
    assert elapsed < 150.0, (
        f"RTB took {elapsed:.1f}s, expected under 150s for 500m"
    )
    assert max_dist_from_home < straight_line_dist * 1.5, (
        f"Trajectory went {max_dist_from_home:.1f}m from home, "
        f"exceeding 150% of straight-line {straight_line_dist:.1f}m"
    )


def test_vessel_straight_line_accuracy():
    """Vessel navigating 1000m in a straight line should stay within 30m
    of the ideal path (lateral deviation)."""
    fm = FleetManager()
    # Alpha starts at (0,0) heading East, waypoint at (1000, 0)
    cmd = FleetCommand(
        mission_type=MissionType.ESCORT,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=1000.0, y=0.0)],
                speed=5.0,
            ),
        ],
    )
    fm.dispatch_command(cmd)

    dt = 0.25
    max_lateral = 0.0
    for _ in range(4000):
        fm.step(dt)
        sy = fm.vessels["alpha"]["state"][1]
        if abs(sy) > max_lateral:
            max_lateral = abs(sy)
        if fm.vessels["alpha"]["status"] == AssetStatus.IDLE:
            break

    assert fm.vessels["alpha"]["status"] == AssetStatus.IDLE, (
        f"Vessel should have reached waypoint"
    )
    assert max_lateral < 30.0, (
        f"Max lateral deviation was {max_lateral:.1f}m, expected under 30m"
    )
