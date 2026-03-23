"""
REST endpoints for LocalFleet.
POST /api/command       — send NL command
GET  /api/assets        — current fleet state
GET  /api/mission       — active mission info
POST /api/gps-mode      — toggle GPS degradation
POST /api/voice-command — send audio, get transcription + command
"""
import os
import tempfile

from fastapi import APIRouter, Request, UploadFile, File

from src.schemas import (
    CommandRequest, CommandResponse, FleetState, GpsDeniedRequest,
)
from src.voice.whisper_local import transcribe_audio


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

    return router
