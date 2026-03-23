"""
Formations — Surface vessel formation geometry.
Given a reference point, heading, formation type, and spacing,
computes offset positions for each vessel in the group.
Surface-only. Drone uses DroneCoordinator patterns instead.
"""
import math
from typing import Dict, List

from src.schemas import Waypoint, FormationType


def compute_formation_offsets(
    vessel_ids: List[str],
    formation: FormationType,
    spacing: float = 200.0,
) -> Dict[str, Waypoint]:
    """Return offsets (meters) relative to the leader for each vessel.

    The leader (vessel_ids[0]) always gets offset (0, 0).
    Offsets are in body-frame: x = right of heading, y = behind heading.
    Caller rotates by heading before adding to leader's world position.
    """
    offsets: Dict[str, Waypoint] = {}
    n = len(vessel_ids)

    for i, vid in enumerate(vessel_ids):
        if i == 0:
            offsets[vid] = Waypoint(x=0.0, y=0.0)
            continue

        if formation == FormationType.ECHELON:
            # Diagonal: each vessel offset right and behind
            offsets[vid] = Waypoint(x=i * spacing, y=-i * spacing)

        elif formation == FormationType.LINE_ABREAST:
            # Side by side, centered on leader
            offsets[vid] = Waypoint(x=i * spacing, y=0.0)

        elif formation == FormationType.COLUMN:
            # Single file behind leader
            offsets[vid] = Waypoint(x=0.0, y=-i * spacing)

        elif formation == FormationType.SPREAD:
            # Like line abreast but wider (1.5x spacing)
            offsets[vid] = Waypoint(x=i * spacing * 1.5, y=0.0)

        else:  # INDEPENDENT
            offsets[vid] = Waypoint(x=0.0, y=0.0)

    return offsets


def apply_formation(
    leader_x: float,
    leader_y: float,
    heading_deg: float,
    vessel_ids: List[str],
    formation: FormationType,
    spacing: float = 200.0,
) -> Dict[str, Waypoint]:
    """Compute world-frame positions for each vessel in formation.

    heading_deg: leader heading in degrees (0 = North).
    Returns dict of asset_id -> Waypoint in world coordinates.
    """
    offsets = compute_formation_offsets(vessel_ids, formation, spacing)
    heading_rad = math.radians(heading_deg)

    # Rotation: body-frame (right, behind) -> world-frame (x, y)
    cos_h = math.cos(heading_rad)
    sin_h = math.sin(heading_rad)

    positions: Dict[str, Waypoint] = {}
    for vid, off in offsets.items():
        # body x = starboard (right), body y = forward/aft
        wx = leader_x + off.x * cos_h + off.y * sin_h
        wy = leader_y - off.x * sin_h + off.y * cos_h
        positions[vid] = Waypoint(x=wx, y=wy)

    return positions
