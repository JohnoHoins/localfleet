"""
DroneAgent — Simple 2D+altitude waypoint follower.
NOT real flight dynamics. Just smooth movement on the map.
"""
import math
from typing import List, Optional
from src.schemas import (
    Waypoint, AssetState, DomainType, DronePattern,
    AssetStatus, MissionType, GpsMode,
)


class DroneAgent:
    def __init__(self, asset_id: str, x: float = 0.0, y: float = 0.0,
                 altitude: float = 100.0):
        self.asset_id = asset_id
        self.x = x
        self.y = y
        self.altitude = altitude
        self.target_altitude = altitude
        self.heading = 0.0          # degrees, 0 = North
        self.speed = 15.0           # m/s
        self.status = AssetStatus.IDLE
        self.mission_type: Optional[MissionType] = None
        self.waypoints: List[Waypoint] = []
        self.current_wp_index = 0
        self.pattern: Optional[DronePattern] = None
        self._orbit_angle = 0.0     # radians, for orbit pattern
        self._orbit_center: Optional[Waypoint] = None
        self._orbit_radius = 150.0  # meters

    def set_waypoints(self, waypoints: List[Waypoint],
                      pattern: Optional[DronePattern] = None):
        self.waypoints = list(waypoints)
        self.current_wp_index = 0
        self.pattern = pattern
        self.status = AssetStatus.EXECUTING if waypoints else AssetStatus.IDLE
        if pattern == DronePattern.ORBIT and waypoints:
            self._orbit_center = waypoints[0]
            self._orbit_angle = 0.0

    def step(self, dt: float):
        if self.status != AssetStatus.EXECUTING or not self.waypoints:
            return

        # Smooth altitude transition
        alt_diff = self.target_altitude - self.altitude
        if abs(alt_diff) > 0.5:
            self.altitude += math.copysign(min(5.0 * dt, abs(alt_diff)), alt_diff)

        if self.pattern == DronePattern.ORBIT and self._orbit_center:
            self._step_orbit(dt)
        else:
            self._step_waypoint(dt)

    def _step_waypoint(self, dt: float):
        wp = self.waypoints[self.current_wp_index]
        dx, dy = wp.x - self.x, wp.y - self.y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < 2.0:  # within threshold
            self.current_wp_index += 1
            if self.current_wp_index >= len(self.waypoints):
                if self.pattern == DronePattern.SWEEP:
                    self.current_wp_index = 0  # loop sweep
                else:
                    self.status = AssetStatus.IDLE
            return

        self.heading = math.degrees(math.atan2(dx, dy)) % 360
        move = min(self.speed * dt, dist)
        self.x += move * math.sin(math.radians(self.heading))
        self.y += move * math.cos(math.radians(self.heading))

    def _step_orbit(self, dt: float):
        c = self._orbit_center
        angular_speed = self.speed / self._orbit_radius
        self._orbit_angle += angular_speed * dt
        self.x = c.x + self._orbit_radius * math.cos(self._orbit_angle)
        self.y = c.y + self._orbit_radius * math.sin(self._orbit_angle)
        self.heading = (math.degrees(self._orbit_angle) + 90) % 360

    def get_state(self) -> AssetState:
        return AssetState(
            asset_id=self.asset_id,
            domain=DomainType.AIR,
            x=self.x, y=self.y,
            heading=self.heading,
            speed=self.speed if self.status == AssetStatus.EXECUTING else 0.0,
            altitude=self.altitude,
            status=self.status,
            mission_type=self.mission_type,
            current_waypoint_index=self.current_wp_index,
            total_waypoints=len(self.waypoints),
            drone_pattern=self.pattern,
        )
