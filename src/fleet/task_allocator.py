"""
TaskAllocator — Cross-domain mission assignment.
Maps mission types to asset roles by domain (surface vs air).
Decides which assets do what based on mission + available fleet.
"""
from typing import Dict, List

from src.schemas import (
    MissionType, DomainType, DronePattern, FormationType,
)


# What each mission type means for each domain
MISSION_ROLES: Dict[MissionType, dict] = {
    MissionType.PATROL: {
        "surface_behavior": "waypoint",
        "surface_formation": FormationType.ECHELON,
        "air_pattern": DronePattern.ORBIT,
        "air_altitude": 120.0,
        "description": "Surface vessels patrol waypoints in formation, drone orbits overhead",
    },
    MissionType.SEARCH: {
        "surface_behavior": "waypoint",
        "surface_formation": FormationType.LINE_ABREAST,
        "air_pattern": DronePattern.SWEEP,
        "air_altitude": 80.0,
        "description": "Surface vessels sweep in line, drone sweeps from altitude",
    },
    MissionType.ESCORT: {
        "surface_behavior": "waypoint",
        "surface_formation": FormationType.COLUMN,
        "air_pattern": DronePattern.ORBIT,
        "air_altitude": 150.0,
        "description": "Surface vessels escort in column, drone orbits the convoy",
    },
    MissionType.LOITER: {
        "surface_behavior": "loiter",
        "surface_formation": FormationType.SPREAD,
        "air_pattern": DronePattern.STATION,
        "air_altitude": 100.0,
        "description": "Surface vessels hold spread positions, drone holds station",
    },
    MissionType.AERIAL_RECON: {
        "surface_behavior": "waypoint",
        "surface_formation": FormationType.INDEPENDENT,
        "air_pattern": DronePattern.SWEEP,
        "air_altitude": 100.0,
        "description": "Drone-primary mission: sweep area, surface vessels standby",
    },
}


def get_mission_roles(mission_type: MissionType) -> dict:
    """Return role config for a given mission type."""
    return MISSION_ROLES.get(mission_type, MISSION_ROLES[MissionType.PATROL])


def allocate_assets(
    mission_type: MissionType,
    available_assets: List[dict],
) -> Dict[str, dict]:
    """Assign roles to each asset based on mission type and domain.

    available_assets: list of {"asset_id": str, "domain": DomainType}
    Returns: dict of asset_id -> {"behavior": str, "formation": FormationType,
                                   "drone_pattern": DronePattern | None,
                                   "altitude": float | None}
    """
    roles = get_mission_roles(mission_type)
    assignments: Dict[str, dict] = {}

    for asset in available_assets:
        aid = asset["asset_id"]
        domain = asset["domain"]

        if domain == DomainType.SURFACE:
            assignments[aid] = {
                "behavior": roles["surface_behavior"],
                "formation": roles["surface_formation"],
                "drone_pattern": None,
                "altitude": None,
            }
        elif domain == DomainType.AIR:
            assignments[aid] = {
                "behavior": roles["air_pattern"].value,
                "formation": FormationType.INDEPENDENT,
                "drone_pattern": roles["air_pattern"],
                "altitude": roles["air_altitude"],
            }

    return assignments
