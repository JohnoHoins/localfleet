"""
WebSocket handler — streams FleetState JSON at 4Hz.
Each connected client gets state updates every 250ms.
The simulation advances one tick per broadcast.
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


DT = 0.25  # Simulation timestep (250ms = 4Hz)


def create_ws_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        commander = websocket.app.state.commander

        try:
            while True:
                commander.step(DT)
                state = commander.get_state()
                await websocket.send_json(state.model_dump())
                await asyncio.sleep(DT)
        except WebSocketDisconnect:
            pass

    return router
