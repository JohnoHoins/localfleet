#!/usr/bin/env python3
"""
LocalFleet Full-Spectrum Simulation Orchestrator

Drives a timed tactical narrative via REST API calls while capturing
all WebSocket state frames, decisions, and mission logs to data files.

Usage:
    # Start backend + dashboard first, then:
    .venv/bin/python scripts/run_simulation.py

Requires: requests, websocket-client
"""

import json
import math
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
import websocket

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Phase durations in seconds — tune these to adjust total runtime
PHASE_TIMING = {
    0:  30,   # Baseline
    1:  90,   # PATROL
    2:  60,   # Contact appears — threat escalation
    3:  120,  # INTERCEPT — full kill chain
    4:  90,   # SEARCH — post-contact sweep
    5:  90,   # COMMS DENIED — autonomous ops
    6:  60,   # GPS DENIED during autonomous intercept
    7:  30,   # COMMS + GPS restored
    8:  60,   # ESCORT mission
    9:  60,   # LOITER mission
    10: 60,   # AERIAL_RECON
    11: 30,   # GPS DEGRADED test
    12: 60,   # Return to base
    13: 30,   # Final data dump
}

# Asset home positions (for RTB verification)
HOME_POSITIONS = {
    "alpha": (0, 0),
    "bravo": (200, 0),
    "charlie": (400, 0),
    "eagle-1": (200, -100),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compass_to_math_rad(compass_deg: float) -> float:
    """Convert compass degrees (0=N, CW+) to math radians (0=E, CCW+)."""
    return math.radians(90 - compass_deg)


def api(method: str, path: str, json_body=None, params=None):
    """Make an API call, return parsed JSON or None on error."""
    url = f"{BASE_URL}{path}"
    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=5)
        elif method == "POST":
            r = requests.post(url, json=json_body, timeout=5)
        elif method == "DELETE":
            r = requests.delete(url, timeout=5)
        else:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [API ERROR] {method} {path}: {e}")
        return None


def elapsed_str(start_time: float) -> str:
    """Return mm:ss since start_time."""
    e = time.time() - start_time
    return f"{int(e)//60}:{int(e)%60:02d}"


def phase_header(num: int, name: str, start_time: float):
    """Print a visible phase header."""
    ts = elapsed_str(start_time)
    banner = f"=== PHASE {num}: {name} ({ts}) ==="
    print(f"\n{'='*len(banner)}")
    print(banner)
    print(f"{'='*len(banner)}\n")


def event(msg: str, start_time: float):
    """Print a timestamped event."""
    print(f"  [{elapsed_str(start_time)}] {msg}")


def snapshot_phase(phase_num: int, phase_name: str, out_file):
    """Capture and write phase-transition snapshot data."""
    decisions = api("GET", "/api/decisions", params={"limit": 200})
    assets = api("GET", "/api/assets")
    contacts = api("GET", "/api/contacts")
    mission = api("GET", "/api/mission")
    snapshot = {
        "phase": phase_num,
        "phase_name": phase_name,
        "timestamp": time.time(),
        "decisions": decisions,
        "assets": assets,
        "contacts": contacts,
        "mission": mission,
    }
    out_file.write(json.dumps(snapshot) + "\n")
    out_file.flush()


def make_fleet_command(mission_type, waypoints, formation="independent",
                       speed=5.0, spacing=200.0, comms_lost_behavior="return_to_base",
                       drone_pattern=None, drone_altitude=100.0, drone_speed=15.0):
    """Build a FleetCommand dict for all 4 assets.

    waypoints: list of {"x": float, "y": float} — applied to all surface assets
               (formation offsets handled server-side).
    """
    surface_assets = []
    for aid in ["alpha", "bravo", "charlie"]:
        surface_assets.append({
            "asset_id": aid,
            "domain": "surface",
            "waypoints": waypoints,
            "speed": speed,
        })

    drone_cmd = {
        "asset_id": "eagle-1",
        "domain": "air",
        "waypoints": waypoints,
        "speed": drone_speed,
        "altitude": drone_altitude,
    }
    if drone_pattern:
        drone_cmd["drone_pattern"] = drone_pattern

    return {
        "mission_type": mission_type,
        "assets": surface_assets + [drone_cmd],
        "formation": formation,
        "spacing_meters": spacing,
        "colregs_compliance": True,
        "comms_lost_behavior": comms_lost_behavior,
    }


# ---------------------------------------------------------------------------
# WebSocket Capture Thread
# ---------------------------------------------------------------------------

class WSCapture:
    """Connects to WebSocket, captures all frames to JSONL file."""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.frame_count = 0
        self.latest_state = None
        self._stop = threading.Event()
        self._file = None
        self._ws = None
        self._thread = None

    def start(self):
        self._file = open(self.output_path, "w")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        def on_message(ws, message):
            self._file.write(message + "\n")
            self._file.flush()
            self.frame_count += 1
            try:
                self.latest_state = json.loads(message)
            except json.JSONDecodeError:
                pass

        def on_error(ws, error):
            print(f"  [WS ERROR] {error}")

        def on_close(ws, close_status, close_msg):
            pass

        def on_open(ws):
            pass

        self._ws = websocket.WebSocketApp(
            WS_URL,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        self._ws.run_forever()

    def stop(self):
        if self._ws:
            self._ws.close()
        if self._file:
            self._file.close()

    @property
    def state(self):
        return self.latest_state


# ---------------------------------------------------------------------------
# Phase Implementations
# ---------------------------------------------------------------------------

def wait_phase(duration: float, ws: WSCapture, start_time: float,
               monitor_fn=None, poll_interval=1.0):
    """Wait for duration seconds, optionally calling monitor_fn each poll."""
    end = time.time() + duration
    while time.time() < end:
        if monitor_fn and ws.state:
            monitor_fn(ws.state, start_time)
        time.sleep(poll_interval)


def phase_0(ws, start_time, snapshots_file):
    """Baseline — verify all assets at home, IDLE."""
    phase_header(0, "BASELINE", start_time)

    state = api("GET", "/api/assets")
    if state and "assets" in state:
        for a in state["assets"]:
            event(f"{a['asset_id']}: ({a['x']:.0f}, {a['y']:.0f}) status={a['status']}", start_time)
    else:
        event("Could not read fleet state — is the backend running?", start_time)

    summary = api("GET", "/api/logs/summary")
    if summary:
        event(f"Starting log summary: {summary}", start_time)

    snapshot_phase(0, "BASELINE", snapshots_file)
    wait_phase(PHASE_TIMING[0], ws, start_time)


def phase_1(ws, start_time, snapshots_file):
    """PATROL mission — echelon formation."""
    phase_header(1, "PATROL — ECHELON FORMATION", start_time)

    wps = [{"x": 1500, "y": 1500}, {"x": 1500, "y": 0}, {"x": 0, "y": 0}]
    cmd = make_fleet_command("patrol", wps, formation="echelon", speed=5.0,
                             drone_pattern="orbit", drone_altitude=100.0)
    result = api("POST", "/api/command-direct", cmd)
    event(f"PATROL dispatched: {result.get('success') if result else 'FAILED'}", start_time)

    def monitor(state, st):
        assets = state.get("assets", [])
        for a in assets:
            if a["asset_id"] == "alpha":
                pass  # silent monitoring — data captured via WS
        # Report drone pattern
        for a in assets:
            if a["asset_id"] == "eagle-1" and a.get("drone_pattern"):
                pass  # captured

    snapshot_phase(1, "PATROL", snapshots_file)
    wait_phase(PHASE_TIMING[1], ws, start_time, monitor)


def phase_2(ws, start_time, snapshots_file):
    """Contact appears — threat escalation."""
    phase_header(2, "CONTACT APPEARS — THREAT ESCALATION", start_time)

    # Spawn bogey-1 at ~6500m from origin, heading southwest toward fleet
    # Heading SW in compass = ~225°, convert to math radians
    heading_rad = compass_to_math_rad(225)
    contact = api("POST", "/api/contacts", {
        "contact_id": "bogey-1",
        "x": 4000,
        "y": 2000,
        "heading": heading_rad,
        "speed": 3.0,
        "domain": "surface",
    })
    event(f"Spawned bogey-1 at (4000, 2000) heading SW @ 3 m/s: {contact}", start_time)

    prev_threat = None
    prev_kc = None

    def monitor(state, st):
        nonlocal prev_threat, prev_kc
        threats = state.get("threat_assessments", [])
        for t in threats:
            if t.get("contact_id") == "bogey-1":
                level = t.get("threat_level", "none")
                dist = t.get("distance", 0)
                if level != prev_threat:
                    event(f"bogey-1 threat: {prev_threat or 'none'} → {level} "
                          f"(dist={dist:.0f}m, closing={t.get('closing_rate', 0):.1f} m/s)", st)
                    prev_threat = level

        autonomy = state.get("autonomy", {})
        kc = autonomy.get("kill_chain_phase")
        if kc and kc != prev_kc:
            event(f"Kill chain: {prev_kc or 'none'} → {kc}", st)
            prev_kc = kc

        # Check if drone retasked
        for a in state.get("assets", []):
            if a["asset_id"] == "eagle-1" and a.get("drone_pattern") == "track":
                pass  # Will be captured in data

    snapshot_phase(2, "CONTACT_ESCALATION", snapshots_file)
    wait_phase(PHASE_TIMING[2], ws, start_time, monitor)


def phase_3(ws, start_time, snapshots_file):
    """INTERCEPT mission — full kill chain."""
    phase_header(3, "INTERCEPT — FULL KILL CHAIN", start_time)

    wps = [{"x": 4000, "y": 2000}]  # Toward bogey-1's spawn point
    cmd = make_fleet_command("intercept", wps, formation="echelon", speed=8.0,
                             drone_pattern="track", drone_altitude=100.0)
    result = api("POST", "/api/command-direct", cmd)
    event(f"INTERCEPT dispatched @ 8 m/s: {result.get('success') if result else 'FAILED'}", start_time)

    prev_kc = None
    removed = False

    def monitor(state, st):
        nonlocal prev_kc, removed
        autonomy = state.get("autonomy", {})
        kc = autonomy.get("kill_chain_phase")
        if kc and kc != prev_kc:
            event(f"Kill chain: {prev_kc or 'none'} → {kc}", st)
            prev_kc = kc

        targeting = autonomy.get("targeting", {})
        if targeting and targeting.get("locked"):
            event(f"TARGET LOCKED — range={targeting.get('range_m', 0):.0f}m "
                  f"confidence={targeting.get('confidence', 0):.2f}", st)

        # Check closest vessel to bogey-1
        contacts = state.get("contacts", [])
        bogey = next((c for c in contacts if c.get("contact_id") == "bogey-1"), None)
        if bogey and not removed:
            bx, by = bogey["x"], bogey["y"]
            for a in state.get("assets", []):
                if a["domain"] == "surface":
                    dist = math.sqrt((a["x"] - bx)**2 + (a["y"] - by)**2)
                    if dist < 300:
                        event(f"CONVERGE: {a['asset_id']} within {dist:.0f}m of bogey-1 — neutralizing", st)
                        api("DELETE", f"/api/contacts/bogey-1")
                        event("bogey-1 removed (neutralized)", st)
                        removed = True
                        break

    snapshot_phase(3, "INTERCEPT", snapshots_file)
    wait_phase(PHASE_TIMING[3], ws, start_time, monitor)


def phase_4(ws, start_time, snapshots_file):
    """SEARCH mission — post-contact area sweep."""
    phase_header(4, "SEARCH — POST-CONTACT AREA SWEEP", start_time)

    # Search where bogey-1 was roughly neutralized
    wps = [{"x": 3000, "y": 1500}]
    cmd = make_fleet_command("search", wps, formation="line", speed=5.0,
                             drone_pattern="sweep", drone_altitude=100.0)
    result = api("POST", "/api/command-direct", cmd)
    event(f"SEARCH dispatched (LINE_ABREAST): {result.get('success') if result else 'FAILED'}", start_time)

    snapshot_phase(4, "SEARCH", snapshots_file)
    wait_phase(PHASE_TIMING[4], ws, start_time)


def phase_5(ws, start_time, snapshots_file):
    """COMMS DENIED — autonomous operations."""
    phase_header(5, "COMMS DENIED — AUTONOMOUS OPERATIONS", start_time)

    # First set comms_lost_behavior to continue_mission via a new command
    # We do this by dispatching the current search mission with the behavior set
    wps = [{"x": 3000, "y": 1500}]
    cmd = make_fleet_command("search", wps, formation="line", speed=5.0,
                             comms_lost_behavior="continue_mission",
                             drone_pattern="sweep")
    api("POST", "/api/command-direct", cmd)
    event("Set comms_lost_behavior=continue_mission", start_time)
    time.sleep(1)

    # Spawn bogey-2 FIRST (so threat detector sees it before comms denied)
    heading_rad = compass_to_math_rad(0)  # heading North
    contact = api("POST", "/api/contacts", {
        "contact_id": "bogey-2",
        "x": 3000,
        "y": -1000,
        "heading": heading_rad,
        "speed": 4.0,
        "domain": "surface",
    })
    event(f"Spawned bogey-2 at (3000, -1000) heading N @ 4 m/s", start_time)
    time.sleep(2)  # Let threat detector pick it up

    # Now deny comms
    result = api("POST", "/api/comms-mode", {"mode": "denied"})
    event(f"COMMS DENIED: {result}", start_time)

    prev_threat = None
    prev_actions = 0
    auto_engaged = False

    def monitor(state, st):
        nonlocal prev_threat, prev_actions, auto_engaged
        autonomy = state.get("autonomy", {})
        denied_dur = autonomy.get("comms_denied_duration", 0)
        actions = autonomy.get("autonomous_actions", [])

        if len(actions) > prev_actions:
            for a in actions[prev_actions:]:
                event(f"AUTONOMOUS ACTION: {a}", st)
            prev_actions = len(actions)

        threats = state.get("threat_assessments", [])
        for t in threats:
            if t.get("contact_id") == "bogey-2":
                level = t.get("threat_level", "none")
                if level != prev_threat:
                    event(f"bogey-2 threat: {prev_threat or 'none'} → {level} "
                          f"(comms denied for {denied_dur:.0f}s)", st)
                    prev_threat = level

        kc = autonomy.get("kill_chain_phase")
        if kc and not auto_engaged:
            event(f"Kill chain (autonomous): {kc}, denied_duration={denied_dur:.0f}s", st)
            if kc in ("ENGAGE", "CONVERGE"):
                auto_engaged = True
                event("AUTO-ENGAGE TRIGGERED — fleet acting without operator!", st)

    snapshot_phase(5, "COMMS_DENIED", snapshots_file)
    wait_phase(PHASE_TIMING[5], ws, start_time, monitor)


def phase_6(ws, start_time, snapshots_file):
    """GPS DENIED during autonomous intercept."""
    phase_header(6, "GPS DENIED — DEAD RECKONING", start_time)

    result = api("POST", "/api/gps-mode", {"mode": "denied"})
    event(f"GPS DENIED: {result}", start_time)

    def monitor(state, st):
        for a in state.get("assets", []):
            if a["asset_id"] == "alpha":
                acc = a.get("position_accuracy", 1.0)
                if acc > 2.0:  # Only report meaningful drift
                    event(f"DR drift: alpha accuracy={acc:.1f}m, "
                          f"pos=({a['x']:.0f},{a['y']:.0f})", st)
                    break

    snapshot_phase(6, "GPS_DENIED", snapshots_file)
    wait_phase(PHASE_TIMING[6], ws, start_time, monitor, poll_interval=5.0)


def phase_7(ws, start_time, snapshots_file):
    """COMMS + GPS restored — damage assessment."""
    phase_header(7, "COMMS + GPS RESTORED", start_time)

    # Snapshot before restoration to capture drift
    pre_state = api("GET", "/api/assets")
    if pre_state:
        for a in pre_state.get("assets", []):
            event(f"Pre-restore {a['asset_id']}: pos=({a['x']:.1f},{a['y']:.1f}) "
                  f"accuracy={a.get('position_accuracy', 0):.1f}m", start_time)

    result1 = api("POST", "/api/comms-mode", {"mode": "full"})
    event(f"COMMS RESTORED: {result1}", start_time)

    result2 = api("POST", "/api/gps-mode", {"mode": "full"})
    event(f"GPS RESTORED: {result2}", start_time)

    # Remove bogey-2
    api("DELETE", "/api/contacts/bogey-2")
    event("bogey-2 removed", start_time)

    snapshot_phase(7, "RESTORED", snapshots_file)
    wait_phase(PHASE_TIMING[7], ws, start_time)


def phase_8(ws, start_time, snapshots_file):
    """ESCORT mission — following a contact."""
    phase_header(8, "ESCORT — CONTACT FOLLOWING", start_time)

    # Spawn friendly escort target
    heading_rad = compass_to_math_rad(90)  # heading East
    api("POST", "/api/contacts", {
        "contact_id": "escort-target",
        "x": 1000,
        "y": 500,
        "heading": heading_rad,
        "speed": 2.0,
        "domain": "surface",
    })
    event("Spawned escort-target at (1000, 500) heading E @ 2 m/s", start_time)
    time.sleep(1)

    wps = [{"x": 1000, "y": 500}]
    cmd = make_fleet_command("escort", wps, formation="column", speed=4.0,
                             drone_pattern="orbit", drone_altitude=150.0)
    result = api("POST", "/api/command-direct", cmd)
    event(f"ESCORT dispatched (COLUMN): {result.get('success') if result else 'FAILED'}", start_time)

    snapshot_phase(8, "ESCORT", snapshots_file)
    wait_phase(PHASE_TIMING[8], ws, start_time)


def phase_9(ws, start_time, snapshots_file):
    """LOITER mission — holding pattern."""
    phase_header(9, "LOITER — HOLDING PATTERN", start_time)

    api("DELETE", "/api/contacts/escort-target")
    event("Removed escort-target", start_time)

    # Loiter point relatively close so vessels arrive quickly
    wps = [{"x": 2000, "y": 1000}]
    cmd = make_fleet_command("loiter", wps, formation="spread", speed=5.0,
                             drone_pattern="orbit", drone_altitude=100.0)
    result = api("POST", "/api/command-direct", cmd)
    event(f"LOITER dispatched (SPREAD): {result.get('success') if result else 'FAILED'}", start_time)

    snapshot_phase(9, "LOITER", snapshots_file)
    wait_phase(PHASE_TIMING[9], ws, start_time)


def phase_10(ws, start_time, snapshots_file):
    """AERIAL_RECON — drone-primary mission."""
    phase_header(10, "AERIAL_RECON — DRONE PRIMARY", start_time)

    wps = [{"x": 1500, "y": 1500}]
    cmd = make_fleet_command("aerial_recon", wps, formation="independent", speed=5.0,
                             drone_pattern="sweep", drone_altitude=150.0)
    result = api("POST", "/api/command-direct", cmd)
    event(f"AERIAL_RECON dispatched: {result.get('success') if result else 'FAILED'}", start_time)

    snapshot_phase(10, "AERIAL_RECON", snapshots_file)
    wait_phase(PHASE_TIMING[10], ws, start_time)


def phase_11(ws, start_time, snapshots_file):
    """GPS DEGRADED test."""
    phase_header(11, "GPS DEGRADED — NOISE TEST", start_time)

    result = api("POST", "/api/gps-mode", {"mode": "degraded", "noise_meters": 50})
    event(f"GPS DEGRADED (50m noise): {result}", start_time)

    def monitor(state, st):
        for a in state.get("assets", []):
            if a["asset_id"] == "alpha":
                event(f"alpha accuracy={a.get('position_accuracy', 0):.1f}m", st)
                break

    snapshot_phase(11, "GPS_DEGRADED", snapshots_file)
    wait_phase(PHASE_TIMING[11], ws, start_time, monitor, poll_interval=10.0)


def phase_12(ws, start_time, snapshots_file):
    """Return to base."""
    phase_header(12, "RETURN TO BASE", start_time)

    # Restore GPS first
    api("POST", "/api/gps-mode", {"mode": "full"})
    event("GPS restored to FULL", start_time)

    result = api("POST", "/api/return-to-base")
    event(f"RTB issued: {result}", start_time)

    def monitor(state, st):
        idle_count = sum(1 for a in state.get("assets", []) if a.get("status") == "idle")
        if idle_count == 4:
            event("All 4 assets IDLE — RTB complete!", st)

    snapshot_phase(12, "RTB", snapshots_file)
    wait_phase(PHASE_TIMING[12], ws, start_time, monitor, poll_interval=5.0)


def phase_13(ws, start_time, snapshots_file, decisions_file, mission_log_file):
    """Final data dump."""
    phase_header(13, "FINAL DATA DUMP", start_time)

    # Full decision log
    decisions = api("GET", "/api/decisions", params={"limit": 500})
    if decisions:
        decisions_file.write(json.dumps(decisions) + "\n")
        decisions_file.flush()
        event(f"Captured {len(decisions.get('decisions', []))} decisions", start_time)

    # Full mission log
    logs = api("GET", "/api/logs", params={"limit": 2000})
    if logs:
        mission_log_file.write(json.dumps(logs) + "\n")
        mission_log_file.flush()
        event(f"Captured {logs.get('count', 0)} mission log entries", start_time)

    # Summary
    summary = api("GET", "/api/logs/summary")
    event(f"Final summary: {summary}", start_time)

    # Final fleet state
    final_state = api("GET", "/api/assets")
    if final_state:
        for a in final_state.get("assets", []):
            home = HOME_POSITIONS.get(a["asset_id"], (0, 0))
            dist = math.sqrt((a["x"] - home[0])**2 + (a["y"] - home[1])**2)
            event(f"{a['asset_id']}: ({a['x']:.0f},{a['y']:.0f}) "
                  f"status={a['status']} dist_from_home={dist:.0f}m", start_time)

    # Final contacts (should be empty)
    contacts = api("GET", "/api/contacts")
    event(f"Final contacts: {contacts}", start_time)

    snapshot_phase(13, "FINAL", snapshots_file)
    wait_phase(PHASE_TIMING[13], ws, start_time)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Create data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Timestamp for this run
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    capture_path = DATA_DIR / "sim_capture.jsonl"
    decisions_path = DATA_DIR / "sim_decisions.jsonl"
    mission_log_path = DATA_DIR / "sim_mission_log.jsonl"
    snapshots_path = DATA_DIR / "sim_snapshots.jsonl"

    total_time = sum(PHASE_TIMING.values())
    print(f"\n{'='*60}")
    print(f"  LocalFleet Full-Spectrum Simulation")
    print(f"  Run: {run_ts}")
    print(f"  Estimated duration: {total_time//60}m {total_time%60}s")
    print(f"  Data output: {DATA_DIR}")
    print(f"{'='*60}\n")

    # Verify backend is running
    try:
        r = requests.get(f"{BASE_URL}/api/assets", timeout=3)
        r.raise_for_status()
        print("Backend is running. Starting simulation...\n")
    except Exception as e:
        print(f"ERROR: Cannot reach backend at {BASE_URL}")
        print(f"  Start it first: .venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000")
        sys.exit(1)

    # Start WebSocket capture
    ws = WSCapture(capture_path)
    ws.start()
    time.sleep(1)  # Let WS connect

    if ws.frame_count == 0:
        time.sleep(2)  # Extra wait
    if ws.frame_count == 0:
        print("WARNING: No WebSocket frames received yet. Continuing anyway...")

    start_time = time.time()

    # Open persistent output files
    with open(decisions_path, "w") as dec_f, \
         open(mission_log_path, "w") as log_f, \
         open(snapshots_path, "w") as snap_f:

        try:
            phase_0(ws, start_time, snap_f)
            phase_1(ws, start_time, snap_f)
            phase_2(ws, start_time, snap_f)
            phase_3(ws, start_time, snap_f)
            phase_4(ws, start_time, snap_f)
            phase_5(ws, start_time, snap_f)
            phase_6(ws, start_time, snap_f)
            phase_7(ws, start_time, snap_f)
            phase_8(ws, start_time, snap_f)
            phase_9(ws, start_time, snap_f)
            phase_10(ws, start_time, snap_f)
            phase_11(ws, start_time, snap_f)
            phase_12(ws, start_time, snap_f)

            # Phase 13 needs decision/log files
            phase_13(ws, start_time, snap_f, dec_f, log_f)

        except KeyboardInterrupt:
            print("\n\nSimulation interrupted by operator.")
        finally:
            ws.stop()

    # Final report
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  SIMULATION COMPLETE")
    print(f"  Duration: {int(elapsed)//60}m {int(elapsed)%60}s")
    print(f"  WebSocket frames captured: {ws.frame_count}")
    print(f"  Files written:")
    print(f"    {capture_path}")
    print(f"    {decisions_path}")
    print(f"    {mission_log_path}")
    print(f"    {snapshots_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
