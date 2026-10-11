"""
FastAPI application — LocalFleet backend.
CORS-enabled, mounts routes and WebSocket handler.
Background sim loop runs at 4Hz regardless of WebSocket connections.
"""
import asyncio
import collections
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.fleet.fleet_commander import FleetCommander
from src.logging.mission_logger import MissionLogger
from src.api.routes import attach_decision_sink, create_router, flush_decisions
from src.api.ws import create_ws_router
from src.api.monitor_ws import create_monitor_router

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

SIM_DT = 0.25  # 4Hz simulation tick
LOG_INTERVAL = 20  # Log a state snapshot every 20 ticks (5 seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background simulation loop on startup, cancel on shutdown."""
    app.state.time_scale = 1  # 1x, 2x, 4x, 8x
    task = asyncio.create_task(_sim_loop(app))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    flush_decisions(app)


async def _sim_loop(app: FastAPI):
    """Advance simulation at 4Hz, running time_scale sub-steps per tick."""
    import time as _time
    app.state.tick_count = 0
    app.state.last_step_time_us = 0
    last_error = None
    while True:
        t0 = _time.perf_counter()
        try:
            for _ in range(app.state.time_scale):
                app.state.commander.step(SIM_DT)
            last_error = None
        except Exception as e:  # a failing step must not silently end the loop
            if repr(e) != last_error:
                log.exception("Simulation step failed")
            last_error = repr(e)
        app.state.last_step_time_us = int((_time.perf_counter() - t0) * 1_000_000)
        app.state.tick_count += 1
        # Log state from the sim loop so the mission log is complete whether
        # or not a dashboard is connected (and not duplicated per client)
        logger = getattr(app.state, "logger", None)
        if logger:
            try:
                if app.state.pending_decisions:
                    await asyncio.to_thread(flush_decisions, app)
                if app.state.tick_count % LOG_INTERVAL == 0:
                    await asyncio.to_thread(logger.log_state, app.state.commander.get_state())
            except Exception:  # never let logging stop the simulation
                pass
        await asyncio.sleep(SIM_DT)


async def _validation_error(request: Request, exc: RequestValidationError):
    """422 in the same {success, error} shape as every other refusal."""
    errors = exc.errors()
    message = "; ".join(
        f"{'.'.join(str(p) for p in err.get('loc', ()) if p != 'body')}: {err.get('msg')}"
        for err in errors
    )
    # Echoing the rejected input back could itself be NaN, which isn't JSON
    detail = [{k: err.get(k) for k in ("type", "loc", "msg")} for err in errors]
    return JSONResponse(status_code=422, content={
        "success": False,
        "error": f"Invalid request — {message}",
        "detail": jsonable_encoder(detail),
    })


def create_app(
    commander: FleetCommander | None = None,
    logger: MissionLogger | None = None,
) -> FastAPI:
    """Factory: build and return the FastAPI app."""
    logger = logger or MissionLogger()
    commander = commander or FleetCommander(logger=logger)

    app = FastAPI(title="LocalFleet", version="1.0.0", lifespan=lifespan)

    # Permissive CORS — intentional for local-only development/demo use
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(RequestValidationError, _validation_error)

    # Store commander and logger on app state for routes/ws to access
    app.state.commander = commander
    app.state.logger = logger

    # Autonomous decisions are queued here and persisted by the sim loop
    app.state.pending_decisions = collections.deque(maxlen=10_000)
    attach_decision_sink(app)

    app.include_router(create_router(), prefix="/api")
    app.include_router(create_ws_router())
    app.include_router(create_monitor_router())

    return app


app = create_app()
