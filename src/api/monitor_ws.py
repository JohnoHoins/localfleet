"""
Monitor WebSocket — streams system telemetry at 2Hz for the System Monitor dashboard.
Broadcasts: command parser state, threat engine, simulation stats,
comms/GPS mode, decision log, and performance counters.
"""
import asyncio
import time
from collections import Counter

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.fleet.fleet_manager import SIM_DT
from src.llm import ollama_client


MONITOR_INTERVAL = 0.5  # 2Hz
OLLAMA_CHECK_INTERVAL = 10.0  # seconds between Ollama model status checks


async def _ollama_status(app) -> str:
    """Cached status of the configured model ('loaded', 'cold', 'missing'
    or 'offline'), refreshed at most every 10s."""
    now = time.time()
    checked = getattr(app.state, "ollama_checked_at", 0.0)
    if now - checked >= OLLAMA_CHECK_INTERVAL:
        app.state.ollama_checked_at = now
        app.state.ollama_status = await asyncio.to_thread(ollama_client.model_status)
    return getattr(app.state, "ollama_status", "offline")


def create_monitor_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/monitor/ws")
    async def monitor_ws(websocket: WebSocket):
        await websocket.accept()
        commander = websocket.app.state.commander

        try:
            while True:
                # Re-read every tick: /api/reset swaps in a new FleetManager
                fm = commander.fleet_manager

                # --- Simulation stats ---
                # Count every asset (drone too) by its actual status
                statuses = Counter(v["status"].value for v in fm.vessels.values())
                statuses[fm.drone.status.value] += 1

                time_scale = getattr(websocket.app.state, "time_scale", 1)
                # Wall time of one 4Hz tick, i.e. all time_scale sub-steps
                step_time_us = getattr(websocket.app.state, "last_step_time_us", 0)

                sim_data = {
                    "tick_count": getattr(websocket.app.state, "tick_count", 0),
                    "time_scale": time_scale,
                    "dt": 0.25,
                    "assets_executing": statuses["executing"],
                    "assets_returning": statuses["returning"],
                    "assets_idle": statuses["idle"],
                }

                # --- Command parser state ---
                pi = commander.last_parse_info
                command_data = {
                    "last_text": pi["text"] if pi else None,
                    "parse_method": pi["method"] if pi else None,
                    "parse_time_ms": pi["time_ms"] if pi else None,
                    "mission_type": pi["mission"] if pi else None,
                    "formation": pi["formation"] if pi else None,
                    "error": pi.get("error") if pi else None,
                }

                # --- Threats ---
                critical = sum(1 for ta in fm.threat_assessments if ta.threat_level == "critical")
                warning = sum(1 for ta in fm.threat_assessments if ta.threat_level == "warning")
                auto_engage_countdown = None
                if fm.comms_mode == "denied" and fm.comms_denied_since:
                    remaining_steps = fm.escalation_steps - fm._comms_denied_steps
                    remaining_secs = remaining_steps * SIM_DT
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
                    "auto_engage_delay": fm.escalation_steps * SIM_DT,
                }

                # --- Comms ---
                # Sim-time, consistent with the escalation countdown
                denied_dur = 0.0
                if fm.comms_mode == "denied" and fm.comms_denied_since:
                    denied_dur = fm._comms_denied_steps * SIM_DT
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
                if fm.gps_mode.value != "denied" and not fm._gps_blending:
                    gps_data["dr_drift_meters"] = 0.0

                # --- Decisions (last 20) ---
                decisions = fm.decision_log.to_dicts(n=20)

                # --- Performance ---
                ws_clients = getattr(websocket.app.state, "ws_client_count", 0)
                ollama_status = await _ollama_status(websocket.app)
                perf_data = {
                    "ws_clients": ws_clients,
                    "step_time_us": step_time_us,
                    "substep_time_us": step_time_us // max(1, time_scale),
                    "ollama_loaded": ollama_status == "loaded",
                    "ollama_status": ollama_status,
                    "ollama_model": ollama_client.MODEL,
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
