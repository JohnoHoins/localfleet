"""
Threat Detector — Evaluates contacts against fleet position.
Assigns threat levels based on range and closing rate.
Used by FleetManager to auto-retask drone and recommend intercept.
"""
import math
from dataclasses import dataclass
from typing import Dict, List

from src.schemas import Contact


# Detection range thresholds (meters)
RANGE_NONE = 8000.0       # > 8km: not detected
RANGE_DETECTED = 5000.0   # 5-8km: detected, monitor
RANGE_WARNING = 2000.0    # 2-5km: warning, track
# < 2km: critical, intercept


@dataclass
class ThreatAssessment:
    """Evaluation of a single contact relative to the fleet."""
    contact_id: str
    distance: float          # meters from fleet centroid
    bearing: float           # radians from fleet centroid to contact
    closing_rate: float      # m/s — negative means closing
    threat_level: str        # "none", "detected", "warning", "critical"
    recommended_action: str  # "monitor", "track", "intercept"
    reason: str              # human-readable explanation


def assess_threats(
    vessels: Dict[str, dict],
    contacts: Dict[str, Contact],
) -> List[ThreatAssessment]:
    """Evaluate all contacts against fleet centroid position.

    Args:
        vessels: FleetManager.vessels dict (state arrays keyed by vessel id)
        contacts: FleetManager.contacts dict (Contact objects keyed by id)

    Returns:
        List of ThreatAssessment, one per contact.
    """
    if not contacts:
        return []

    # Compute fleet centroid from surface vessel positions
    if not vessels:
        return []
    cx = sum(v["state"][0] for v in vessels.values()) / len(vessels)
    cy = sum(v["state"][1] for v in vessels.values()) / len(vessels)

    assessments: List[ThreatAssessment] = []

    for cid, contact in contacts.items():
        dx = contact.x - cx
        dy = contact.y - cy
        distance = math.sqrt(dx * dx + dy * dy)

        # Bearing from fleet centroid to contact (radians, math convention)
        bearing = math.atan2(dy, dx)

        # Closing rate: project contact 1s forward, compare distances
        proj_x = contact.x + contact.speed * math.cos(contact.heading)
        proj_y = contact.y + contact.speed * math.sin(contact.heading)
        proj_dist = math.sqrt((proj_x - cx) ** 2 + (proj_y - cy) ** 2)
        # Positive = opening, negative = closing
        closing_rate = proj_dist - distance

        # Classify threat level
        if distance > RANGE_NONE:
            threat_level = "none"
            action = "monitor"
        elif distance > RANGE_DETECTED:
            threat_level = "detected"
            action = "monitor"
        elif distance > RANGE_WARNING:
            threat_level = "warning"
            action = "track"
        else:
            threat_level = "critical"
            action = "intercept"

        # Nautical bearing for display: 0=North, CW+
        bearing_deg = (90 - math.degrees(bearing)) % 360
        dist_km = distance / 1000.0

        if threat_level == "critical":
            reason = (
                f"{cid} CRITICAL at {dist_km:.1f}km bearing "
                f"{bearing_deg:03.0f}\u00b0, closing at {abs(closing_rate):.1f} m/s "
                f"\u2014 INTERCEPT recommended"
            )
        elif threat_level == "warning":
            reason = (
                f"{cid} WARNING at {dist_km:.1f}km bearing "
                f"{bearing_deg:03.0f}\u00b0, closing at {abs(closing_rate):.1f} m/s"
            )
        else:
            reason = (
                f"{cid} detected at {dist_km:.1f}km bearing "
                f"{bearing_deg:03.0f}\u00b0, closing at {abs(closing_rate):.1f} m/s"
            )

        assessments.append(ThreatAssessment(
            contact_id=cid,
            distance=distance,
            bearing=bearing,
            closing_rate=closing_rate,
            threat_level=threat_level,
            recommended_action=action,
            reason=reason,
        ))

    return assessments
