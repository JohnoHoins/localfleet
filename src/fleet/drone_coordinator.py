"""
DroneCoordinator — Higher-level pattern generation for DroneAgent.
Generates waypoints/parameters that feed into DroneAgent for
orbit, sweep, track, and station patterns.
"""
import math
from typing import List

from src.schemas import Waypoint, DronePattern
from src.dynamics.drone_dynamics import DroneAgent


class DroneCoordinator:
    def __init__(self, drone: DroneAgent):
        self.drone = drone
        self.orbit_radius = 150.0
        self.sweep_spacing = 100.0
        self.track_offset = 50.0
        self._current_pattern: DronePattern | None = None
        self._pattern_center: Waypoint | None = None

    def generate_orbit_waypoints(self, center: Waypoint,
                                  radius: float = 150.0) -> List[Waypoint]:
        """Generate N points around a circle. First waypoint IS the center
        (DroneAgent._step_orbit uses waypoints[0] as orbit center)."""
        self.orbit_radius = radius
        waypoints = [center]  # waypoints[0] = orbit center for DroneAgent
        n_points = 8
        for i in range(n_points):
            angle = 2 * math.pi * i / n_points
            waypoints.append(Waypoint(
                x=center.x + radius * math.cos(angle),
                y=center.y + radius * math.sin(angle),
            ))
        return waypoints

    def generate_sweep_waypoints(self, corner1: Waypoint, corner2: Waypoint,
                                  spacing: float = 100.0) -> List[Waypoint]:
        """Generate lawnmower/raster zigzag over a rectangular area."""
        self.sweep_spacing = spacing
        min_x, max_x = min(corner1.x, corner2.x), max(corner1.x, corner2.x)
        min_y, max_y = min(corner1.y, corner2.y), max(corner1.y, corner2.y)

        waypoints: List[Waypoint] = []
        x = min_x
        going_up = True
        while x <= max_x:
            if going_up:
                waypoints.append(Waypoint(x=x, y=min_y))
                waypoints.append(Waypoint(x=x, y=max_y))
            else:
                waypoints.append(Waypoint(x=x, y=max_y))
                waypoints.append(Waypoint(x=x, y=min_y))
            going_up = not going_up
            x += spacing

        return waypoints

    def generate_track_waypoints(self, target_position: Waypoint,
                                  offset_distance: float = 50.0) -> List[Waypoint]:
        """Generate a single waypoint offset behind/above the target."""
        self.track_offset = offset_distance
        return [Waypoint(
            x=target_position.x - offset_distance,
            y=target_position.y - offset_distance,
        )]

    def assign_pattern(self, pattern: DronePattern,
                       waypoints: List[Waypoint],
                       altitude: float = 100.0, **kwargs):
        """Generate pattern-specific waypoints and push them to the drone."""
        self._current_pattern = pattern
        self.drone.target_altitude = altitude

        if pattern == DronePattern.ORBIT:
            center = waypoints[0]
            radius = kwargs.get("radius", self.orbit_radius)
            orbit_wps = self.generate_orbit_waypoints(center, radius)
            self._pattern_center = center
            self.drone.set_waypoints(orbit_wps, DronePattern.ORBIT)

        elif pattern == DronePattern.SWEEP:
            corner1, corner2 = waypoints[0], waypoints[1]
            spacing = kwargs.get("spacing", self.sweep_spacing)
            sweep_wps = self.generate_sweep_waypoints(corner1, corner2, spacing)
            self._pattern_center = Waypoint(
                x=(corner1.x + corner2.x) / 2,
                y=(corner1.y + corner2.y) / 2,
            )
            self.drone.set_waypoints(sweep_wps, DronePattern.SWEEP)

        elif pattern == DronePattern.TRACK:
            target = waypoints[0]
            offset = kwargs.get("offset_distance", self.track_offset)
            track_wps = self.generate_track_waypoints(target, offset)
            self._pattern_center = target
            self.drone.set_waypoints(track_wps, DronePattern.TRACK)

        elif pattern == DronePattern.STATION:
            self._pattern_center = waypoints[0]
            self.drone.set_waypoints([waypoints[0]], None)

    def get_pattern_info(self) -> dict:
        """Return current pattern state for dashboard display."""
        return {
            "pattern": self._current_pattern.value if self._current_pattern else None,
            "center": {"x": self._pattern_center.x, "y": self._pattern_center.y}
                      if self._pattern_center else None,
            "altitude": self.drone.target_altitude,
            "orbit_radius": self.orbit_radius,
            "sweep_spacing": self.sweep_spacing,
            "track_offset": self.track_offset,
        }
