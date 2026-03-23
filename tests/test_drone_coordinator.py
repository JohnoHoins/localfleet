"""Tests for DroneCoordinator — pattern generation on top of DroneAgent."""
import math
import pytest
from src.schemas import Waypoint, DronePattern, AssetStatus
from src.dynamics.drone_dynamics import DroneAgent
from src.fleet.drone_coordinator import DroneCoordinator


@pytest.fixture
def coordinator():
    drone = DroneAgent("eagle-1", x=0.0, y=0.0, altitude=100.0)
    return DroneCoordinator(drone)


class TestGenerateOrbitWaypoints:
    def test_correct_count(self, coordinator):
        center = Waypoint(x=500.0, y=500.0)
        wps = coordinator.generate_orbit_waypoints(center, radius=200.0)
        # 1 center + 8 perimeter points
        assert len(wps) == 9

    def test_center_is_first(self, coordinator):
        center = Waypoint(x=500.0, y=500.0)
        wps = coordinator.generate_orbit_waypoints(center)
        assert wps[0].x == center.x
        assert wps[0].y == center.y

    def test_perimeter_points_at_correct_radius(self, coordinator):
        center = Waypoint(x=100.0, y=200.0)
        radius = 200.0
        wps = coordinator.generate_orbit_waypoints(center, radius=radius)
        for wp in wps[1:]:
            dist = math.sqrt((wp.x - center.x)**2 + (wp.y - center.y)**2)
            assert abs(dist - radius) < 0.01


class TestGenerateSweepWaypoints:
    def test_zigzag_coverage(self, coordinator):
        c1 = Waypoint(x=0.0, y=0.0)
        c2 = Waypoint(x=300.0, y=400.0)
        wps = coordinator.generate_sweep_waypoints(c1, c2, spacing=100.0)
        # 4 legs (x=0,100,200,300), 2 waypoints each = 8
        assert len(wps) == 8

    def test_alternating_direction(self, coordinator):
        c1 = Waypoint(x=0.0, y=0.0)
        c2 = Waypoint(x=200.0, y=400.0)
        wps = coordinator.generate_sweep_waypoints(c1, c2, spacing=100.0)
        # First leg goes min_y -> max_y
        assert wps[0].y == 0.0
        assert wps[1].y == 400.0
        # Second leg goes max_y -> min_y
        assert wps[2].y == 400.0
        assert wps[3].y == 0.0

    def test_all_waypoints_within_bounds(self, coordinator):
        c1 = Waypoint(x=100.0, y=100.0)
        c2 = Waypoint(x=500.0, y=600.0)
        wps = coordinator.generate_sweep_waypoints(c1, c2, spacing=50.0)
        for wp in wps:
            assert 100.0 <= wp.x <= 500.0
            assert 100.0 <= wp.y <= 600.0


class TestGenerateTrackWaypoints:
    def test_returns_single_waypoint(self, coordinator):
        target = Waypoint(x=300.0, y=300.0)
        wps = coordinator.generate_track_waypoints(target, offset_distance=50.0)
        assert len(wps) == 1

    def test_offset_applied(self, coordinator):
        target = Waypoint(x=300.0, y=300.0)
        offset = 50.0
        wps = coordinator.generate_track_waypoints(target, offset_distance=offset)
        assert wps[0].x == 250.0
        assert wps[0].y == 250.0


class TestAssignPattern:
    def test_orbit_sets_drone_pattern(self, coordinator):
        center = Waypoint(x=500.0, y=500.0)
        coordinator.assign_pattern(DronePattern.ORBIT, [center],
                                   altitude=150.0, radius=200.0)
        assert coordinator.drone.pattern == DronePattern.ORBIT
        assert coordinator.drone.target_altitude == 150.0
        assert coordinator.drone._orbit_center.x == center.x

    def test_sweep_sets_drone_waypoints(self, coordinator):
        c1 = Waypoint(x=0.0, y=0.0)
        c2 = Waypoint(x=300.0, y=400.0)
        coordinator.assign_pattern(DronePattern.SWEEP, [c1, c2],
                                   altitude=80.0, spacing=100.0)
        assert coordinator.drone.pattern == DronePattern.SWEEP
        assert coordinator.drone.target_altitude == 80.0
        assert len(coordinator.drone.waypoints) == 8

    def test_track_sets_drone_waypoints(self, coordinator):
        target = Waypoint(x=200.0, y=200.0)
        coordinator.assign_pattern(DronePattern.TRACK, [target])
        assert coordinator.drone.pattern == DronePattern.TRACK
        assert len(coordinator.drone.waypoints) == 1

    def test_station_hold(self, coordinator):
        pos = Waypoint(x=100.0, y=100.0)
        coordinator.assign_pattern(DronePattern.STATION, [pos], altitude=50.0)
        assert coordinator.drone.target_altitude == 50.0
        assert coordinator.drone.waypoints[0].x == 100.0


class TestOrbitSimulation:
    def test_drone_moves_after_orbit_assignment(self, coordinator):
        center = Waypoint(x=500.0, y=500.0)
        coordinator.assign_pattern(DronePattern.ORBIT, [center], radius=150.0)
        initial_x, initial_y = coordinator.drone.x, coordinator.drone.y

        for _ in range(20):
            coordinator.drone.step(0.25)

        assert (coordinator.drone.x != initial_x or
                coordinator.drone.y != initial_y)
        assert coordinator.drone.status == AssetStatus.EXECUTING


class TestGetPatternInfo:
    def test_returns_pattern_info(self, coordinator):
        center = Waypoint(x=500.0, y=500.0)
        coordinator.assign_pattern(DronePattern.ORBIT, [center], radius=200.0)
        info = coordinator.get_pattern_info()
        assert info["pattern"] == "orbit"
        assert info["center"]["x"] == 500.0
        assert info["orbit_radius"] == 200.0

    def test_no_pattern_info(self, coordinator):
        info = coordinator.get_pattern_info()
        assert info["pattern"] is None
        assert info["center"] is None
