"""Tests for DroneAgent — waypoint following, orbit, sweep, state output."""
from src.dynamics.drone_dynamics import DroneAgent
from src.schemas import Waypoint, DomainType, DronePattern, AssetStatus


def test_import():
    agent = DroneAgent("eagle-1")
    assert agent.asset_id == "eagle-1"
    print("Import OK")


def test_waypoint_following():
    agent = DroneAgent("eagle-1", x=0, y=0, altitude=100)
    agent.set_waypoints([Waypoint(x=100, y=0)])
    assert agent.status == AssetStatus.EXECUTING

    for _ in range(200):
        agent.step(0.25)

    assert abs(agent.x - 100) < 5.0
    assert agent.status == AssetStatus.IDLE
    print("Waypoint following OK")


def test_orbit_pattern():
    agent = DroneAgent("eagle-1", x=0, y=0)
    center = Waypoint(x=0, y=0)
    agent.set_waypoints([center], pattern=DronePattern.ORBIT)

    for _ in range(100):
        agent.step(0.25)

    # Should still be executing (orbit loops forever)
    assert agent.status == AssetStatus.EXECUTING
    # Should be roughly orbit_radius from center
    import math
    dist = math.sqrt(agent.x**2 + agent.y**2)
    assert abs(dist - 150) < 5.0
    print("Orbit pattern OK")


def test_sweep_loops():
    agent = DroneAgent("eagle-1", x=0, y=0)
    wps = [Waypoint(x=50, y=0), Waypoint(x=50, y=50), Waypoint(x=0, y=50)]
    agent.set_waypoints(wps, pattern=DronePattern.SWEEP)

    for _ in range(500):
        agent.step(0.25)

    # Sweep loops, so should still be executing
    assert agent.status == AssetStatus.EXECUTING
    print("Sweep loops OK")


def test_get_state():
    agent = DroneAgent("eagle-1", x=10, y=20, altitude=80)
    state = agent.get_state()
    assert state.asset_id == "eagle-1"
    assert state.domain == DomainType.AIR
    assert state.x == 10.0
    assert state.y == 20.0
    assert state.altitude == 80.0
    assert state.status == AssetStatus.IDLE
    print("get_state OK")


def test_altitude_transition():
    agent = DroneAgent("eagle-1", x=0, y=0, altitude=50)
    agent.target_altitude = 100
    agent.set_waypoints([Waypoint(x=1000, y=0)])

    for _ in range(100):
        agent.step(0.25)

    assert abs(agent.altitude - 100) < 2.0
    print("Altitude transition OK")


if __name__ == "__main__":
    test_import()
    test_waypoint_following()
    test_orbit_pattern()
    test_sweep_loops()
    test_get_state()
    test_altitude_transition()
    print("\nAll drone tests passed!")
