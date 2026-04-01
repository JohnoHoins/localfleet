"""Drone sensor model — detection range and FOV for targeting."""
import math
from dataclasses import dataclass


DRONE_SENSOR_RANGE = 3000.0  # meters
DRONE_SENSOR_FOV = 120.0     # degrees, forward-looking


@dataclass
class TargetingData:
    contact_id: str
    bearing: float       # radians from drone to contact
    range_m: float       # meters
    contact_x: float     # estimated contact position
    contact_y: float
    confidence: float    # 1.0 at 0m, degrades with range
    locked: bool = False # True when drone is tracking + in range + in FOV


def drone_detect_contacts(drone_x: float, drone_y: float,
                          drone_heading: float, contacts: dict,
                          sensor_range: float = DRONE_SENSOR_RANGE,
                          fov_deg: float = DRONE_SENSOR_FOV
                          ) -> list[TargetingData]:
    """Return targeting data for contacts visible to drone sensor."""
    results = []
    half_fov = math.radians(fov_deg / 2)
    for cid, contact in contacts.items():
        dx = contact.x - drone_x
        dy = contact.y - drone_y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > sensor_range:
            continue
        bearing = math.atan2(dy, dx)
        # Check FOV
        angle_diff = (bearing - drone_heading + math.pi) % (2 * math.pi) - math.pi
        if abs(angle_diff) > half_fov:
            continue
        confidence = max(0.3, 1.0 - (dist / sensor_range) * 0.7)
        results.append(TargetingData(
            contact_id=cid, bearing=bearing, range_m=dist,
            contact_x=contact.x, contact_y=contact.y,
            confidence=confidence, locked=False,
        ))
    return results
