"""
FastAPI application — LocalFleet backend.
CORS-enabled, mounts routes and WebSocket handler.
Background sim loop runs at 4Hz regardless of WebSocket connections.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.fleet.fleet_commander import FleetCommander
from src.logging.mission_logger import MissionLogger
from src.api.routes import create_router
from src.api.ws import create_ws_router
from src.api.monitor_ws import create_monitor_router

if TYPE_CHECKING:
    pass

SIM_DT = 0.25  # 4Hz simulation tick


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


async def _sim_loop(app: FastAPI):
    """Advance simulation at 4Hz, running time_scale sub-steps per tick."""
    import time as _time
    app.state.tick_count = 0
    app.state.last_step_time_us = 0
    while True:
        t0 = _time.perf_counter()
        for _ in range(app.state.time_scale):
            app.state.commander.step(SIM_DT)
        app.state.last_step_time_us = int((_time.perf_counter() - t0) * 1_000_000)
        app.state.tick_count += 1
        await asyncio.sleep(SIM_DT)


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

    # Store commander and logger on app state for routes/ws to access
    app.state.commander = commander
    app.state.logger = logger

    app.include_router(create_router(), prefix="/api")
    app.include_router(create_ws_router())
    app.include_router(create_monitor_router())

    return app


app = create_app()
