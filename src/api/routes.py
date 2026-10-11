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
import asyncio
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

from fastapi import APIRouter, FastAPI, Query, Request, UploadFile, File
from fastapi.responses import JSONResponse

from pydantic import BaseModel, Field, field_validator

from src.schemas import (
    CommandRequest, CommandResponse, FleetState, GpsDeniedRequest,
    Contact, DomainType, FleetCommand,
)
from src.fleet.fleet_commander import (
    COMMS_DENIED_ERROR, FleetCommander, validate_command,
)
from src.fleet.fleet_manager import FleetManager
from src.voice.whisper_local import transcribe_audio

# One dedicated thread for Whisper: transcription stays off the event loop
# (sim loop and sockets keep running), overlapping requests queue up, and
# the MLX model always runs on the thread that loaded it.
_WHISPER_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")


def attach_decision_sink(app: FastAPI) -> None:
    """Queue every decision of the current fleet for the mission log.

    Must be re-run whenever /api/reset swaps in a new FleetManager. The sink
    only queues; flush_decisions() writes to SQLite outside step().
    """
    decision_log = app.state.commander.fleet_manager.decision_log
    setattr(decision_log, "on_log", app.state.pending_decisions.append)


def flush_decisions(app: FastAPI) -> None:
    """Write queued decisions to the mission log."""
    logger = getattr(app.state, "logger", None)
    pending = getattr(app.state, "pending_decisions", None)
    if logger is None or not pending:
        return
    entries = []
    try:
        while True:
            entries.append(pending.popleft())
    except IndexError:
        pass
    logger.log_decisions(entries)


async def _parse_then_dispatch(commander: FleetCommander, req: CommandRequest,
                               fleet_manager: FleetManager) -> CommandResponse:
    """Run the slow LLM parse in a worker thread, then dispatch on the event
    loop, so dispatch never races step(). dispatch_parsed re-checks comms and
    reset first: the link may have dropped during the 15–21 s parse."""
    parsed = await asyncio.to_thread(commander.parse_command, req)
    if isinstance(parsed, CommandResponse):
        return parsed
    return commander.dispatch_parsed(req, parsed, fleet_manager)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/command", response_model=CommandResponse)
    async def post_command(req: CommandRequest, request: Request):
        """Parse NL text and dispatch to fleet."""
        commander = request.app.state.commander
        fm = commander.fleet_manager
        if fm.comms_mode == "denied":
            return CommandResponse(success=False, error=COMMS_DENIED_ERROR)
        return await _parse_then_dispatch(commander, req, fm)

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
        mode: Literal["full", "denied"]

        @field_validator("mode", mode="before")
        @classmethod
        def _lower(cls, v):
            return v.strip().lower() if isinstance(v, str) else v

    @router.post("/comms-mode")
    async def post_comms_mode(req: CommsModeRequest, request: Request):
        fm = request.app.state.commander.fleet_manager
        previous = fm.comms_mode
        fm.set_comms_mode(req.mode)
        elapsed = 0.0
        if fm.comms_mode == "denied" and fm.comms_denied_since:
            elapsed = fm._comms_denied_steps * 0.25  # sim-seconds
        logger = getattr(request.app.state, "logger", None)
        if logger and fm.comms_mode != previous:
            logger.log_comms_change(fm.comms_mode, fm.autonomous_actions[-10:])
        return {
            "comms_mode": fm.comms_mode,
            "autonomous_actions": fm.autonomous_actions[-10:],
            "denied_duration": elapsed,
        }

    @router.post("/reset")
    async def post_reset(request: Request):
        """Reset fleet to initial state — all assets at home, no mission, no contacts."""
        app = request.app
        commander = app.state.commander
        # Persist the old fleet's decisions before it is dropped
        flush_decisions(app)
        logger = getattr(app.state, "logger", None)
        if logger:
            logger.log_reset()
        commander.fleet_manager = FleetManager()
        attach_decision_sink(app)
        commander.last_command = None
        commander.last_parse_info = None
        return {"success": True, "message": "Fleet reset to initial state"}

    class TimeScaleRequest(BaseModel):
        scale: int  # 1, 2, 4, or 8

    @router.post("/time-scale")
    async def post_time_scale(req: TimeScaleRequest, request: Request):
        """Set simulation speed multiplier (sub-steps per tick)."""
        scale = max(1, min(8, req.scale))
        request.app.state.time_scale = scale
        return {"time_scale": scale}

    @router.get("/time-scale")
    async def get_time_scale(request: Request):
        return {"time_scale": getattr(request.app.state, "time_scale", 1)}

    @router.post("/return-to-base")
    async def post_return_to_base(request: Request):
        """Trigger comms-lost return-to-base for all assets."""
        commander = request.app.state.commander
        if commander.fleet_manager.comms_mode == "denied":
            return {"success": False, "error": COMMS_DENIED_ERROR}
        commander.return_to_base()
        return {"success": True, "action": "return_to_base"}

    @router.post("/voice-command", response_model=CommandResponse)
    async def post_voice_command(request: Request, audio: UploadFile = File(...)):
        """Transcribe uploaded audio and dispatch as fleet command."""
        commander = request.app.state.commander
        fm = commander.fleet_manager
        if fm.comms_mode == "denied":
            return CommandResponse(success=False, error=COMMS_DENIED_ERROR)
        tmp_path = None
        text = None
        try:
            suffix = os.path.splitext(audio.filename or ".wav")[1] or ".wav"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await audio.read())
                tmp_path = tmp.name

            # Frontend sends 16kHz mono WAV — pass directly to Whisper
            text = await asyncio.get_running_loop().run_in_executor(
                _WHISPER_EXECUTOR, transcribe_audio, tmp_path,
            )
            if not text.strip():
                return CommandResponse(success=False, error="No speech detected", transcript=text)
            req = CommandRequest(text=text, source="voice")
            resp = await _parse_then_dispatch(commander, req, fm)
            return resp.model_copy(update={"transcript": text})
        except Exception as e:
            return CommandResponse(success=False, error=str(e), transcript=text)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @router.post("/command-direct")
    async def post_command_direct(cmd: FleetCommand, request: Request):
        """Accept a structured FleetCommand directly, bypassing the LLM."""
        commander = request.app.state.commander
        fm = commander.fleet_manager
        if fm.comms_mode == "denied":
            return {"success": False, "error": COMMS_DENIED_ERROR}
        # Same sanitizing as LLM commands (unknown IDs, NaN, land waypoints...)
        warnings = validate_command(cmd)
        if not cmd.assets:
            return JSONResponse(status_code=422, content={
                "success": False,
                "error": "No valid assets in command: " + "; ".join(warnings),
                "warnings": warnings,
            })
        fm.dispatch_command(cmd)
        commander.last_command = cmd
        if commander.logger:
            commander.logger.log_command(cmd)
        commander.last_parse_info = {
            "text": f"[direct] {cmd.mission_type.value}" if cmd.mission_type else "[direct]",
            "method": "direct",
            "time_ms": 0,
            "mission": cmd.mission_type.value if cmd.mission_type else None,
            "formation": cmd.formation.value if cmd.formation else None,
        }
        return {"success": True, "fleet_command": cmd.model_dump(), "warnings": warnings}

    # ------------------------------------------------------------------
    # Decision audit trail
    # ------------------------------------------------------------------

    @router.get("/decisions")
    async def get_decisions(request: Request,
                            limit: int = Query(50),
                            dtype: Optional[str] = Query(None, alias="type")):
        fm = request.app.state.commander.fleet_manager
        if dtype:
            entries = fm.decision_log.get_by_type(dtype)[-limit:]
        else:
            entries = fm.decision_log.get_recent(limit)
        return {"decisions": [
            {"id": e.id, "timestamp": e.timestamp, "type": e.decision_type,
             "action": e.action_taken, "rationale": e.rationale,
             "confidence": e.confidence, "assets": e.assets_involved,
             "alternatives": e.alternatives, "parent_id": e.parent_id}
            for e in entries
        ]}

    # ------------------------------------------------------------------
    # Contacts (simulated targets)
    # ------------------------------------------------------------------

    class SpawnContactRequest(BaseModel):
        contact_id: str
        x: float = Field(allow_inf_nan=False)
        y: float = Field(allow_inf_nan=False)
        heading: float = Field(allow_inf_nan=False)    # radians, math convention
        speed: float = Field(3.0, ge=0, allow_inf_nan=False)    # m/s
        domain: DomainType = DomainType.SURFACE

    @router.get("/contacts")
    async def get_contacts(request: Request):
        """List active contacts."""
        fm = request.app.state.commander.fleet_manager
        return {"contacts": [c.model_dump() for c in fm.contacts.values()]}

    @router.post("/contacts")
    async def post_contact(req: SpawnContactRequest, request: Request):
        """Spawn a simulated contact/target (replaces one with the same ID)."""
        fm = request.app.state.commander.fleet_manager
        replaced = req.contact_id in fm.contacts
        try:
            contact = fm.spawn_contact(
                req.contact_id, req.x, req.y, req.heading, req.speed, req.domain,
            )
        except ValueError as e:
            return JSONResponse(status_code=422, content={"success": False, "error": str(e)})
        return {"success": True, "contact": contact.model_dump(), "replaced": replaced}

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
        flush_decisions(request.app)
        events = logger.get_events(
            event_type=event_type, asset_id=asset_id, limit=limit, newest=True,
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
            return {"total_events": 0, "commands": 0, "state_snapshots": 0, "gps_changes": 0,
                    "decisions": 0, "duration_seconds": 0}
        flush_decisions(request.app)
        return {
            "total_events": logger.count_events(),
            "commands": logger.count_events("command"),
            "state_snapshots": logger.count_events("state"),
            "gps_changes": logger.count_events("gps_change"),
            "decisions": logger.count_events("decision"),
            "duration_seconds": logger.duration_seconds(),
        }

    return router
