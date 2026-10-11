"""
FleetCommander — Bridges natural language to FleetManager.
Commands are parsed by a local 72B parameter LLM via Ollama.
"""
import logging
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.schemas import (
    FleetCommand, CommandRequest, CommandResponse, GpsMode, GpsDeniedRequest,
    AssetCommand, Waypoint, DomainType, MissionType, FormationType, DronePattern,
)
from src.llm.ollama_client import parse_fleet_command
from src.fleet.fleet_manager import FleetManager
from src.navigation.land_check import is_on_land, nearest_water_point

if TYPE_CHECKING:
    from src.logging.mission_logger import MissionLogger

logger = logging.getLogger(__name__)

# Validation constants
# The roster decides each asset's domain; the LLM's label is not trusted
ROSTER_DOMAINS = {
    "alpha": DomainType.SURFACE,
    "bravo": DomainType.SURFACE,
    "charlie": DomainType.SURFACE,
    "eagle-1": DomainType.AIR,
}
VALID_ASSET_IDS = set(ROSTER_DOMAINS)
# Spoken/LLM spellings of roster IDs (after lower-casing, '_' and ' ' → '-')
ASSET_ALIASES = {
    "alfa": "alpha",
    "eagle": "eagle-1",
    "eagle1": "eagle-1",
    "eagle-one": "eagle-1",
    "drone": "eagle-1",
}
# Missions where dispatch derives surface waypoints from the contact
TARGET_MISSIONS = {MissionType.INTERCEPT, MissionType.ESCORT}
MAX_RANGE = 5000  # meters — operating area bounds
LAND_MARGIN = 100.0  # meters — how far off the coast a land waypoint is moved
MIN_SURFACE_SPEED = 1.0
MAX_SURFACE_SPEED = 10.0
MIN_AIR_SPEED = 5.0
MAX_AIR_SPEED = 25.0
MIN_ALTITUDE = 10.0
MAX_ALTITUDE = 500.0

COMMS_DENIED_ERROR = "COMMS DENIED — fleet operating autonomously"


def normalize_asset_id(raw: str) -> str:
    """'Alpha', 'alfa', 'eagle_1', 'Eagle One' → roster ID (unknown IDs pass through)."""
    key = "-".join(raw.strip().lower().replace("_", " ").replace("-", " ").split())
    return ASSET_ALIASES.get(key, key)


def validate_command(command: FleetCommand) -> list[str]:
    """Validate and sanitize a parsed FleetCommand in place.

    Returns a warning for every adjustment, so the operator sees what changed.
    """
    warnings = []

    # Resolve asset IDs against the roster, merging duplicate entries
    by_id: dict[str, AssetCommand] = {}
    for ac in command.assets:
        asset_id = normalize_asset_id(ac.asset_id)
        if asset_id not in VALID_ASSET_IDS:
            warnings.append(f"Unknown asset_id '{ac.asset_id}' removed")
            continue
        if asset_id != ac.asset_id:
            warnings.append(f"asset_id '{ac.asset_id}' read as '{asset_id}'")
            ac.asset_id = asset_id
        if asset_id in by_id:
            first = by_id[asset_id]
            first.waypoints.extend(wp for wp in ac.waypoints if wp not in first.waypoints)
            warnings.append(f"{asset_id}: duplicate entry merged into the first")
            continue
        roster_domain = ROSTER_DOMAINS[asset_id]
        if ac.domain != roster_domain:
            warnings.append(
                f"{asset_id}: domain '{ac.domain.value}' corrected to '{roster_domain.value}'"
            )
            ac.domain = roster_domain
        by_id[asset_id] = ac

    if not math.isfinite(command.spacing_meters):
        warnings.append(f"spacing {command.spacing_meters} is not a number, using 200")
        command.spacing_meters = 200.0

    valid_assets = []
    for ac in by_id.values():
        waypoints = []
        for wp in ac.waypoints:
            if not (math.isfinite(wp.x) and math.isfinite(wp.y)):
                warnings.append(f"{ac.asset_id}: waypoint ({wp.x}, {wp.y}) is not a number, removed")
                continue

            # Clamp waypoints to operating area
            clamped_x = max(-MAX_RANGE, min(MAX_RANGE, wp.x))
            clamped_y = max(-MAX_RANGE, min(MAX_RANGE, wp.y))
            if clamped_x != wp.x or clamped_y != wp.y:
                warnings.append(
                    f"{ac.asset_id}: waypoint ({wp.x}, {wp.y}) clamped to ({clamped_x}, {clamped_y})"
                )
                wp.x = clamped_x
                wp.y = clamped_y

            # Vessels can't go ashore (the drone may overfly land)
            if ac.domain == DomainType.SURFACE and is_on_land(wp.x, wp.y):
                nx, ny = map(float, nearest_water_point(wp.x, wp.y, margin=LAND_MARGIN))
                if is_on_land(nx, ny) or max(abs(nx), abs(ny)) > MAX_RANGE:
                    warnings.append(
                        f"{ac.asset_id}: waypoint ({wp.x:.0f}, {wp.y:.0f}) is on land, removed"
                    )
                    continue
                warnings.append(
                    f"{ac.asset_id}: waypoint ({wp.x:.0f}, {wp.y:.0f}) is on land, "
                    f"moved to ({nx:.0f}, {ny:.0f})"
                )
                wp.x, wp.y = nx, ny
            waypoints.append(wp)
        ac.waypoints = waypoints

        # An asset with nowhere to go would be dispatched as a silent no-op
        # (intercept/escort vessels get their waypoints from the contact)
        if not ac.waypoints and not (
            ac.domain == DomainType.SURFACE and command.mission_type in TARGET_MISSIONS
        ):
            warnings.append(f"{ac.asset_id}: no waypoints, not tasked")
            continue
        valid_assets.append(ac)

        # Clamp speed based on domain
        if ac.domain == DomainType.SURFACE:
            original = ac.speed
            ac.speed = max(MIN_SURFACE_SPEED, min(MAX_SURFACE_SPEED, ac.speed))
            if ac.speed != original:
                warnings.append(f"{ac.asset_id}: speed clamped {original} → {ac.speed}")
        elif ac.domain == DomainType.AIR:
            original = ac.speed
            ac.speed = max(MIN_AIR_SPEED, min(MAX_AIR_SPEED, ac.speed))
            if ac.speed != original:
                warnings.append(f"{ac.asset_id}: speed clamped {original} → {ac.speed}")

            # Clamp altitude for air assets
            if ac.altitude is not None:
                original = ac.altitude
                ac.altitude = max(MIN_ALTITUDE, min(MAX_ALTITUDE, ac.altitude))
                if ac.altitude != original:
                    warnings.append(
                        f"{ac.asset_id}: altitude clamped {original} → {ac.altitude}"
                    )
    command.assets = valid_assets

    return warnings


@dataclass
class ParsedCommand:
    """A validated FleetCommand that has not been dispatched yet."""
    command: FleetCommand
    warnings: list[str]
    elapsed_ms: float


class FleetCommander:
    def __init__(
        self,
        fleet_manager: FleetManager | None = None,
        logger: "MissionLogger | None" = None,
    ):
        self.fleet_manager = fleet_manager or FleetManager()
        self.last_command: FleetCommand | None = None
        self.logger = logger
        self.last_parse_info: dict | None = None

    def handle_command(self, request: CommandRequest) -> CommandResponse:
        """Parse natural language into FleetCommand via LLM and dispatch."""
        fleet_manager = self.fleet_manager
        if fleet_manager.comms_mode == "denied":
            return CommandResponse(success=False, error=COMMS_DENIED_ERROR)
        parsed = self.parse_command(request)
        if isinstance(parsed, CommandResponse):
            return parsed
        return self.dispatch_parsed(request, parsed, fleet_manager)

    def parse_command(self, request: CommandRequest) -> ParsedCommand | CommandResponse:
        """Parse and validate a command without dispatching it.

        This is the slow LLM call, safe to run off the event loop. Returns a
        failure CommandResponse when there is nothing to dispatch.
        """
        t0 = time.time()
        try:
            command = parse_fleet_command(request.text)
            elapsed_ms = (time.time() - t0) * 1000.0
            logger.info("LLM parse: %s → %s", request.text[:60], command.mission_type)

            # Validate and sanitize the parsed command
            warnings = validate_command(command)
        except Exception as e:
            logger.error("Command parse failed: %s", e)
            return self._failure(request, str(e), (time.time() - t0) * 1000.0)

        for w in warnings:
            logger.warning("Command validation: %s", w)

        if not command.assets:
            error = "No valid assets in command after validation"
            if warnings:
                error += ": " + "; ".join(warnings)
            return self._failure(request, error, elapsed_ms, warnings)

        return ParsedCommand(command=command, warnings=warnings, elapsed_ms=elapsed_ms)

    def dispatch_parsed(
        self,
        request: CommandRequest,
        parsed: ParsedCommand,
        fleet_manager: FleetManager | None = None,
    ) -> CommandResponse:
        """Dispatch a parsed command to the fleet it was parsed for.

        Call on the thread that steps the simulation. Refuses if the fleet was
        reset, or comms were lost, while the command was being parsed.
        """
        fleet_manager = fleet_manager or self.fleet_manager
        if self.fleet_manager is not fleet_manager:
            return self._failure(
                request, "Fleet was reset while the command was being parsed — command not sent",
                parsed.elapsed_ms, parsed.warnings,
            )
        if fleet_manager.comms_mode == "denied":
            return self._failure(
                request, "COMMS DENIED — link lost during parse, command not transmitted",
                parsed.elapsed_ms, parsed.warnings,
            )

        command = parsed.command
        try:
            fleet_manager.dispatch_command(command)
        except Exception as e:
            logger.error("Command dispatch failed: %s", e)
            return self._failure(request, str(e), parsed.elapsed_ms, parsed.warnings)

        self.last_command = command
        self.last_parse_info = {
            "text": request.text,
            "method": "llm",
            "time_ms": parsed.elapsed_ms,
            "mission": command.mission_type.value if command.mission_type else None,
            "formation": command.formation.value if command.formation else None,
        }

        if self.logger:
            self.logger.log_command(command)

        return CommandResponse(
            success=True,
            fleet_command=command,
            warnings=parsed.warnings,
            llm_response_time_ms=parsed.elapsed_ms,
        )

    def _failure(self, request: CommandRequest, error: str, elapsed_ms: float,
                 warnings: list[str] | None = None) -> CommandResponse:
        """Record a failed command for the System Monitor and build the response."""
        self.last_parse_info = {
            "text": request.text,
            "method": "llm",
            "time_ms": elapsed_ms,
            "mission": None,
            "formation": None,
            "error": error,
        }
        return CommandResponse(
            success=False,
            error=error,
            warnings=warnings or [],
            llm_response_time_ms=elapsed_ms,
        )

    def handle_text(self, text: str) -> CommandResponse:
        """Convenience: accept raw string instead of CommandRequest."""
        return self.handle_command(CommandRequest(text=text))

    def handle_gps_mode(self, request: GpsDeniedRequest):
        """Toggle GPS degradation on the fleet manager."""
        self.fleet_manager.set_gps_mode(request.mode, request.noise_meters)
        if self.logger:
            self.logger.log_gps_change(request.mode, request.noise_meters)

    def return_to_base(self):
        """Trigger comms_lost_behavior: return all assets to base."""
        self.fleet_manager.return_to_base()

    def step(self, dt: float = 0.25):
        """Advance the simulation one tick."""
        self.fleet_manager.step(dt)

    def get_state(self):
        """Get current fleet state."""
        return self.fleet_manager.get_fleet_state()

    def get_state_dict(self) -> dict:
        """Get fleet state as dict with threat data included."""
        return self.fleet_manager.get_fleet_state_dict()
