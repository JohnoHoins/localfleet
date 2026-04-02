#!/usr/bin/env python3
"""
LocalFleet V2 Deep-Diagnostic Simulation Orchestrator

Runs 21 isolated tests with clean resets between each. Captures all WebSocket
frames, decisions, and snapshots to data/ for offline analysis.

Usage:
    # Start backend first:
    .venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000
    # Then run:
    .venv/bin/python scripts/run_simulation_v2.py
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

HOME_POSITIONS = {
    "alpha": (0, 0),
    "bravo": (200, 0),
    "charlie": (400, 0),
    "eagle-1": (200, -100),
}

RESET_TIMEOUT = 120  # max seconds to wait for assets to reach home
RESET_IDLE_THRESHOLD = 50  # meters from home to consider "at home"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compass_to_math_rad(compass_deg: float) -> float:
    return math.radians(90 - compass_deg)


def api(method: str, path: str, json_body=None, params=None):
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
    e = time.time() - start_time
    return f"{int(e)//60}:{int(e)%60:02d}"


def make_fleet_command(mission_type, waypoints, formation="independent",
                       speed=5.0, spacing=200.0, comms_lost_behavior="return_to_base",
                       drone_pattern=None, drone_altitude=100.0, drone_speed=15.0):
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
    """Connects to WebSocket, captures all frames with test_id and wall_clock."""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.frame_count = 0
        self.latest_state = None
        self.current_test_id = "INIT"
        self._file = None
        self._ws = None
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        self._file = open(self.output_path, "w")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        def on_message(ws, message):
            wall_clock = time.time()
            with self._lock:
                test_id = self.current_test_id
            wrapped = json.dumps({
                "test": test_id,
                "wall_clock": wall_clock,
                "frame": json.loads(message),
            })
            self._file.write(wrapped + "\n")
            self._file.flush()
            self.frame_count += 1
            try:
                self.latest_state = json.loads(message)
            except json.JSONDecodeError:
                pass

        def on_error(ws, error):
            print(f"  [WS ERROR] {error}")

        self._ws = websocket.WebSocketApp(
            WS_URL,
            on_message=on_message,
            on_error=on_error,
            on_close=lambda ws, s, m: None,
            on_open=lambda ws: None,
        )
        self._ws.run_forever()

    def set_test(self, test_id: str):
        with self._lock:
            self.current_test_id = test_id

    def stop(self):
        if self._ws:
            self._ws.close()
        if self._file:
            self._file.close()

    @property
    def state(self):
        return self.latest_state


# ---------------------------------------------------------------------------
# Decision Poller Thread
# ---------------------------------------------------------------------------

class DecisionPoller:
    """Polls /api/decisions every 5s, deduplicates, writes to JSONL."""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.seen_ids = set()
        self.current_test_id = "INIT"
        self._file = None
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        self._file = open(self.output_path, "w")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            self._poll()
            self._stop.wait(5.0)

    def _poll(self):
        result = api("GET", "/api/decisions", params={"limit": 50})
        if not result or "decisions" not in result:
            return
        with self._lock:
            test_id = self.current_test_id
        for d in result["decisions"]:
            did = d.get("id") or d.get("timestamp", "")
            if did not in self.seen_ids:
                self.seen_ids.add(did)
                entry = {"test": test_id, "wall_clock": time.time(), "decision": d}
                self._file.write(json.dumps(entry) + "\n")
                self._file.flush()

    def set_test(self, test_id: str):
        with self._lock:
            self.current_test_id = test_id

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._file:
            self._file.close()


# ---------------------------------------------------------------------------
# Snapshot Capture
# ---------------------------------------------------------------------------

def snapshot(test_id: str, label: str, snap_file):
    """Capture full state snapshot to snapshots file."""
    data = {
        "test": test_id,
        "label": label,
        "wall_clock": time.time(),
        "assets": api("GET", "/api/assets"),
        "contacts": api("GET", "/api/contacts"),
        "decisions": api("GET", "/api/decisions", params={"limit": 200}),
        "mission": api("GET", "/api/mission"),
    }
    snap_file.write(json.dumps(data) + "\n")
    snap_file.flush()


# ---------------------------------------------------------------------------
# Reset Cycle
# ---------------------------------------------------------------------------

def reset_cycle(ws: WSCapture, run_start: float, snap_file):
    """Full reset between tests: remove contacts, restore GPS/comms, RTB, wait idle."""
    print(f"  [{elapsed_str(run_start)}] RESET: cleaning up...")

    # 1. Remove all contacts
    contacts = api("GET", "/api/contacts")
    if contacts and isinstance(contacts, list):
        for c in contacts:
            cid = c.get("contact_id", "")
            if cid:
                api("DELETE", f"/api/contacts/{cid}")
    elif contacts and isinstance(contacts, dict) and "contacts" in contacts:
        for c in contacts["contacts"]:
            cid = c.get("contact_id", "")
            if cid:
                api("DELETE", f"/api/contacts/{cid}")

    # 2. Restore GPS
    api("POST", "/api/gps-mode", {"mode": "full"})

    # 3. Restore comms
    api("POST", "/api/comms-mode", {"mode": "full"})

    # 4. Issue RTB
    time.sleep(0.5)  # Let comms restore take effect
    api("POST", "/api/return-to-base")

    # 5. Wait for all assets to reach idle near home
    deadline = time.time() + RESET_TIMEOUT
    all_home = False
    while time.time() < deadline:
        state = ws.state
        if state:
            assets = state.get("assets", [])
            idle_home = 0
            for a in assets:
                aid = a.get("asset_id", "")
                status = a.get("status", "")
                home = HOME_POSITIONS.get(aid, (0, 0))
                dist = math.sqrt((a.get("x", 0) - home[0])**2 +
                                 (a.get("y", 0) - home[1])**2)
                if status == "idle" and dist < RESET_IDLE_THRESHOLD:
                    idle_home += 1
            if idle_home >= 4:
                all_home = True
                break
        time.sleep(1.0)

    if all_home:
        print(f"  [{elapsed_str(run_start)}] RESET: all assets home and idle")
    else:
        print(f"  [{elapsed_str(run_start)}] RESET: TIMEOUT — forcing proceed (some assets not home)")

    # 7. Snapshot baseline
    snapshot("RESET", "post_reset", snap_file)
    time.sleep(0.5)


# ---------------------------------------------------------------------------
# Wait helper with monitoring
# ---------------------------------------------------------------------------

def wait_with_monitor(duration: float, ws: WSCapture, run_start: float,
                      monitor_fn=None, poll_interval=1.0):
    """Wait for duration seconds, calling monitor_fn each poll."""
    end = time.time() + duration
    while time.time() < end:
        if monitor_fn and ws.state:
            monitor_fn(ws.state, run_start)
        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Test Implementations
# ---------------------------------------------------------------------------

def test_00_baseline(ws, run_start, snap_file):
    test_id = "TEST-00-BASELINE"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    state = api("GET", "/api/assets")
    if state and "assets" in state:
        for a in state["assets"]:
            print(f"  {a['asset_id']}: ({a['x']:.0f}, {a['y']:.0f}) status={a['status']}")

    wait_with_monitor(10, ws, run_start)
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-00 complete")


def test_01_patrol(ws, run_start, snap_file):
    test_id = "TEST-01-PATROL"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 1500, "y": 1000}, {"x": 1500, "y": -500}, {"x": 0, "y": 0}]
    cmd = make_fleet_command("patrol", wps, formation="echelon", speed=7.0,
                             drone_pattern="orbit", drone_altitude=100.0)
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] PATROL dispatched: {result.get('success') if result else 'FAILED'}")

    prev_wp = {}
    def monitor(state, st):
        for a in state.get("assets", []):
            aid = a["asset_id"]
            wpi = a.get("current_waypoint_index", 0)
            if aid not in prev_wp:
                prev_wp[aid] = wpi
            if wpi != prev_wp[aid]:
                print(f"  [{elapsed_str(st)}] {aid}: waypoint {prev_wp[aid]} -> {wpi}")
                prev_wp[aid] = wpi

    wait_with_monitor(180, ws, run_start, monitor)
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-01 complete")
    reset_cycle(ws, run_start, snap_file)


def test_02_search(ws, run_start, snap_file):
    test_id = "TEST-02-SEARCH"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 2000, "y": 1000}]
    cmd = make_fleet_command("search", wps, formation="line", speed=5.0,
                             drone_pattern="sweep", drone_altitude=100.0)
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] SEARCH dispatched: {result.get('success') if result else 'FAILED'}")

    eagle_stuck_count = 0
    def monitor(state, st):
        nonlocal eagle_stuck_count
        for a in state.get("assets", []):
            if a["asset_id"] == "eagle-1" and a.get("status") == "executing":
                if a.get("speed", 0) < 0.1:
                    eagle_stuck_count += 1
                    if eagle_stuck_count == 20:  # 5s at 4Hz... but we poll at 1s
                        print(f"  [{elapsed_str(st)}] WARNING: eagle-1 stuck (speed=0 while executing)")
                else:
                    eagle_stuck_count = 0

    wait_with_monitor(150, ws, run_start, monitor)
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-02 complete")
    reset_cycle(ws, run_start, snap_file)


def test_03_escort(ws, run_start, snap_file):
    test_id = "TEST-03-ESCORT"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    # Spawn escort target close
    heading_rad = compass_to_math_rad(90)  # heading East
    api("POST", "/api/contacts", {
        "contact_id": "escort-target",
        "x": 500, "y": 200,
        "heading": heading_rad,
        "speed": 2.0,
        "domain": "surface",
    })
    print(f"  [{elapsed_str(run_start)}] Spawned escort-target at (500, 200) heading E @ 2 m/s")
    time.sleep(1)

    wps = [{"x": 500, "y": 200}]
    cmd = make_fleet_command("escort", wps, formation="column", speed=4.0,
                             drone_pattern="orbit", drone_altitude=150.0)
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] ESCORT dispatched: {result.get('success') if result else 'FAILED'}")

    min_dist = float("inf")
    def monitor(state, st):
        nonlocal min_dist
        contacts = state.get("contacts", [])
        target = next((c for c in contacts if c.get("contact_id") == "escort-target"), None)
        if target:
            tx, ty = target["x"], target["y"]
            for a in state.get("assets", []):
                if a.get("domain") == "surface":
                    dist = math.sqrt((a["x"] - tx)**2 + (a["y"] - ty)**2)
                    if dist < min_dist:
                        min_dist = dist
                        if dist < 300:
                            print(f"  [{elapsed_str(st)}] {a['asset_id']} within {dist:.0f}m of escort-target")

    wait_with_monitor(120, ws, run_start, monitor)
    print(f"  [{elapsed_str(run_start)}] Closest approach to escort-target: {min_dist:.0f}m")
    api("DELETE", "/api/contacts/escort-target")
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-03 complete")
    reset_cycle(ws, run_start, snap_file)


def test_04_loiter(ws, run_start, snap_file):
    test_id = "TEST-04-LOITER"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 1000, "y": 500}]
    cmd = make_fleet_command("loiter", wps, formation="spread", speed=5.0,
                             drone_pattern="orbit", drone_altitude=100.0)
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] LOITER dispatched: {result.get('success') if result else 'FAILED'}")

    def monitor(state, st):
        for a in state.get("assets", []):
            if a["asset_id"] == "alpha":
                twp = a.get("total_waypoints", 0)
                if twp > 3:  # orbit waypoints generated
                    pass  # captured in data

    wait_with_monitor(150, ws, run_start, monitor)
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-04 complete")
    reset_cycle(ws, run_start, snap_file)


def test_05_aerial_recon(ws, run_start, snap_file):
    test_id = "TEST-05-AERIAL-RECON"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 2000, "y": 2000}]
    cmd = make_fleet_command("aerial_recon", wps, formation="independent", speed=5.0,
                             drone_pattern="sweep", drone_altitude=150.0)
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] AERIAL_RECON dispatched: {result.get('success') if result else 'FAILED'}")

    wait_with_monitor(120, ws, run_start)
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-05 complete")
    reset_cycle(ws, run_start, snap_file)


def test_06_threat_escalation(ws, run_start, snap_file):
    test_id = "TEST-06-THREAT-ESCALATION"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    # Spawn contact at ~8900m, heading SW
    heading_rad = compass_to_math_rad(225)  # SW
    api("POST", "/api/contacts", {
        "contact_id": "bogey-far",
        "x": 7000, "y": 5500,
        "heading": heading_rad,
        "speed": 2.0,
        "domain": "surface",
    })
    dist = math.sqrt(7000**2 + 5500**2)
    print(f"  [{elapsed_str(run_start)}] Spawned bogey-far at (7000, 5500) ~{dist:.0f}m, heading SW @ 2 m/s")

    prev_threat = None
    prev_kc = None
    def monitor(state, st):
        nonlocal prev_threat, prev_kc
        for t in state.get("threat_assessments", []):
            if t.get("contact_id") == "bogey-far":
                level = t.get("threat_level", "none")
                dist = t.get("distance", 0)
                if level != prev_threat:
                    print(f"  [{elapsed_str(st)}] bogey-far: {prev_threat or 'none'} -> {level} "
                          f"(dist={dist:.0f}m)")
                    prev_threat = level

        autonomy = state.get("autonomy", {})
        kc = autonomy.get("kill_chain_phase")
        if kc and kc != prev_kc:
            print(f"  [{elapsed_str(st)}] Kill chain: {prev_kc or 'none'} -> {kc}")
            prev_kc = kc

    wait_with_monitor(240, ws, run_start, monitor)
    api("DELETE", "/api/contacts/bogey-far")
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-06 complete")
    reset_cycle(ws, run_start, snap_file)


def test_07_intercept_replan(ws, run_start, snap_file):
    test_id = "TEST-07-INTERCEPT-REPLAN"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    # Spawn contact heading SW
    heading_sw = compass_to_math_rad(225)
    api("POST", "/api/contacts", {
        "contact_id": "bogey-mover",
        "x": 4000, "y": 3000,
        "heading": heading_sw,
        "speed": 3.0,
        "domain": "surface",
    })
    print(f"  [{elapsed_str(run_start)}] Spawned bogey-mover at (4000, 3000) heading SW @ 3 m/s")

    # Wait for detection
    time.sleep(5)

    # Dispatch intercept
    wps = [{"x": 4000, "y": 3000}]
    cmd = make_fleet_command("intercept", wps, formation="echelon", speed=8.0,
                             drone_pattern="track", drone_altitude=100.0)
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] INTERCEPT dispatched: {result.get('success') if result else 'FAILED'}")

    # After 30s, change bogey direction by respawning
    direction_changed = False
    test_start = time.time()

    prev_kc = None
    def monitor(state, st):
        nonlocal direction_changed, prev_kc
        elapsed = time.time() - test_start

        # At 35s (30s after dispatch), respawn with new heading
        if elapsed > 35 and not direction_changed:
            # Get current bogey position
            contacts = state.get("contacts", [])
            bogey = next((c for c in contacts if c.get("contact_id") == "bogey-mover"), None)
            if bogey:
                bx, by = bogey["x"], bogey["y"]
                api("DELETE", "/api/contacts/bogey-mover")
                heading_n = compass_to_math_rad(0)  # heading North
                api("POST", "/api/contacts", {
                    "contact_id": "bogey-mover",
                    "x": bx, "y": by,
                    "heading": heading_n,
                    "speed": 3.0,
                    "domain": "surface",
                })
                print(f"  [{elapsed_str(st)}] bogey-mover respawned at ({bx:.0f}, {by:.0f}) NOW heading NORTH")
                direction_changed = True

        autonomy = state.get("autonomy", {})
        kc = autonomy.get("kill_chain_phase")
        if kc and kc != prev_kc:
            print(f"  [{elapsed_str(st)}] Kill chain: {prev_kc or 'none'} -> {kc}")
            prev_kc = kc

        targeting = autonomy.get("targeting", {})
        if targeting and targeting.get("locked"):
            print(f"  [{elapsed_str(st)}] TARGET LOCKED — range={targeting.get('range_m', 0):.0f}m "
                  f"confidence={targeting.get('confidence', 0):.2f}")

    wait_with_monitor(180, ws, run_start, monitor)
    api("DELETE", "/api/contacts/bogey-mover")
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-07 complete")
    reset_cycle(ws, run_start, snap_file)


def test_08_comms_continue(ws, run_start, snap_file):
    test_id = "TEST-08-COMMS-CONTINUE"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 1500, "y": 1000}, {"x": 1500, "y": -500}, {"x": 0, "y": 0}]
    cmd = make_fleet_command("patrol", wps, formation="echelon", speed=5.0,
                             comms_lost_behavior="continue_mission",
                             drone_pattern="orbit")
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] PATROL (continue_mission) dispatched: "
          f"{result.get('success') if result else 'FAILED'}")

    # Wait for patrol to establish
    time.sleep(15)

    # Deny comms
    api("POST", "/api/comms-mode", {"mode": "denied"})
    print(f"  [{elapsed_str(run_start)}] COMMS DENIED")

    prev_wp = {}
    prev_actions = 0
    def monitor(state, st):
        nonlocal prev_actions
        for a in state.get("assets", []):
            aid = a["asset_id"]
            wpi = a.get("current_waypoint_index", 0)
            if aid not in prev_wp:
                prev_wp[aid] = wpi
            if wpi != prev_wp[aid]:
                print(f"  [{elapsed_str(st)}] {aid}: waypoint {prev_wp[aid]} -> {wpi} (comms denied)")
                prev_wp[aid] = wpi

        autonomy = state.get("autonomy", {})
        actions = autonomy.get("autonomous_actions", [])
        if len(actions) > prev_actions:
            for a in actions[prev_actions:]:
                print(f"  [{elapsed_str(st)}] AUTONOMOUS ACTION: {a}")
            prev_actions = len(actions)

    wait_with_monitor(90, ws, run_start, monitor)
    api("POST", "/api/comms-mode", {"mode": "full"})
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-08 complete")
    reset_cycle(ws, run_start, snap_file)


def test_09_comms_hold(ws, run_start, snap_file):
    test_id = "TEST-09-COMMS-HOLD"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 1500, "y": 1000}]
    cmd = make_fleet_command("patrol", wps, formation="echelon", speed=5.0,
                             comms_lost_behavior="hold_position",
                             drone_pattern="orbit")
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] PATROL (hold_position) dispatched: "
          f"{result.get('success') if result else 'FAILED'}")

    time.sleep(30)  # Let vessels get mid-transit
    api("POST", "/api/comms-mode", {"mode": "denied"})
    print(f"  [{elapsed_str(run_start)}] COMMS DENIED — vessels should hold position")

    def monitor(state, st):
        for a in state.get("assets", []):
            if a["asset_id"] == "alpha":
                spd = a.get("speed", 0)
                if spd < 0.1:
                    pass  # captured in data

    wait_with_monitor(60, ws, run_start, monitor)
    api("POST", "/api/comms-mode", {"mode": "full"})
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-09 complete")
    reset_cycle(ws, run_start, snap_file)


def test_10_comms_rtb(ws, run_start, snap_file):
    test_id = "TEST-10-COMMS-RTB"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 2000, "y": 1500}]
    cmd = make_fleet_command("patrol", wps, formation="echelon", speed=5.0,
                             comms_lost_behavior="return_to_base",
                             drone_pattern="orbit")
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] PATROL (return_to_base) dispatched: "
          f"{result.get('success') if result else 'FAILED'}")

    time.sleep(30)
    api("POST", "/api/comms-mode", {"mode": "denied"})
    print(f"  [{elapsed_str(run_start)}] COMMS DENIED — vessels should RTB")

    def monitor(state, st):
        autonomy = state.get("autonomy", {})
        actions = autonomy.get("autonomous_actions", [])
        for a in actions:
            if "RTB" in a:
                pass  # captured

    wait_with_monitor(120, ws, run_start, monitor)
    api("POST", "/api/comms-mode", {"mode": "full"})
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-10 complete")
    reset_cycle(ws, run_start, snap_file)


def test_11_comms_auto_engage(ws, run_start, snap_file):
    test_id = "TEST-11-COMMS-AUTOENGAGE"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 1500, "y": 1000}]
    cmd = make_fleet_command("patrol", wps, formation="echelon", speed=5.0,
                             comms_lost_behavior="continue_mission",
                             drone_pattern="orbit")
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] PATROL (continue_mission) dispatched")

    time.sleep(10)

    # Spawn threat
    heading_nw = compass_to_math_rad(315)  # NW
    api("POST", "/api/contacts", {
        "contact_id": "bogey-auto",
        "x": 3000, "y": 0,
        "heading": heading_nw,
        "speed": 4.0,
        "domain": "surface",
    })
    print(f"  [{elapsed_str(run_start)}] Spawned bogey-auto at (3000, 0) heading NW @ 4 m/s")

    time.sleep(5)

    # Deny comms
    comms_denied_time = time.time()
    api("POST", "/api/comms-mode", {"mode": "denied"})
    print(f"  [{elapsed_str(run_start)}] COMMS DENIED — waiting for auto-engage at 60s")

    prev_actions = 0
    def monitor(state, st):
        nonlocal prev_actions
        autonomy = state.get("autonomy", {})
        denied_dur = autonomy.get("comms_denied_duration", 0)
        actions = autonomy.get("autonomous_actions", [])
        if len(actions) > prev_actions:
            for a in actions[prev_actions:]:
                print(f"  [{elapsed_str(st)}] AUTONOMOUS ACTION ({denied_dur:.0f}s denied): {a}")
            prev_actions = len(actions)

        kc = autonomy.get("kill_chain_phase")
        if kc and denied_dur > 55:
            pass  # captured in data

    wait_with_monitor(120, ws, run_start, monitor)
    api("POST", "/api/comms-mode", {"mode": "full"})
    api("DELETE", "/api/contacts/bogey-auto")
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-11 complete")
    reset_cycle(ws, run_start, snap_file)


def test_12_gps_degraded(ws, run_start, snap_file):
    test_id = "TEST-12-GPS-DEGRADED"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 1500, "y": 1000}, {"x": 0, "y": 0}]
    cmd = make_fleet_command("patrol", wps, formation="echelon", speed=5.0,
                             drone_pattern="orbit")
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] PATROL dispatched for GPS noise test")

    time.sleep(15)

    for noise in [25, 50, 100]:
        api("POST", "/api/gps-mode", {"mode": "degraded", "noise_meters": noise})
        print(f"  [{elapsed_str(run_start)}] GPS DEGRADED — noise={noise}m")
        wait_with_monitor(60, ws, run_start)

    api("POST", "/api/gps-mode", {"mode": "full"})
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-12 complete")
    reset_cycle(ws, run_start, snap_file)


def test_13_gps_denied_drift(ws, run_start, snap_file):
    test_id = "TEST-13-GPS-DENIED-DRIFT"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    # Square patrol for easy geometry
    wps = [{"x": 2000, "y": 0}, {"x": 2000, "y": 2000},
           {"x": 0, "y": 2000}, {"x": 0, "y": 0}]
    cmd = make_fleet_command("patrol", wps, formation="independent", speed=5.0,
                             drone_pattern="orbit")
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] Square PATROL dispatched")

    time.sleep(10)

    api("POST", "/api/gps-mode", {"mode": "denied"})
    print(f"  [{elapsed_str(run_start)}] GPS DENIED — tracking drift")

    def monitor(state, st):
        for a in state.get("assets", []):
            if a["asset_id"] == "alpha":
                acc = a.get("position_accuracy", 1.0)
                if acc > 2:
                    pass  # captured in data

    wait_with_monitor(180, ws, run_start, monitor, poll_interval=5.0)

    # Restore GPS — measure snap
    print(f"  [{elapsed_str(run_start)}] Restoring GPS — measuring position snap")
    pre_state = ws.state
    if pre_state:
        for a in pre_state.get("assets", []):
            print(f"  [{elapsed_str(run_start)}] Pre-restore {a['asset_id']}: "
                  f"accuracy={a.get('position_accuracy', 0):.1f}m")

    api("POST", "/api/gps-mode", {"mode": "full"})
    time.sleep(2)  # Let snap happen

    post_state = ws.state
    if post_state:
        for a in post_state.get("assets", []):
            print(f"  [{elapsed_str(run_start)}] Post-restore {a['asset_id']}: "
                  f"accuracy={a.get('position_accuracy', 0):.1f}m")

    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-13 complete")
    reset_cycle(ws, run_start, snap_file)


def test_14_double_denial(ws, run_start, snap_file):
    test_id = "TEST-14-DOUBLE-DENIAL"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 1500, "y": 1000}]
    cmd = make_fleet_command("patrol", wps, formation="echelon", speed=5.0,
                             comms_lost_behavior="continue_mission",
                             drone_pattern="orbit")
    api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] PATROL dispatched (continue_mission)")

    time.sleep(15)

    heading_sw = compass_to_math_rad(225)
    api("POST", "/api/contacts", {
        "contact_id": "bogey-stress",
        "x": 3500, "y": 1500,
        "heading": heading_sw,
        "speed": 3.0,
        "domain": "surface",
    })
    print(f"  [{elapsed_str(run_start)}] Spawned bogey-stress at (3500, 1500)")

    time.sleep(5)

    api("POST", "/api/gps-mode", {"mode": "denied"})
    print(f"  [{elapsed_str(run_start)}] GPS DENIED")

    time.sleep(5)

    api("POST", "/api/comms-mode", {"mode": "denied"})
    print(f"  [{elapsed_str(run_start)}] COMMS DENIED — double denial active")

    prev_actions = 0
    def monitor(state, st):
        nonlocal prev_actions
        autonomy = state.get("autonomy", {})
        actions = autonomy.get("autonomous_actions", [])
        if len(actions) > prev_actions:
            for a in actions[prev_actions:]:
                print(f"  [{elapsed_str(st)}] AUTONOMOUS ACTION: {a}")
            prev_actions = len(actions)

    wait_with_monitor(120, ws, run_start, monitor)
    api("POST", "/api/comms-mode", {"mode": "full"})
    api("POST", "/api/gps-mode", {"mode": "full"})
    api("DELETE", "/api/contacts/bogey-stress")
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-14 complete")
    reset_cycle(ws, run_start, snap_file)


def test_15_formations(ws, run_start, snap_file):
    test_id_base = "TEST-15-FORMATION"
    print(f"\n{'='*60}")
    print(f"=== TEST-15: FORMATION COMPARISON ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    for formation in ["echelon", "line", "column", "spread", "independent"]:
        test_id = f"{test_id_base}-{formation.upper()}"
        ws.set_test(test_id)
        snapshot(test_id, "start", snap_file)

        wps = [{"x": 2000, "y": 1000}]
        cmd = make_fleet_command("patrol", wps, formation=formation, speed=5.0,
                                 drone_pattern="orbit")
        result = api("POST", "/api/command-direct", cmd)
        print(f"  [{elapsed_str(run_start)}] {formation.upper()} dispatched: "
              f"{result.get('success') if result else 'FAILED'}")

        wait_with_monitor(60, ws, run_start)
        snapshot(test_id, "end", snap_file)
        print(f"  [{elapsed_str(run_start)}] {formation.upper()} complete")
        reset_cycle(ws, run_start, snap_file)


def test_16_speeds(ws, run_start, snap_file):
    test_id_base = "TEST-16-SPEED"
    print(f"\n{'='*60}")
    print(f"=== TEST-16: SPEED TESTS ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    for speed in [2, 4, 6, 8, 10]:
        test_id = f"{test_id_base}-{speed}MS"
        ws.set_test(test_id)
        snapshot(test_id, "start", snap_file)

        wps = [{"x": 1500, "y": 0}]
        cmd = make_fleet_command("patrol", wps, formation="independent", speed=float(speed),
                                 drone_pattern="orbit")
        result = api("POST", "/api/command-direct", cmd)
        print(f"  [{elapsed_str(run_start)}] Speed {speed} m/s dispatched")

        wait_with_monitor(45, ws, run_start)
        snapshot(test_id, "end", snap_file)
        reset_cycle(ws, run_start, snap_file)


def test_17_multi_contact(ws, run_start, snap_file):
    test_id = "TEST-17-MULTI-CONTACT"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    # Spawn 3 contacts
    api("POST", "/api/contacts", {
        "contact_id": "bogey-A",
        "x": 6000, "y": 3000,
        "heading": compass_to_math_rad(225),
        "speed": 2.0,
        "domain": "surface",
    })
    api("POST", "/api/contacts", {
        "contact_id": "bogey-B",
        "x": 3000, "y": 1000,
        "heading": compass_to_math_rad(270),
        "speed": 5.0,
        "domain": "surface",
    })
    api("POST", "/api/contacts", {
        "contact_id": "bogey-C",
        "x": 1500, "y": -500,
        "heading": compass_to_math_rad(0),
        "speed": 3.0,
        "domain": "surface",
    })
    print(f"  [{elapsed_str(run_start)}] Spawned 3 contacts: bogey-A (far), bogey-B (fast), bogey-C (close)")

    prev_threats = {}
    def monitor(state, st):
        for t in state.get("threat_assessments", []):
            cid = t.get("contact_id", "")
            level = t.get("threat_level", "none")
            dist = t.get("distance", 0)
            if cid and level != prev_threats.get(cid):
                print(f"  [{elapsed_str(st)}] {cid}: {prev_threats.get(cid, 'none')} -> {level} "
                      f"(dist={dist:.0f}m)")
                prev_threats[cid] = level

        autonomy = state.get("autonomy", {})
        targeting = autonomy.get("targeting", {})
        if targeting and targeting.get("contact_id"):
            pass  # captured in data

    wait_with_monitor(60, ws, run_start, monitor)
    for cid in ["bogey-A", "bogey-B", "bogey-C"]:
        api("DELETE", f"/api/contacts/{cid}")
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-17 complete")
    reset_cycle(ws, run_start, snap_file)


def test_18_max_range(ws, run_start, snap_file):
    test_id = "TEST-18-MAX-RANGE"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 4900, "y": 0}]
    cmd = make_fleet_command("patrol", wps, formation="independent", speed=8.0,
                             drone_pattern="orbit")
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] Max-range PATROL dispatched (4900m @ 8 m/s)")

    wait_with_monitor(90, ws, run_start)
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-18 complete")
    reset_cycle(ws, run_start, snap_file)


def test_19_rapid_switching(ws, run_start, snap_file):
    test_id = "TEST-19-RAPID-SWITCH"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    missions = [
        ("patrol", [{"x": 1500, "y": 1000}], "echelon"),
        ("search", [{"x": 1500, "y": 1000}], "line"),
        ("loiter", [{"x": 1000, "y": 500}], "spread"),
        ("patrol", [{"x": 1500, "y": -500}], "column"),
    ]

    for mission_type, wps, formation in missions:
        cmd = make_fleet_command(mission_type, wps, formation=formation, speed=5.0,
                                 drone_pattern="orbit")
        result = api("POST", "/api/command-direct", cmd)
        print(f"  [{elapsed_str(run_start)}] Switched to {mission_type.upper()} ({formation})")
        time.sleep(10)

    wait_with_monitor(10, ws, run_start)
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-19 complete")
    reset_cycle(ws, run_start, snap_file)


def test_20_endurance(ws, run_start, snap_file):
    test_id = "TEST-20-ENDURANCE"
    print(f"\n{'='*60}")
    print(f"=== {test_id} ({elapsed_str(run_start)}) ===")
    print(f"{'='*60}")

    ws.set_test(test_id)
    snapshot(test_id, "start", snap_file)

    wps = [{"x": 2000, "y": 1000}, {"x": 2000, "y": -1000}, {"x": -500, "y": 0}]
    cmd = make_fleet_command("patrol", wps, formation="echelon", speed=5.0,
                             drone_pattern="orbit")
    result = api("POST", "/api/command-direct", cmd)
    print(f"  [{elapsed_str(run_start)}] Endurance PATROL dispatched (300s)")

    prev_wp = {}
    frame_times = []
    def monitor(state, st):
        frame_times.append(time.time())
        for a in state.get("assets", []):
            aid = a["asset_id"]
            wpi = a.get("current_waypoint_index", 0)
            if aid not in prev_wp:
                prev_wp[aid] = wpi
            if wpi != prev_wp[aid]:
                prev_wp[aid] = wpi

    wait_with_monitor(300, ws, run_start, monitor)
    snapshot(test_id, "end", snap_file)
    print(f"  [{elapsed_str(run_start)}] TEST-20 complete")
    # No reset after last test — go straight to data dump


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    capture_path = DATA_DIR / "sim_v2_capture.jsonl"
    decisions_path = DATA_DIR / "sim_v2_decisions.jsonl"
    snapshots_path = DATA_DIR / "sim_v2_snapshots.jsonl"

    print(f"\n{'='*60}")
    print(f"  LocalFleet V2 Deep-Diagnostic Simulation")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  21 tests, isolated with resets")
    print(f"  Estimated runtime: ~45-60 minutes")
    print(f"  Data output: {DATA_DIR}")
    print(f"{'='*60}\n")

    # Verify backend
    try:
        r = requests.get(f"{BASE_URL}/api/assets", timeout=3)
        r.raise_for_status()
        print("Backend is running. Starting simulation...\n")
    except Exception as e:
        print(f"ERROR: Cannot reach backend at {BASE_URL}")
        print(f"  Start it: .venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000")
        sys.exit(1)

    # Start WS capture
    ws = WSCapture(capture_path)
    ws.start()
    time.sleep(1)
    if ws.frame_count == 0:
        time.sleep(2)
    if ws.frame_count == 0:
        print("WARNING: No WebSocket frames received yet. Continuing anyway...")

    # Start decision poller
    poller = DecisionPoller(decisions_path)
    poller.start()

    run_start = time.time()

    with open(snapshots_path, "w") as snap_f:
        try:
            # Initial reset to known state
            ws.set_test("INIT-RESET")
            poller.set_test("INIT-RESET")
            reset_cycle(ws, run_start, snap_f)

            tests = [
                ("TEST-00", test_00_baseline),
                ("TEST-01", test_01_patrol),
                ("TEST-02", test_02_search),
                ("TEST-03", test_03_escort),
                ("TEST-04", test_04_loiter),
                ("TEST-05", test_05_aerial_recon),
                ("TEST-06", test_06_threat_escalation),
                ("TEST-07", test_07_intercept_replan),
                ("TEST-08", test_08_comms_continue),
                ("TEST-09", test_09_comms_hold),
                ("TEST-10", test_10_comms_rtb),
                ("TEST-11", test_11_comms_auto_engage),
                ("TEST-12", test_12_gps_degraded),
                ("TEST-13", test_13_gps_denied_drift),
                ("TEST-14", test_14_double_denial),
                ("TEST-15", test_15_formations),
                ("TEST-16", test_16_speeds),
                ("TEST-17", test_17_multi_contact),
                ("TEST-18", test_18_max_range),
                ("TEST-19", test_19_rapid_switching),
                ("TEST-20", test_20_endurance),
            ]

            for test_name, test_fn in tests:
                poller.set_test(test_name)
                test_fn(ws, run_start, snap_f)

            # End-of-run data dump
            print(f"\n{'='*60}")
            print(f"=== FINAL DATA DUMP ({elapsed_str(run_start)}) ===")
            print(f"{'='*60}")

            ws.set_test("FINAL")
            poller.set_test("FINAL")

            decisions = api("GET", "/api/decisions", params={"limit": 1000})
            if decisions:
                dec_count = len(decisions.get("decisions", []))
                print(f"  Total decisions: {dec_count}")

            logs = api("GET", "/api/logs", params={"limit": 5000})
            if logs:
                print(f"  Total log entries: {logs.get('count', 0)}")

            summary = api("GET", "/api/logs/summary")
            if summary:
                print(f"  Log summary: {summary}")

            final_state = api("GET", "/api/assets")
            if final_state:
                for a in final_state.get("assets", []):
                    print(f"  {a['asset_id']}: ({a['x']:.0f}, {a['y']:.0f}) status={a['status']}")

            snapshot("FINAL", "end_of_run", snap_f)

        except KeyboardInterrupt:
            print("\n\nSimulation interrupted by operator.")
        finally:
            ws.stop()
            poller.stop()

    elapsed = time.time() - run_start
    print(f"\n{'='*60}")
    print(f"  SIMULATION COMPLETE")
    print(f"  Duration: {int(elapsed)//60}m {int(elapsed)%60}s")
    print(f"  WebSocket frames captured: {ws.frame_count}")
    print(f"  Files written:")
    print(f"    {capture_path}")
    print(f"    {decisions_path}")
    print(f"    {snapshots_path}")
    print(f"{'='*60}\n")
    print(f"Next: .venv/bin/python scripts/analyze_simulation_v2.py")


if __name__ == "__main__":
    main()
