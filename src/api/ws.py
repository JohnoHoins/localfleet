"""
WebSocket handler — streams FleetState JSON at 4Hz.
Each connected client gets state updates every 250ms.
The simulation advances one tick per broadcast.
State snapshots are logged every LOG_INTERVAL ticks (~5 seconds).
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


DT = 0.25  # Simulation timestep (250ms = 4Hz)
LOG_INTERVAL = 20  # Log state every 20 ticks (5 seconds)


def create_ws_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        commander = websocket.app.state.commander
        logger = getattr(websocket.app.state, "logger", None)
        tick_count = 0

        try:
            while True:
                commander.step(DT)
                state_dict = commander.get_state_dict()
                await websocket.send_json(state_dict)

                tick_count += 1
                if logger and tick_count % LOG_INTERVAL == 0:
                    state = commander.get_state()
                    logger.log_state(state)

                await asyncio.sleep(DT)
        except WebSocketDisconnect:
            pass

    return router
