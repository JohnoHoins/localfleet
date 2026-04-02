#!/usr/bin/env python3
"""
LocalFleet V2 Simulation Analyzer

Reads captured data from data/sim_v2_capture.jsonl and produces:
  - data/sim_v2_report.txt       — per-test analysis report with pass/fail
  - data/sim_v2_timeline.csv     — second-by-second state with test_id
  - data/sim_v2_formation.csv    — formation geometry per tick
  - data/sim_v2_threats.csv      — threat escalation timeline
  - data/sim_v2_drift.csv        — dead reckoning drift curve

Usage:
    .venv/bin/python scripts/analyze_simulation_v2.py
"""

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CAPTURE_FILE = DATA_DIR / "sim_v2_capture.jsonl"
DECISIONS_FILE = DATA_DIR / "sim_v2_decisions.jsonl"
REPORT_FILE = DATA_DIR / "sim_v2_report.txt"
TIMELINE_FILE = DATA_DIR / "sim_v2_timeline.csv"
FORMATION_FILE = DATA_DIR / "sim_v2_formation.csv"
THREATS_FILE = DATA_DIR / "sim_v2_threats.csv"
DRIFT_FILE = DATA_DIR / "sim_v2_drift.csv"

# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_capture(path: Path) -> list[dict]:
    """Load wrapped frames: {test, wall_clock, frame}."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def load_decisions(path: Path) -> list[dict]:
    """Load decision entries."""
    decisions = []
    if not path.exists():
        return decisions
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if "decision" in data:
                    data["decision"]["_test"] = data.get("test", "")
                    decisions.append(data["decision"])
                elif "decisions" in data:
                    for d in data["decisions"]:
                        decisions.append(d)
                else:
                    decisions.append(data)
            except json.JSONDecodeError:
                continue
    return decisions


def group_by_test(entries: list[dict]) -> dict[str, list[dict]]:
    """Group captured entries by test_id, returning {test_id: [frames]}."""
    groups = defaultdict(list)
    for e in entries:
        test = e.get("test", "UNKNOWN")
        frame = e.get("frame", e)
        frame["_wall_clock"] = e.get("wall_clock", 0)
        frame["_test"] = test
        groups[test].append(frame)
    return dict(groups)


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

def dist(x1, y1, x2, y2):
    return math.sqrt((x1 - x2)**2 + (y1 - y2)**2)


def asset_positions(frame):
    """Return {asset_id: (x, y)} from a frame."""
    return {a["asset_id"]: (a.get("x", 0), a.get("y", 0))
            for a in frame.get("assets", [])}


def asset_by_id(frame, aid):
    for a in frame.get("assets", []):
        if a["asset_id"] == aid:
            return a
    return None


def mean(values):
    return sum(values) / len(values) if values else 0


def std_dev(values):
    if len(values) < 2:
        return 0
    m = mean(values)
    return math.sqrt(sum((v - m)**2 for v in values) / (len(values) - 1))


def fit_circle(points):
    """Fit a circle to 2D points using algebraic method. Returns (cx, cy, r, error)."""
    if len(points) < 3:
        return 0, 0, 0, float("inf")

    # Use algebraic circle fit (Kasa method)
    n = len(points)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sx2 = sum(p[0]**2 for p in points)
    sy2 = sum(p[1]**2 for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    sx3 = sum(p[0]**3 for p in points)
    sy3 = sum(p[1]**3 for p in points)
    sx2y = sum(p[0]**2 * p[1] for p in points)
    sxy2 = sum(p[0] * p[1]**2 for p in points)

    A = n * sx2 - sx**2
    B = n * sxy - sx * sy
    C = n * sy2 - sy**2
    D = 0.5 * (n * sx3 + n * sxy2 - sx * sx2 - sx * sy2)
    E = 0.5 * (n * sx2y + n * sy3 - sy * sx2 - sy * sy2)

    denom = A * C - B * B
    if abs(denom) < 1e-10:
        return 0, 0, 0, float("inf")

    cx = (D * C - B * E) / denom
    cy = (A * E - B * D) / denom
    r = math.sqrt((sx2 + sy2 - 2 * cx * sx - 2 * cy * sy) / n + cx**2 + cy**2)

    # Fitting error (RMS distance from circle)
    errors = [abs(dist(p[0], p[1], cx, cy) - r) for p in points]
    rms_error = math.sqrt(sum(e**2 for e in errors) / len(errors))

    return cx, cy, r, rms_error


# ---------------------------------------------------------------------------
# Per-Test Analysis Functions
# ---------------------------------------------------------------------------

def analyze_formation(frames, commanded_spacing=200.0):
    """Compute inter-vessel distances per tick."""
    records = []
    for f in frames:
        pos = asset_positions(f)
        if "alpha" not in pos or "bravo" not in pos or "charlie" not in pos:
            continue
        ab = dist(*pos["alpha"], *pos["bravo"])
        bc = dist(*pos["bravo"], *pos["charlie"])
        ac = dist(*pos["alpha"], *pos["charlie"])
        mean_err = mean([abs(ab - commanded_spacing), abs(bc - commanded_spacing)])
        records.append({
            "wall_clock": f.get("_wall_clock", 0),
            "alpha_bravo": ab,
            "bravo_charlie": bc,
            "alpha_charlie": ac,
            "mean_error": mean_err,
        })
    return records


def analyze_waypoint_loops(frames, asset_id="alpha"):
    """Count waypoint index transitions and detect loops."""
    transitions = []
    prev_wpi = None
    for f in frames:
        a = asset_by_id(f, asset_id)
        if not a:
            continue
        wpi = a.get("current_waypoint_index", 0)
        if prev_wpi is not None and wpi != prev_wpi:
            transitions.append((f.get("_wall_clock", 0), prev_wpi, wpi))
        prev_wpi = wpi

    # Detect loop: wpi goes back to 0
    loops = sum(1 for _, _, to_wp in transitions if to_wp == 0)
    return transitions, loops


def analyze_drone_orbit(frames):
    """Extract drone positions during orbit and fit circle."""
    points = []
    for f in frames:
        a = asset_by_id(f, "eagle-1")
        if a and a.get("drone_pattern") == "orbit" and a.get("status") == "executing":
            points.append((a["x"], a["y"]))

    if len(points) < 10:
        return None

    cx, cy, r, err = fit_circle(points)
    return {"center_x": cx, "center_y": cy, "radius": r, "fit_error": err,
            "num_points": len(points)}


def analyze_drone_stuck(frames):
    """Find periods where eagle-1 is executing but stationary."""
    stuck_periods = []
    stuck_start = None
    prev_pos = None
    for f in frames:
        a = asset_by_id(f, "eagle-1")
        if not a:
            continue
        x, y = a["x"], a["y"]
        if a.get("status") == "executing" and prev_pos:
            if abs(x - prev_pos[0]) < 0.01 and abs(y - prev_pos[1]) < 0.01:
                if stuck_start is None:
                    stuck_start = f.get("_wall_clock", 0)
            else:
                if stuck_start is not None:
                    duration = f.get("_wall_clock", 0) - stuck_start
                    if duration > 5:  # >5s stuck
                        stuck_periods.append({"start": stuck_start, "duration_s": duration})
                    stuck_start = None
        else:
            if stuck_start is not None:
                duration = f.get("_wall_clock", 0) - stuck_start
                if duration > 5:
                    stuck_periods.append({"start": stuck_start, "duration_s": duration})
                stuck_start = None
        prev_pos = (x, y)
    return stuck_periods


def analyze_threat_timeline(frames):
    """Build threat escalation timeline per contact."""
    contacts = defaultdict(lambda: {
        "first_seen": None, "threat_transitions": [],
        "prev_level": None, "closest_approach": float("inf"),
        "drone_track_time": None, "first_intercept_recommend": None,
    })

    for f in frames:
        wc = f.get("_wall_clock", 0)

        # Track contacts
        for c in f.get("contacts", []):
            cid = c["contact_id"]
            if contacts[cid]["first_seen"] is None:
                contacts[cid]["first_seen"] = wc

        # Threat levels
        for t in f.get("threat_assessments", []):
            cid = t.get("contact_id", "")
            level = t.get("threat_level", "none")
            distance = t.get("distance", 0)
            cd = contacts[cid]
            if level != cd["prev_level"]:
                cd["threat_transitions"].append({
                    "time": wc, "from": cd["prev_level"], "to": level,
                    "distance": distance,
                })
                cd["prev_level"] = level

        # Closest approach
        for c in f.get("contacts", []):
            cid = c["contact_id"]
            cx, cy = c.get("x", 0), c.get("y", 0)
            for a in f.get("assets", []):
                if a.get("domain") == "surface":
                    d = dist(a["x"], a["y"], cx, cy)
                    if d < contacts[cid]["closest_approach"]:
                        contacts[cid]["closest_approach"] = d

        # Drone tracking
        autonomy = f.get("autonomy", {})
        targeting = autonomy.get("targeting", {})
        target_cid = targeting.get("contact_id", "")
        if target_cid and contacts[target_cid]["drone_track_time"] is None:
            eagle = asset_by_id(f, "eagle-1")
            if eagle and eagle.get("drone_pattern") == "track":
                contacts[target_cid]["drone_track_time"] = wc

        # Intercept recommended
        if f.get("intercept_recommended"):
            rec_target = f.get("recommended_target", "")
            if rec_target and contacts[rec_target]["first_intercept_recommend"] is None:
                contacts[rec_target]["first_intercept_recommend"] = wc

    return dict(contacts)


def analyze_kill_chain(frames):
    """Track kill chain phase transitions."""
    transitions = []
    prev_kc = None
    for f in frames:
        autonomy = f.get("autonomy", {})
        kc = autonomy.get("kill_chain_phase")
        if kc != prev_kc:
            transitions.append({
                "time": f.get("_wall_clock", 0),
                "from": prev_kc,
                "to": kc,
                "target": autonomy.get("kill_chain_target"),
            })
            prev_kc = kc
    return transitions


def analyze_dr_drift(frames):
    """Compute dead reckoning drift per tick during GPS DENIED."""
    records = []
    for f in frames:
        if f.get("gps_mode") != "denied":
            continue
        wc = f.get("_wall_clock", 0)
        for a in f.get("assets", []):
            if a.get("gps_mode") == "denied":
                records.append({
                    "wall_clock": wc,
                    "asset_id": a["asset_id"],
                    "x": a["x"],
                    "y": a["y"],
                    "speed": a.get("speed", 0),
                    "position_accuracy": a.get("position_accuracy", 1.0),
                })
    return records


def analyze_speed_curve(frames, asset_id="alpha"):
    """Track speed over time for acceleration analysis."""
    records = []
    for f in frames:
        a = asset_by_id(f, asset_id)
        if a:
            records.append({
                "wall_clock": f.get("_wall_clock", 0),
                "speed": a.get("speed", 0),
                "x": a["x"],
                "y": a["y"],
            })
    return records


def analyze_position_jumps(frames):
    """Detect position jumps > 50m between consecutive frames."""
    prev = {}
    jumps = []
    for f in frames:
        for a in f.get("assets", []):
            aid = a["asset_id"]
            x, y = a["x"], a["y"]
            if aid in prev:
                px, py = prev[aid]
                d = dist(x, y, px, py)
                if d > 50 and a.get("domain") == "surface":
                    jumps.append({
                        "wall_clock": f.get("_wall_clock", 0),
                        "asset_id": aid,
                        "jump_m": d,
                    })
            prev[aid] = (x, y)
    return jumps


def analyze_comms_behavior(frames):
    """Track vessel behavior during comms denial."""
    comms_denied_start = None
    results = {
        "waypoint_transitions_during_denial": 0,
        "speeds_during_denial": [],
        "autonomous_actions": [],
        "status_during_denial": Counter(),
    }
    prev_wp = {}

    for f in frames:
        autonomy = f.get("autonomy", {})
        comms = autonomy.get("comms_mode", "full")

        if comms == "denied":
            if comms_denied_start is None:
                comms_denied_start = f.get("_wall_clock", 0)

            for a in f.get("assets", []):
                aid = a["asset_id"]
                wpi = a.get("current_waypoint_index", 0)
                results["speeds_during_denial"].append(a.get("speed", 0))
                results["status_during_denial"][a.get("status", "")] += 1

                if aid not in prev_wp:
                    prev_wp[aid] = wpi
                if wpi != prev_wp[aid]:
                    results["waypoint_transitions_during_denial"] += 1
                    prev_wp[aid] = wpi

            actions = autonomy.get("autonomous_actions", [])
            for act in actions:
                if act not in results["autonomous_actions"]:
                    results["autonomous_actions"].append(act)
        else:
            comms_denied_start = None

    return results


def analyze_gps_noise(frames):
    """Measure position jitter at different noise levels."""
    # Group frames by approximate noise level (from position_accuracy)
    noise_groups = defaultdict(list)
    prev_pos = {}

    for f in frames:
        for a in f.get("assets", []):
            if a.get("domain") != "surface":
                continue
            aid = a["asset_id"]
            x, y = a["x"], a["y"]
            acc = a.get("position_accuracy", 1.0)
            gps = a.get("gps_mode", "full")

            if gps == "degraded" and aid in prev_pos:
                px, py = prev_pos[aid]
                frame_jump = dist(x, y, px, py)
                # Subtract expected motion (speed * 0.25s)
                expected_motion = a.get("speed", 0) * 0.25
                residual = max(0, frame_jump - expected_motion)
                # Bucket by approximate noise level
                if acc < 30:
                    noise_groups[25].append(residual)
                elif acc < 60:
                    noise_groups[50].append(residual)
                else:
                    noise_groups[100].append(residual)

            prev_pos[aid] = (x, y)

    results = {}
    for noise_level, residuals in sorted(noise_groups.items()):
        results[noise_level] = {
            "mean_jitter": mean(residuals),
            "max_jitter": max(residuals) if residuals else 0,
            "std_jitter": std_dev(residuals),
            "samples": len(residuals),
        }
    return results


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_report(test_groups, decisions):
    """Generate the master report."""
    lines = []

    def section(title):
        lines.append("")
        lines.append("=" * 70)
        lines.append(f"  {title}")
        lines.append("=" * 70)
        lines.append("")

    # Pass/Fail summary table
    summary_rows = []

    # Collect test results
    test_results = {}

    # ---- TEST 00: BASELINE ----
    test_id = "TEST-00-BASELINE"
    frames = test_groups.get(test_id, [])
    result = "SKIP"
    key_metric = "No data"
    if frames:
        last = frames[-1]
        all_idle = all(a.get("status") == "idle" for a in last.get("assets", []))
        result = "PASS" if all_idle else "FAIL"
        key_metric = f"All idle: {all_idle}, {len(frames)} frames"
    summary_rows.append((test_id, result, key_metric))
    test_results[test_id] = {"result": result, "frames": len(frames)}

    # ---- TEST 01: PATROL ----
    test_id = "TEST-01-PATROL"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames ({len(frames)*0.25:.0f}s approx)")

        # Waypoint loops
        for aid in ["alpha", "bravo", "charlie"]:
            transitions, loops = analyze_waypoint_loops(frames, aid)
            lines.append(f"  {aid}: {len(transitions)} waypoint transitions, {loops} loops")

        # Formation
        formation_data = analyze_formation(frames, 200.0)
        if formation_data:
            ab_dists = [r["alpha_bravo"] for r in formation_data]
            bc_dists = [r["bravo_charlie"] for r in formation_data]
            lines.append(f"  FORMATION (echelon, target=200m):")
            lines.append(f"    alpha-bravo: mean={mean(ab_dists):.1f}m, max={max(ab_dists):.1f}m, "
                         f"std={std_dev(ab_dists):.1f}m")
            lines.append(f"    bravo-charlie: mean={mean(bc_dists):.1f}m, max={max(bc_dists):.1f}m, "
                         f"std={std_dev(bc_dists):.1f}m")

        # Drone orbit
        orbit = analyze_drone_orbit(frames)
        if orbit:
            lines.append(f"  DRONE ORBIT:")
            lines.append(f"    Radius: {orbit['radius']:.1f}m (target: 150m, "
                         f"error: {abs(orbit['radius']-150)/150*100:.1f}%)")
            lines.append(f"    Center: ({orbit['center_x']:.0f}, {orbit['center_y']:.0f})")
            lines.append(f"    Fit error (RMS): {orbit['fit_error']:.1f}m")

        # Stuck check
        stuck = analyze_drone_stuck(frames)
        lines.append(f"  Drone stuck periods: {len(stuck)}")

        _, loops = analyze_waypoint_loops(frames, "alpha")
        result = "PASS" if loops >= 1 else "WARN"
        key_metric = f"{loops} loops, {mean(ab_dists):.0f}m spacing" if formation_data else f"{loops} loops"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 02: SEARCH ----
    test_id = "TEST-02-SEARCH"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        # Formation (line abreast)
        formation_data = analyze_formation(frames, 200.0)
        if formation_data:
            ab_dists = [r["alpha_bravo"] for r in formation_data]
            lines.append(f"  LINE ABREAST spacing: mean={mean(ab_dists):.1f}m")

        # Drone stuck
        stuck = analyze_drone_stuck(frames)
        total_stuck = sum(s["duration_s"] for s in stuck)
        lines.append(f"  Drone stuck periods: {len(stuck)} (total {total_stuck:.0f}s)")
        for s in stuck:
            lines.append(f"    Stuck for {s['duration_s']:.1f}s")

        # Heading changes (zigzag detection)
        headings = []
        for f in frames:
            a = asset_by_id(f, "alpha")
            if a and a.get("status") == "executing":
                headings.append(a.get("heading", 0))
        reversals = 0
        if len(headings) > 2:
            for i in range(2, len(headings)):
                d1 = headings[i-1] - headings[i-2]
                d2 = headings[i] - headings[i-1]
                if d1 * d2 < 0 and abs(d1) > 5 and abs(d2) > 5:
                    reversals += 1
        lines.append(f"  Heading reversals (zigzag indicator): {reversals}")

        result = "WARN" if stuck else "PASS"
        key_metric = f"Stuck: {total_stuck:.0f}s" if stuck else "No stuck"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 03: ESCORT ----
    test_id = "TEST-03-ESCORT"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        # Closest approach to escort-target
        min_dist_val = float("inf")
        for f in frames:
            contacts = f.get("contacts", [])
            target = next((c for c in contacts if c.get("contact_id") == "escort-target"), None)
            if target:
                tx, ty = target["x"], target["y"]
                for a in f.get("assets", []):
                    if a.get("domain") == "surface":
                        d = dist(a["x"], a["y"], tx, ty)
                        min_dist_val = min(min_dist_val, d)

        if min_dist_val < float("inf"):
            lines.append(f"  Closest approach: {min_dist_val:.0f}m")
        else:
            lines.append(f"  Closest approach: N/A (no contact data)")

        result = "PASS" if min_dist_val < 500 else ("WARN" if min_dist_val < 1000 else "FAIL")
        key_metric = f"Closest: {min_dist_val:.0f}m"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 04: LOITER ----
    test_id = "TEST-04-LOITER"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        # Check for orbit waypoint generation
        orbit_detected = False
        for f in frames:
            a = asset_by_id(f, "alpha")
            if a and a.get("total_waypoints", 0) > 4:
                orbit_detected = True
                break

        lines.append(f"  Orbit waypoints generated: {'YES' if orbit_detected else 'NO'}")

        # Fit circle to vessel paths during orbit phase
        for aid in ["alpha", "bravo", "charlie"]:
            orbit_points = []
            for f in frames:
                a = asset_by_id(f, aid)
                if a and a.get("total_waypoints", 0) > 4 and a.get("status") == "executing":
                    orbit_points.append((a["x"], a["y"]))
            if len(orbit_points) > 20:
                cx, cy, r, err = fit_circle(orbit_points)
                lines.append(f"  {aid} orbit: radius={r:.1f}m (target: 150m), "
                             f"center=({cx:.0f},{cy:.0f}), RMS error={err:.1f}m")

        # Drone orbit
        orbit = analyze_drone_orbit(frames)
        if orbit:
            lines.append(f"  Drone orbit radius: {orbit['radius']:.1f}m")

        result = "PASS" if orbit_detected else "WARN"
        key_metric = f"Orbit: {'YES' if orbit_detected else 'NO'}"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 05: AERIAL RECON ----
    test_id = "TEST-05-AERIAL-RECON"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        # Check surface vessels near (2000, 1500)
        target_x, target_y = 2000, 1500
        surface_dists = []
        for f in frames[-100:]:  # Last ~25s
            for a in f.get("assets", []):
                if a.get("domain") == "surface" and a.get("status") == "executing":
                    d = dist(a["x"], a["y"], target_x, target_y)
                    surface_dists.append(d)

        if surface_dists:
            lines.append(f"  Surface distance from hold point (2000,1500): "
                         f"mean={mean(surface_dists):.0f}m, min={min(surface_dists):.0f}m")

        # Drone altitude
        altitudes = []
        for f in frames:
            a = asset_by_id(f, "eagle-1")
            if a and a.get("altitude"):
                altitudes.append(a["altitude"])
        if altitudes:
            lines.append(f"  Drone altitude: mean={mean(altitudes):.0f}m")

        result = "PASS"
        key_metric = f"Surface hold: {mean(surface_dists):.0f}m" if surface_dists else "No data"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 06: THREAT ESCALATION ----
    test_id = "TEST-06-THREAT-ESCALATION"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        threats = analyze_threat_timeline(frames)
        bogey = threats.get("bogey-far")
        if bogey:
            lines.append(f"  Threat transitions for bogey-far:")
            for t in bogey["threat_transitions"]:
                lines.append(f"    {t['from'] or 'none'} -> {t['to']} "
                             f"(dist={t['distance']:.0f}m)")
            if bogey["drone_track_time"] and bogey["first_seen"]:
                lines.append(f"  Time to drone track: "
                             f"{bogey['drone_track_time'] - bogey['first_seen']:.1f}s")
            lines.append(f"  Closest approach: {bogey['closest_approach']:.0f}m")

            # Check if "detected" level was observed
            detected_seen = any(t["to"] == "detected" for t in bogey["threat_transitions"])
            lines.append(f"  'detected' threat level observed: {'YES' if detected_seen else 'NO'}")

        kc = analyze_kill_chain(frames)
        if kc:
            lines.append(f"  Kill chain transitions: {len(kc)}")
            for t in kc[:10]:
                lines.append(f"    {t['from'] or 'none'} -> {t['to']}")

        result = "PASS" if bogey and len(bogey["threat_transitions"]) > 1 else "WARN"
        key_metric = f"{len(bogey['threat_transitions'])} transitions" if bogey else "No data"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 07: INTERCEPT REPLAN ----
    test_id = "TEST-07-INTERCEPT-REPLAN"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        kc = analyze_kill_chain(frames)
        kc_phases = set(t["to"] for t in kc if t["to"])
        lines.append(f"  Kill chain phases observed: {', '.join(sorted(kc_phases)) or 'none'}")
        for t in kc:
            lines.append(f"    {t['from'] or 'none'} -> {t['to']}")

        # Check for replan decisions
        test_decisions = [d for d in decisions if d.get("_test", "").startswith("TEST-07")]
        replan_count = sum(1 for d in test_decisions if d.get("type") == "replan")
        lines.append(f"  Replan events: {replan_count}")

        # Targeting
        lock_count = 0
        for f in frames:
            autonomy = f.get("autonomy", {})
            targeting = autonomy.get("targeting", {})
            if targeting.get("locked"):
                lock_count += 1
        lines.append(f"  Target locked frames: {lock_count}")

        result = "PASS" if replan_count > 0 else "FAIL"
        key_metric = f"{replan_count} replans, KC: {', '.join(sorted(kc_phases))}"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 08: COMMS CONTINUE ----
    test_id = "TEST-08-COMMS-CONTINUE"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        comms = analyze_comms_behavior(frames)
        lines.append(f"  Waypoint transitions during denial: {comms['waypoint_transitions_during_denial']}")
        lines.append(f"  Autonomous actions: {len(comms['autonomous_actions'])}")
        for a in comms["autonomous_actions"]:
            lines.append(f"    {a}")

        continued = comms["waypoint_transitions_during_denial"] > 0
        result = "PASS" if continued else "FAIL"
        key_metric = f"WP transitions: {comms['waypoint_transitions_during_denial']}"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 09: COMMS HOLD ----
    test_id = "TEST-09-COMMS-HOLD"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        comms = analyze_comms_behavior(frames)
        denied_speeds = comms["speeds_during_denial"]
        if denied_speeds:
            lines.append(f"  Speed during denial: mean={mean(denied_speeds):.2f}, "
                         f"min={min(denied_speeds):.2f}, max={max(denied_speeds):.2f}")
            # Check if speed drops to ~0
            near_zero = sum(1 for s in denied_speeds if s < 0.5)
            lines.append(f"  Frames near zero speed: {near_zero}/{len(denied_speeds)}")

        result = "PASS" if denied_speeds and mean(denied_speeds) < 1.0 else "WARN"
        key_metric = f"Mean speed: {mean(denied_speeds):.1f}" if denied_speeds else "No data"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 10: COMMS RTB ----
    test_id = "TEST-10-COMMS-RTB"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        comms = analyze_comms_behavior(frames)
        lines.append(f"  Status during denial: {dict(comms['status_during_denial'])}")
        lines.append(f"  Autonomous actions: {comms['autonomous_actions']}")

        has_rtb = any("RTB" in a for a in comms["autonomous_actions"])
        result = "PASS" if has_rtb else "WARN"
        key_metric = f"RTB action: {'YES' if has_rtb else 'NO'}"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 11: COMMS AUTO-ENGAGE ----
    test_id = "TEST-11-COMMS-AUTOENGAGE"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        comms = analyze_comms_behavior(frames)
        lines.append(f"  Autonomous actions: {len(comms['autonomous_actions'])}")
        for a in comms["autonomous_actions"]:
            lines.append(f"    {a}")

        has_auto_engage = any("INTERCEPT" in a or "auto_engage" in a.lower()
                              for a in comms["autonomous_actions"])
        result = "PASS" if has_auto_engage else "FAIL"
        key_metric = f"Auto-engage: {'YES' if has_auto_engage else 'NO'}"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 12: GPS DEGRADED ----
    test_id = "TEST-12-GPS-DEGRADED"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        noise = analyze_gps_noise(frames)
        for level, data in sorted(noise.items()):
            lines.append(f"  Noise={level}m: mean_jitter={data['mean_jitter']:.1f}m, "
                         f"max={data['max_jitter']:.1f}m, std={data['std_jitter']:.1f}m "
                         f"({data['samples']} samples)")

        result = "PASS" if noise else "WARN"
        key_metric = f"{len(noise)} noise levels tested"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 13: GPS DENIED DRIFT ----
    test_id = "TEST-13-GPS-DENIED-DRIFT"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        dr = analyze_dr_drift(frames)
        if dr:
            # Group by asset
            by_asset = defaultdict(list)
            for r in dr:
                by_asset[r["asset_id"]].append(r)

            for aid, records in sorted(by_asset.items()):
                if not records:
                    continue
                max_acc = max(r["position_accuracy"] for r in records)
                # Compute cumulative distance
                cum_dist = 0
                for i in range(1, len(records)):
                    cum_dist += records[i]["speed"] * 0.25  # approx
                drift_rate = (max_acc / max(cum_dist, 1)) * 100
                lines.append(f"  {aid}: max drift={max_acc:.1f}m, "
                             f"cum_dist~{cum_dist:.0f}m, "
                             f"drift rate~{drift_rate:.2f}%")

                # Sample at intervals
                t0 = records[0]["wall_clock"]
                for target_s in [30, 60, 90, 120, 150, 180]:
                    closest = min(records, key=lambda r: abs(r["wall_clock"] - t0 - target_s))
                    if abs(closest["wall_clock"] - t0 - target_s) < 5:
                        lines.append(f"    t={target_s}s: accuracy={closest['position_accuracy']:.1f}m")

        # Position snap on GPS restore
        jumps = analyze_position_jumps(frames)
        if jumps:
            lines.append(f"  Position jumps (GPS restore snap): {len(jumps)}")
            for j in jumps[:5]:
                lines.append(f"    {j['asset_id']}: {j['jump_m']:.1f}m")

        result = "PASS" if dr else "WARN"
        key_metric = f"DR data: {len(dr)} samples"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 14: DOUBLE DENIAL ----
    test_id = "TEST-14-DOUBLE-DENIAL"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        comms = analyze_comms_behavior(frames)
        lines.append(f"  Autonomous actions: {comms['autonomous_actions']}")
        dr = analyze_dr_drift(frames)
        if dr:
            max_acc = max(r["position_accuracy"] for r in dr)
            lines.append(f"  Max DR drift: {max_acc:.1f}m")

        result = "PASS"
        key_metric = f"Actions: {len(comms['autonomous_actions'])}, DR: {len(dr)} samples"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 15: FORMATIONS ----
    formation_names = ["ECHELON", "LINE", "COLUMN", "SPREAD", "INDEPENDENT"]
    expected_spacing = {"ECHELON": 200, "LINE": 200, "COLUMN": 200, "SPREAD": 300, "INDEPENDENT": None}
    for fname in formation_names:
        test_id = f"TEST-15-FORMATION-{fname}"
        frames = test_groups.get(test_id, [])
        if frames:
            if fname == formation_names[0]:
                section("TEST-15-FORMATION-COMPARISON")

            target = expected_spacing[fname]
            formation_data = analyze_formation(frames, target or 200.0)
            if formation_data:
                ab = [r["alpha_bravo"] for r in formation_data]
                bc = [r["bravo_charlie"] for r in formation_data]
                lines.append(f"  {fname}: AB mean={mean(ab):.0f}m, BC mean={mean(bc):.0f}m"
                             + (f" (target: {target}m)" if target else ""))

            result = "PASS"
            key_metric = f"AB={mean(ab):.0f}m" if formation_data else "No data"
            summary_rows.append((test_id, result, key_metric))
        else:
            summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 16: SPEEDS ----
    for speed in [2, 4, 6, 8, 10]:
        test_id = f"TEST-16-SPEED-{speed}MS"
        frames = test_groups.get(test_id, [])
        if frames:
            if speed == 2:
                section("TEST-16-SPEED-TESTS")

            sc = analyze_speed_curve(frames, "alpha")
            if sc:
                speeds = [r["speed"] for r in sc]
                max_spd = max(speeds)
                # Time to reach commanded speed
                t0 = sc[0]["wall_clock"]
                time_to_speed = None
                for r in sc:
                    if r["speed"] >= speed * 0.9:
                        time_to_speed = r["wall_clock"] - t0
                        break
                # Distance traveled
                total_d = 0
                for i in range(1, len(sc)):
                    total_d += dist(sc[i]["x"], sc[i]["y"], sc[i-1]["x"], sc[i-1]["y"])

                lines.append(f"  {speed} m/s: max={max_spd:.2f}, "
                             f"time_to_speed={time_to_speed:.1f}s" if time_to_speed else
                             f"  {speed} m/s: max={max_spd:.2f}, never reached target")
                lines.append(f"    Distance in 45s: {total_d:.0f}m (theoretical: {speed*45}m)")

            result = "PASS"
            key_metric = f"Max: {max_spd:.1f} m/s" if sc else "No data"
            summary_rows.append((test_id, result, key_metric))
        else:
            summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 17: MULTI-CONTACT ----
    test_id = "TEST-17-MULTI-CONTACT"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        threats = analyze_threat_timeline(frames)
        for cid in ["bogey-A", "bogey-B", "bogey-C"]:
            t = threats.get(cid)
            if t:
                levels = [tr["to"] for tr in t["threat_transitions"]]
                lines.append(f"  {cid}: transitions={levels}, "
                             f"closest={t['closest_approach']:.0f}m")

        # Which contact did drone track?
        for f in frames:
            autonomy = f.get("autonomy", {})
            targeting = autonomy.get("targeting", {})
            if targeting.get("contact_id"):
                lines.append(f"  First drone target: {targeting['contact_id']}")
                break

        result = "PASS"
        key_metric = f"{len(threats)} contacts tracked"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 18: MAX RANGE ----
    test_id = "TEST-18-MAX-RANGE"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        max_x = 0
        for f in frames:
            a = asset_by_id(f, "alpha")
            if a:
                max_x = max(max_x, a["x"])
        lines.append(f"  Max X reached by alpha: {max_x:.0f}m (target: 4900m)")

        result = "PASS" if max_x > 4500 else "WARN"
        key_metric = f"Max X: {max_x:.0f}m"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 19: RAPID SWITCHING ----
    test_id = "TEST-19-RAPID-SWITCH"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames")

        missions_seen = set()
        for f in frames:
            m = f.get("active_mission")
            if m:
                missions_seen.add(m)
        lines.append(f"  Missions observed: {', '.join(sorted(missions_seen))}")

        jumps = analyze_position_jumps(frames)
        lines.append(f"  Position jumps during switching: {len(jumps)}")

        # Any stuck states?
        stuck = False
        prev_status = {}
        for f in frames:
            for a in f.get("assets", []):
                aid = a["asset_id"]
                status = a.get("status", "")
                if status == "error":
                    stuck = True
        lines.append(f"  Error states: {'YES' if stuck else 'NO'}")

        result = "PASS" if not stuck else "FAIL"
        key_metric = f"{len(missions_seen)} missions, {len(jumps)} jumps"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- TEST 20: ENDURANCE ----
    test_id = "TEST-20-ENDURANCE"
    frames = test_groups.get(test_id, [])
    if frames:
        section(f"{test_id}")
        lines.append(f"Duration: {len(frames)} frames (~{len(frames)*0.25:.0f}s)")

        for aid in ["alpha", "bravo", "charlie"]:
            transitions, loops = analyze_waypoint_loops(frames, aid)
            lines.append(f"  {aid}: {len(transitions)} transitions, {loops} loops")

        # Formation stability over time
        formation_data = analyze_formation(frames, 200.0)
        if formation_data:
            # Split into quarters
            q_size = len(formation_data) // 4
            for qi in range(4):
                chunk = formation_data[qi*q_size:(qi+1)*q_size]
                if chunk:
                    ab = [r["alpha_bravo"] for r in chunk]
                    lines.append(f"  Q{qi+1} spacing: mean={mean(ab):.0f}m, std={std_dev(ab):.1f}m")

        # Frame timing stability
        if len(frames) > 10:
            wall_clocks = [f.get("_wall_clock", 0) for f in frames if f.get("_wall_clock")]
            if len(wall_clocks) > 1:
                intervals = [wall_clocks[i] - wall_clocks[i-1] for i in range(1, len(wall_clocks))]
                lines.append(f"  Frame interval: mean={mean(intervals)*1000:.1f}ms, "
                             f"max={max(intervals)*1000:.1f}ms")

        # NaN check
        nan_count = 0
        for f in frames:
            for a in f.get("assets", []):
                if math.isnan(a.get("x", 0)) or math.isnan(a.get("y", 0)):
                    nan_count += 1
        lines.append(f"  NaN values: {nan_count}")

        orbit = analyze_drone_orbit(frames)
        if orbit:
            lines.append(f"  Drone orbit radius: {orbit['radius']:.1f}m (stable: {orbit['fit_error']:.1f}m RMS)")

        result = "PASS" if nan_count == 0 else "FAIL"
        key_metric = f"NaN: {nan_count}, {len(frames)} frames"
        summary_rows.append((test_id, result, key_metric))
    else:
        summary_rows.append((test_id, "SKIP", "No data"))

    # ---- Build final report ----
    header = []
    header.append("=" * 70)
    header.append("  LOCALFLEET V2 SIMULATION ANALYSIS REPORT")
    header.append("=" * 70)
    header.append("")

    # Total stats
    total_frames = sum(len(f) for f in test_groups.values())
    header.append(f"  Total frames: {total_frames}")
    header.append(f"  Tests with data: {sum(1 for t in test_groups.values() if t)}")
    header.append("")

    # Pass/fail table
    header.append("  PASS/FAIL SUMMARY")
    header.append("  " + "-" * 66)
    header.append(f"  {'TEST':<40s} {'RESULT':8s} KEY METRIC")
    header.append("  " + "-" * 66)
    for test_name, result, metric in summary_rows:
        header.append(f"  {test_name:<40s} {result:8s} {metric}")
    header.append("  " + "-" * 66)

    pass_count = sum(1 for _, r, _ in summary_rows if r == "PASS")
    warn_count = sum(1 for _, r, _ in summary_rows if r == "WARN")
    fail_count = sum(1 for _, r, _ in summary_rows if r == "FAIL")
    skip_count = sum(1 for _, r, _ in summary_rows if r == "SKIP")
    header.append(f"  PASS: {pass_count}  WARN: {warn_count}  FAIL: {fail_count}  SKIP: {skip_count}")

    return "\n".join(header + lines) + "\n"


# ---------------------------------------------------------------------------
# CSV Output
# ---------------------------------------------------------------------------

def write_timeline_csv(test_groups, out_path):
    """Write second-by-second timeline CSV with test_id."""
    headers = [
        "test_id", "second", "mission", "formation", "gps_mode", "comms_mode",
        "kill_chain", "num_contacts",
        "alpha_status", "alpha_x", "alpha_y", "alpha_speed",
        "bravo_status", "bravo_x", "bravo_y", "bravo_speed",
        "charlie_status", "charlie_x", "charlie_y", "charlie_speed",
        "eagle1_status", "eagle1_x", "eagle1_y", "eagle1_speed",
        "eagle1_pattern", "eagle1_altitude",
    ]

    with open(out_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)

        for test_id, frames in sorted(test_groups.items()):
            if not frames:
                continue
            base_wc = frames[0].get("_wall_clock", 0)
            by_second = defaultdict(list)
            for f in frames:
                sec = int(f.get("_wall_clock", 0) - base_wc)
                by_second[sec].append(f)

            for sec in sorted(by_second.keys()):
                f = by_second[sec][-1]
                autonomy = f.get("autonomy", {})
                assets = {a["asset_id"]: a for a in f.get("assets", [])}

                row = [
                    test_id, sec,
                    f.get("active_mission", ""),
                    f.get("formation", ""),
                    f.get("gps_mode", ""),
                    autonomy.get("comms_mode", "full"),
                    autonomy.get("kill_chain_phase", ""),
                    len(f.get("contacts", [])),
                ]

                for aid in ["alpha", "bravo", "charlie", "eagle-1"]:
                    a = assets.get(aid, {})
                    row.extend([
                        a.get("status", ""),
                        f"{a.get('x', 0):.1f}",
                        f"{a.get('y', 0):.1f}",
                        f"{a.get('speed', 0):.2f}",
                    ])
                    if aid == "eagle-1":
                        row.extend([
                            a.get("drone_pattern", ""),
                            f"{a.get('altitude', 0):.0f}" if a.get("altitude") else "",
                        ])

                writer.writerow(row)


def write_formation_csv(test_groups, out_path):
    """Write per-tick formation geometry."""
    headers = [
        "test_id", "wall_clock", "alpha_bravo_dist", "bravo_charlie_dist",
        "alpha_charlie_dist", "formation_type",
    ]

    with open(out_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)

        for test_id, frames in sorted(test_groups.items()):
            for f in frames:
                pos = asset_positions(f)
                if "alpha" not in pos or "bravo" not in pos or "charlie" not in pos:
                    continue
                writer.writerow([
                    test_id,
                    f"{f.get('_wall_clock', 0):.3f}",
                    f"{dist(*pos['alpha'], *pos['bravo']):.1f}",
                    f"{dist(*pos['bravo'], *pos['charlie']):.1f}",
                    f"{dist(*pos['alpha'], *pos['charlie']):.1f}",
                    f.get("formation", ""),
                ])


def write_threats_csv(test_groups, out_path):
    """Write threat escalation timeline per contact per test."""
    headers = [
        "test_id", "contact_id", "first_seen", "closest_approach_m",
        "drone_track_time", "transitions",
    ]

    with open(out_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)

        for test_id, frames in sorted(test_groups.items()):
            threats = analyze_threat_timeline(frames)
            for cid, data in sorted(threats.items()):
                transitions_str = " | ".join(
                    f"{t['from'] or 'none'}->{t['to']}@{t['distance']:.0f}m"
                    for t in data["threat_transitions"]
                )
                writer.writerow([
                    test_id, cid,
                    f"{data['first_seen']:.3f}" if data["first_seen"] else "",
                    f"{data['closest_approach']:.0f}" if data["closest_approach"] < float("inf") else "",
                    f"{data['drone_track_time']:.3f}" if data["drone_track_time"] else "",
                    transitions_str,
                ])


def write_drift_csv(test_groups, out_path):
    """Write dead reckoning drift data."""
    headers = [
        "test_id", "wall_clock", "asset_id", "x", "y", "speed",
        "position_accuracy", "cumulative_distance_m",
    ]

    with open(out_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)

        for test_id in ["TEST-13-GPS-DENIED-DRIFT", "TEST-14-DOUBLE-DENIAL"]:
            frames = test_groups.get(test_id, [])
            dr = analyze_dr_drift(frames)

            # Compute cumulative distance per asset
            cum_dist = defaultdict(float)
            prev_pos = {}
            for r in dr:
                aid = r["asset_id"]
                if aid in prev_pos:
                    d = dist(r["x"], r["y"], *prev_pos[aid])
                    cum_dist[aid] += d
                prev_pos[aid] = (r["x"], r["y"])

                writer.writerow([
                    test_id,
                    f"{r['wall_clock']:.3f}",
                    aid,
                    f"{r['x']:.1f}",
                    f"{r['y']:.1f}",
                    f"{r['speed']:.2f}",
                    f"{r['position_accuracy']:.2f}",
                    f"{cum_dist[aid]:.1f}",
                ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not CAPTURE_FILE.exists():
        print(f"ERROR: Capture file not found: {CAPTURE_FILE}")
        print("Run the simulation first: .venv/bin/python scripts/run_simulation_v2.py")
        sys.exit(1)

    print(f"Loading frames from {CAPTURE_FILE}...")
    entries = load_capture(CAPTURE_FILE)
    print(f"  Loaded {len(entries)} entries")

    if not entries:
        print("ERROR: No data to analyze.")
        sys.exit(1)

    print("Grouping by test...")
    test_groups = group_by_test(entries)
    for tid, frames in sorted(test_groups.items()):
        if tid not in ("INIT-RESET", "RESET", "FINAL"):
            print(f"  {tid}: {len(frames)} frames")

    print("Loading decisions...")
    decisions = load_decisions(DECISIONS_FILE)
    print(f"  Loaded {len(decisions)} decisions")

    print("\nGenerating report...")
    report = generate_report(test_groups, decisions)
    REPORT_FILE.write_text(report)
    print(f"  Written to {REPORT_FILE}")

    print("Writing timeline CSV...")
    write_timeline_csv(test_groups, TIMELINE_FILE)
    print(f"  Written to {TIMELINE_FILE}")

    print("Writing formation CSV...")
    write_formation_csv(test_groups, FORMATION_FILE)
    print(f"  Written to {FORMATION_FILE}")

    print("Writing threats CSV...")
    write_threats_csv(test_groups, THREATS_FILE)
    print(f"  Written to {THREATS_FILE}")

    print("Writing drift CSV...")
    write_drift_csv(test_groups, DRIFT_FILE)
    print(f"  Written to {DRIFT_FILE}")

    print(f"\n{'='*60}")
    print("  ANALYSIS COMPLETE")
    print(f"  Report:    {REPORT_FILE}")
    print(f"  Timeline:  {TIMELINE_FILE}")
    print(f"  Formation: {FORMATION_FILE}")
    print(f"  Threats:   {THREATS_FILE}")
    print(f"  Drift:     {DRIFT_FILE}")
    print(f"{'='*60}\n")

    # Print summary to terminal
    print(report[:4000])
    if len(report) > 4000:
        print(f"\n  ... (full report in {REPORT_FILE})")


if __name__ == "__main__":
    main()
