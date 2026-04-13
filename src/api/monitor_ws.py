"""
Monitor WebSocket — streams system telemetry at 2Hz for the System Monitor dashboard.
Broadcasts: command parser state, threat engine, simulation stats,
comms/GPS mode, decision log, and performance counters.
"""
import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


MONITOR_INTERVAL = 0.5  # 2Hz


def create_monitor_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/monitor/ws")
    async def monitor_ws(websocket: WebSocket):
        await websocket.accept()
        commander = websocket.app.state.commander
        fm = commander.fleet_manager

        try:
            while True:
                # --- Simulation stats ---
                executing = sum(
                    1 for v in fm.vessels.values()
                    if v["status"].value == "executing"
                )
                idle = sum(
                    1 for v in fm.vessels.values()
                    if v["status"].value == "idle"
                )
                # Count drone too
                if fm.drone.status.value == "executing":
                    executing += 1
                else:
                    idle += 1

                time_scale = getattr(websocket.app.state, "time_scale", 1)
                step_time_us = getattr(websocket.app.state, "last_step_time_us", 0)

                sim_data = {
                    "tick_count": getattr(websocket.app.state, "tick_count", 0),
                    "time_scale": time_scale,
                    "dt": 0.25,
                    "assets_executing": executing,
                    "assets_idle": idle,
                }

                # --- Command parser state ---
                pi = commander.last_parse_info
                command_data = {
                    "last_text": pi["text"] if pi else None,
                    "parse_method": pi["method"] if pi else None,
                    "parse_time_ms": pi["time_ms"] if pi else None,
                    "mission_type": pi["mission"] if pi else None,
                    "formation": pi["formation"] if pi else None,
                }

                # --- Threats ---
                critical = sum(1 for ta in fm.threat_assessments if ta.threat_level == "critical")
                warning = sum(1 for ta in fm.threat_assessments if ta.threat_level == "warning")
                auto_engage_countdown = None
                if fm.comms_mode == "denied" and fm.comms_denied_since:
                    from src.fleet.fleet_manager import ESCALATION_STEPS
                    remaining_steps = ESCALATION_STEPS - fm._comms_denied_steps
                    remaining_secs = remaining_steps * 0.25  # dt = 0.25s
                    if remaining_secs > 0 and critical > 0:
                        auto_engage_countdown = round(remaining_secs, 1)

                threats_data = {
                    "contact_count": len(fm.contacts),
                    "critical": critical,
                    "warning": warning,
                    "intercept_recommended": fm.intercept_recommended,
                    "kill_chain_phase": fm.kill_chain_phase,
                    "kill_chain_target": fm.kill_chain_target,
                    "auto_engage_countdown": auto_engage_countdown,
                }

                # --- Comms ---
                denied_dur = 0.0
                if fm.comms_mode == "denied" and fm.comms_denied_since:
                    denied_dur = time.time() - fm.comms_denied_since
                comms_data = {
                    "mode": fm.comms_mode,
                    "denied_duration": round(denied_dur, 1),
                    "standing_orders": fm.comms_lost_behavior,
                    "autonomous_actions": fm.autonomous_actions[-5:],
                    "fallback_executed": fm._comms_fallback_executed,
                }

                # --- GPS ---
                max_drift = 0.0
                for vid, dr in fm.dr_states.items():
                    if vid in fm.vessels:
                        true_x = fm.vessels[vid]["state"][0]
                        true_y = fm.vessels[vid]["state"][1]
                        drift = ((dr.estimated_x - true_x) ** 2 +
                                 (dr.estimated_y - true_y) ** 2) ** 0.5
                        max_drift = max(max_drift, drift)
                gps_data = {
                    "mode": fm.gps_mode.value if hasattr(fm.gps_mode, "value") else str(fm.gps_mode),
                    "dr_drift_meters": round(max_drift, 1),
                    "blending": fm._gps_blending,
                }

                # --- Decisions (last 20) ---
                decisions = fm.decision_log.to_dicts(n=20)

                # --- Performance ---
                from src.api.ws import create_ws_router  # just for client count
                ws_clients = getattr(websocket.app.state, "ws_client_count", 1)
                perf_data = {
                    "ws_clients": ws_clients,
                    "step_time_us": step_time_us,
                    "ollama_loaded": True,
                    "ollama_model": "qwen2.5:72b",
                }

                payload = {
                    "timestamp": time.time(),
                    "sim": sim_data,
                    "command": command_data,
                    "threats": threats_data,
                    "comms": comms_data,
                    "gps": gps_data,
                    "decisions": decisions,
                    "performance": perf_data,
                }

                await websocket.send_json(payload)
                await asyncio.sleep(MONITOR_INTERVAL)

        except WebSocketDisconnect:
            pass

    return router
