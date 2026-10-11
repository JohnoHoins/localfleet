"""
WebSocket handler — streams FleetState JSON at 4Hz.
Each connected client gets state updates every 250ms.
Simulation is advanced, and state snapshots logged, by the background
loop in server.py; this handler only reads and broadcasts state.
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


DT = 0.25  # Broadcast interval (250ms = 4Hz)


def create_ws_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        commander = websocket.app.state.commander
        app_state = websocket.app.state
        app_state.ws_client_count = getattr(app_state, "ws_client_count", 0) + 1

        try:
            while True:
                state_dict = commander.get_state_dict()
                await websocket.send_json(state_dict)
                await asyncio.sleep(DT)
        except WebSocketDisconnect:
            pass
        finally:
            app_state.ws_client_count -= 1

    return router
