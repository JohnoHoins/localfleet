"""
FastAPI application — LocalFleet backend.
CORS-enabled, mounts routes and WebSocket handler.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.fleet.fleet_commander import FleetCommander
from src.api.routes import create_router
from src.api.ws import create_ws_router


def create_app(commander: FleetCommander | None = None) -> FastAPI:
    """Factory: build and return the FastAPI app."""
    commander = commander or FleetCommander()

    app = FastAPI(title="LocalFleet", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store commander on app state for routes/ws to access
    app.state.commander = commander

    app.include_router(create_router(), prefix="/api")
    app.include_router(create_ws_router())

    return app


app = create_app()
