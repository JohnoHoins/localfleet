"""
LocalFleet Data Contracts v2.0 — Multi-Domain
THE source of truth for all modules.
Every module imports from this file. DO NOT define data structures elsewhere.

v2.0 Changes:
- Added DomainType enum (SURFACE, AIR)
- Asset-generic naming (AssetCommand, AssetState)
- Altitude field for air domain
- GPS-denied degradation fields
- DronePattern enum for aerial behaviors
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime


# ============================================================
# ENUMS — Shared across all modules
# ============================================================

class DomainType(str, Enum):
    """Which domain this asset operates in."""
    SURFACE = "surface"    # Vessels — uses CORALL dynamics
    AIR = "air"            # Drones — uses drone_dynamics.py

class MissionType(str, Enum):
    """The 5 mission types LocalFleet supports. No more."""
    PATROL = "patrol"
    SEARCH = "search"
    ESCORT = "escort"
    LOITER = "loiter"
    AERIAL_RECON = "aerial_recon"

class FormationType(str, Enum):
    """How surface vessels arrange relative to each other."""
    ECHELON = "echelon"
    LINE_ABREAST = "line"
    COLUMN = "column"
    SPREAD = "spread"
    INDEPENDENT = "independent"

class DronePattern(str, Enum):
    """How a drone operates over an area."""
    ORBIT = "orbit"
    SWEEP = "sweep"
    TRACK = "track"
    STATION = "station"

class AssetStatus(str, Enum):
    """Current operational state of any asset."""
    IDLE = "idle"
    EXECUTING = "executing"
    AVOIDING = "avoiding"       # COLREGS avoidance (surface only)
    RETURNING = "returning"
    ERROR = "error"

class GpsMode(str, Enum):
    """GPS availability state."""
    FULL = "full"
    DEGRADED = "degraded"


# ============================================================
# COMMANDS — What the operator sends IN
# ============================================================

class Waypoint(BaseModel):
    """A point in 2D space (meters, local frame)."""
    x: float
    y: float

class AssetCommand(BaseModel):
    """
    Command for a single asset (surface OR air).
    The domain field determines which dynamics engine processes it.
    """
    asset_id: str               # "alpha", "bravo", "charlie", "eagle-1"
    domain: DomainType          # SURFACE or AIR
    waypoints: List[Waypoint]
    speed: float = 5.0          # m/s (surface ~5, drone ~15)
    altitude: Optional[float] = None  # meters — only for AIR domain
    behavior: str = "waypoint"  # "waypoint", "loiter", "search", "orbit", "sweep", "track"
    drone_pattern: Optional[DronePattern] = None  # Only for AIR domain

class FleetCommand(BaseModel):
    """
    THE central command object. The LLM produces this from natural
    language input. Every module that processes commands accepts this.
    Now supports BOTH surface and air assets in a single command.
    """
    mission_type: MissionType
    assets: List[AssetCommand]  # Can contain mixed SURFACE + AIR
    formation: FormationType = FormationType.INDEPENDENT
    spacing_meters: float = 200.0
    colregs_compliance: bool = True
    comms_lost_behavior: str = "return_to_base"
    raw_text: Optional[str] = None


# ============================================================
# STATE — What the simulation sends OUT
# ============================================================

class AssetState(BaseModel):
    """
    Current state of one asset (surface or air).
    Sent via WebSocket to the React dashboard every tick.
    """
    asset_id: str
    domain: DomainType
    x: float
    y: float
    heading: float              # Degrees, 0 = North
    speed: float
    altitude: Optional[float] = None
    status: AssetStatus
    mission_type: Optional[MissionType] = None
    current_waypoint_index: int = 0
    total_waypoints: int = 0
    risk_level: float = 0.0
    cpa: Optional[float] = None
    tcpa: Optional[float] = None
    drone_pattern: Optional[DronePattern] = None
    gps_mode: GpsMode = GpsMode.FULL
    position_accuracy: float = 1.0

class FleetState(BaseModel):
    """
    State of the entire fleet. Sent via WebSocket every tick (4Hz).
    The React dashboard receives this exact JSON shape.
    """
    timestamp: float
    assets: List[AssetState]
    active_mission: Optional[MissionType] = None
    formation: FormationType = FormationType.INDEPENDENT
    gps_mode: GpsMode = GpsMode.FULL


# ============================================================
# EVENTS — What gets logged
# ============================================================

class MissionEvent(BaseModel):
    """A logged event for mission replay."""
    timestamp: float
    event_type: str             # "command", "state", "decision", "risk", "gps_change"
    asset_id: Optional[str] = None
    domain: Optional[DomainType] = None
    data: dict
    created_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# API — Request/Response shapes for FastAPI endpoints
# ============================================================

class CommandRequest(BaseModel):
    """POST /api/command — what the dashboard sends."""
    text: str
    source: str = "text"

class CommandResponse(BaseModel):
    """POST /api/command — what the server responds with."""
    success: bool
    fleet_command: Optional[FleetCommand] = None
    error: Optional[str] = None
    llm_response_time_ms: Optional[float] = None

class GpsDeniedRequest(BaseModel):
    """POST /api/gps-mode — toggle GPS degradation."""
    mode: GpsMode
    noise_meters: float = 25.0
    update_rate_hz: float = 1.0
