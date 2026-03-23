"""
REST endpoints for LocalFleet.
POST /api/command — send NL command
GET  /api/assets  — current fleet state
GET  /api/mission — active mission info
POST /api/gps-mode — toggle GPS degradation
"""
from fastapi import APIRouter, Request

from src.schemas import (
    CommandRequest, CommandResponse, FleetState, GpsDeniedRequest,
)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/command", response_model=CommandResponse)
    async def post_command(req: CommandRequest, request: Request):
        """Parse NL text and dispatch to fleet."""
        commander = request.app.state.commander
        return commander.handle_command(req)

    @router.get("/assets", response_model=FleetState)
    async def get_assets(request: Request):
        """Return current state of all assets."""
        commander = request.app.state.commander
        return commander.get_state()

    @router.get("/mission")
    async def get_mission(request: Request):
        """Return active mission info."""
        commander = request.app.state.commander
        cmd = commander.last_command
        return {
            "active_mission": commander.fleet_manager.active_mission,
            "formation": commander.fleet_manager.formation,
            "last_command": cmd.model_dump() if cmd else None,
        }

    @router.post("/gps-mode")
    async def post_gps_mode(req: GpsDeniedRequest, request: Request):
        """Toggle GPS degradation."""
        commander = request.app.state.commander
        commander.handle_gps_mode(req)
        return {
            "gps_mode": req.mode.value,
            "noise_meters": req.noise_meters,
        }

    return router
