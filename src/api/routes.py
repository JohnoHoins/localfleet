"""
REST endpoints for LocalFleet.
POST /api/command       — send NL command
GET  /api/assets        — current fleet state
GET  /api/mission       — active mission info
POST /api/gps-mode      — toggle GPS degradation
POST /api/voice-command — send audio, get transcription + command
GET  /api/logs          — retrieve mission log events
GET  /api/logs/summary  — mission log summary
"""
import os
import tempfile
import time
from typing import Optional

from fastapi import APIRouter, Query, Request, UploadFile, File

from pydantic import BaseModel

from src.schemas import (
    CommandRequest, CommandResponse, FleetState, GpsDeniedRequest,
    Contact, DomainType, FleetCommand,
)
from src.voice.whisper_local import transcribe_audio


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/command", response_model=CommandResponse)
    async def post_command(req: CommandRequest, request: Request):
        """Parse NL text and dispatch to fleet."""
        commander = request.app.state.commander
        if commander.fleet_manager.comms_mode == "denied":
            return CommandResponse(success=False, error="COMMS DENIED — fleet operating autonomously")
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

    class CommsModeRequest(BaseModel):
        mode: str  # "full" or "denied"

    @router.post("/comms-mode")
    async def post_comms_mode(req: CommsModeRequest, request: Request):
        fm = request.app.state.commander.fleet_manager
        fm.set_comms_mode(req.mode)
        elapsed = 0.0
        if fm.comms_mode == "denied" and fm.comms_denied_since:
            elapsed = time.time() - fm.comms_denied_since
        return {
            "comms_mode": fm.comms_mode,
            "autonomous_actions": fm.autonomous_actions[-10:],
            "denied_duration": elapsed,
        }

    @router.post("/return-to-base")
    async def post_return_to_base(request: Request):
        """Trigger comms-lost return-to-base for all assets."""
        commander = request.app.state.commander
        if commander.fleet_manager.comms_mode == "denied":
            return {"success": False, "error": "COMMS DENIED — fleet operating autonomously"}
        commander.return_to_base()
        return {"success": True, "action": "return_to_base"}

    @router.post("/voice-command", response_model=CommandResponse)
    async def post_voice_command(request: Request, audio: UploadFile = File(...)):
        """Transcribe uploaded audio and dispatch as fleet command."""
        tmp_path = None
        try:
            suffix = os.path.splitext(audio.filename or ".wav")[1] or ".wav"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await audio.read())
                tmp_path = tmp.name

            # Frontend sends 16kHz mono WAV — pass directly to Whisper
            text = transcribe_audio(tmp_path)
            commander = request.app.state.commander
            req = CommandRequest(text=text, source="voice")
            return commander.handle_command(req)
        except Exception as e:
            return CommandResponse(success=False, error=str(e))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @router.post("/command-direct")
    async def post_command_direct(cmd: FleetCommand, request: Request):
        """Accept a structured FleetCommand directly, bypassing the LLM."""
        commander = request.app.state.commander
        fm = commander.fleet_manager
        if fm.comms_mode == "denied":
            return {"success": False, "error": "COMMS DENIED — fleet operating autonomously"}
        fm.dispatch_command(cmd)
        commander.last_command = cmd
        return {"success": True, "fleet_command": cmd.model_dump()}

    # ------------------------------------------------------------------
    # Contacts (simulated targets)
    # ------------------------------------------------------------------

    class SpawnContactRequest(BaseModel):
        contact_id: str
        x: float
        y: float
        heading: float        # radians, math convention
        speed: float = 3.0    # m/s
        domain: DomainType = DomainType.SURFACE

    @router.get("/contacts")
    async def get_contacts(request: Request):
        """List active contacts."""
        fm = request.app.state.commander.fleet_manager
        return {"contacts": [c.model_dump() for c in fm.contacts.values()]}

    @router.post("/contacts")
    async def post_contact(req: SpawnContactRequest, request: Request):
        """Spawn a simulated contact/target."""
        fm = request.app.state.commander.fleet_manager
        contact = fm.spawn_contact(
            req.contact_id, req.x, req.y, req.heading, req.speed, req.domain,
        )
        return {"success": True, "contact": contact.model_dump()}

    @router.delete("/contacts/{contact_id}")
    async def delete_contact(contact_id: str, request: Request):
        """Remove a contact by ID."""
        fm = request.app.state.commander.fleet_manager
        removed = fm.remove_contact(contact_id)
        return {"success": removed, "contact_id": contact_id}

    @router.get("/logs")
    async def get_logs(
        request: Request,
        event_type: Optional[str] = Query(None),
        asset_id: Optional[str] = Query(None),
        limit: int = Query(200),
    ):
        """Retrieve logged mission events with optional filters."""
        logger = getattr(request.app.state, "logger", None)
        if logger is None:
            return {"events": [], "count": 0}
        events = logger.get_events(
            event_type=event_type, asset_id=asset_id, limit=limit,
        )
        return {
            "events": [e.model_dump(mode="json") for e in events],
            "count": len(events),
        }

    @router.get("/logs/summary")
    async def get_logs_summary(request: Request):
        """Return a summary of logged mission events."""
        logger = getattr(request.app.state, "logger", None)
        if logger is None:
            return {"total_events": 0, "commands": 0, "state_snapshots": 0, "gps_changes": 0, "duration_seconds": 0}
        return {
            "total_events": logger.count_events(),
            "commands": logger.count_events("command"),
            "state_snapshots": logger.count_events("state"),
            "gps_changes": logger.count_events("gps_change"),
        }

    return router
