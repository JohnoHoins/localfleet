"""
FleetCommander — Bridges natural language to FleetManager.
Commands are parsed by a local 72B parameter LLM via Ollama.
"""
import logging
import time
from typing import TYPE_CHECKING

from src.schemas import (
    FleetCommand, CommandRequest, CommandResponse, GpsMode, GpsDeniedRequest,
    AssetCommand, Waypoint, DomainType, MissionType, FormationType, DronePattern,
)
from src.llm.ollama_client import parse_fleet_command
from src.fleet.fleet_manager import FleetManager

if TYPE_CHECKING:
    from src.logging.mission_logger import MissionLogger

logger = logging.getLogger(__name__)

# Validation constants
VALID_ASSET_IDS = {"alpha", "bravo", "charlie", "eagle-1"}
MAX_RANGE = 5000  # meters — operating area bounds
MIN_SURFACE_SPEED = 1.0
MAX_SURFACE_SPEED = 10.0
MIN_AIR_SPEED = 5.0
MAX_AIR_SPEED = 25.0
MIN_ALTITUDE = 10.0
MAX_ALTITUDE = 500.0


def validate_command(command: FleetCommand) -> list[str]:
    """Validate and sanitize a parsed FleetCommand. Returns list of warnings."""
    warnings = []

    # Filter out invalid asset IDs
    valid_assets = []
    for ac in command.assets:
        if ac.asset_id not in VALID_ASSET_IDS:
            warnings.append(f"Unknown asset_id '{ac.asset_id}' removed")
            continue
        valid_assets.append(ac)
    command.assets = valid_assets

    for ac in command.assets:
        # Clamp waypoints to operating area
        for wp in ac.waypoints:
            clamped_x = max(-MAX_RANGE, min(MAX_RANGE, wp.x))
            clamped_y = max(-MAX_RANGE, min(MAX_RANGE, wp.y))
            if clamped_x != wp.x or clamped_y != wp.y:
                warnings.append(
                    f"{ac.asset_id}: waypoint ({wp.x}, {wp.y}) clamped to ({clamped_x}, {clamped_y})"
                )
                wp.x = clamped_x
                wp.y = clamped_y

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

    return warnings


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
        t0 = time.time()
        try:
            command = parse_fleet_command(request.text)
            elapsed_ms = (time.time() - t0) * 1000.0
            logger.info("LLM parse: %s → %s", request.text[:60], command.mission_type)

            # Validate and sanitize the parsed command
            warnings = validate_command(command)
            for w in warnings:
                logger.warning("Command validation: %s", w)

            if not command.assets:
                return CommandResponse(
                    success=False,
                    error="No valid assets in command after validation",
                    llm_response_time_ms=elapsed_ms,
                )

            self.fleet_manager.dispatch_command(command)
            self.last_command = command
            self.last_parse_info = {
                "text": request.text,
                "method": "llm",
                "time_ms": elapsed_ms,
                "mission": command.mission_type.value if command.mission_type else None,
                "formation": command.formation.value if command.formation else None,
            }

            if self.logger:
                self.logger.log_command(command)

            # Build dispatch summary
            activated = [ac.asset_id for ac in command.assets]
            summary_parts = [f"Activated: {', '.join(activated)}"]
            if warnings:
                summary_parts.append(f"Warnings: {'; '.join(warnings)}")
            summary = ". ".join(summary_parts)

            return CommandResponse(
                success=True,
                fleet_command=command,
                llm_response_time_ms=elapsed_ms,
                error=summary if warnings else None,
            )
        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000.0
            logger.error("Command parse failed: %s", e)
            return CommandResponse(
                success=False,
                error=str(e),
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
