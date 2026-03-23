"""
FleetCommander — Bridges natural language to FleetManager.
Takes text input, calls the local LLM to produce a FleetCommand,
dispatches it to the FleetManager, and returns a CommandResponse.
"""
import time

from src.schemas import (
    FleetCommand, CommandRequest, CommandResponse, GpsMode, GpsDeniedRequest,
)
from src.llm.ollama_client import parse_fleet_command
from src.fleet.fleet_manager import FleetManager


class FleetCommander:
    def __init__(self, fleet_manager: FleetManager | None = None):
        self.fleet_manager = fleet_manager or FleetManager()
        self.last_command: FleetCommand | None = None

    def handle_command(self, request: CommandRequest) -> CommandResponse:
        """Parse NL text into FleetCommand and dispatch to fleet manager."""
        t0 = time.time()
        try:
            command = parse_fleet_command(request.text)
            elapsed_ms = (time.time() - t0) * 1000.0

            self.fleet_manager.dispatch_command(command)
            self.last_command = command

            return CommandResponse(
                success=True,
                fleet_command=command,
                llm_response_time_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000.0
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

    def step(self, dt: float = 0.25):
        """Advance the simulation one tick."""
        self.fleet_manager.step(dt)

    def get_state(self):
        """Get current fleet state."""
        return self.fleet_manager.get_fleet_state()
