#!/usr/bin/env python3
"""
LocalFleet Simulation Data Analyzer

Reads captured data from data/sim_capture.jsonl and produces:
  - data/sim_report.txt  — human-readable metrics summary
  - data/sim_timeline.csv — second-by-second state timeline

Usage:
    .venv/bin/python scripts/analyze_simulation.py
"""

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CAPTURE_FILE = DATA_DIR / "sim_capture.jsonl"
DECISIONS_FILE = DATA_DIR / "sim_decisions.jsonl"
REPORT_FILE = DATA_DIR / "sim_report.txt"
TIMELINE_FILE = DATA_DIR / "sim_timeline.csv"

# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_frames(path: Path) -> list[dict]:
    """Load all JSON frames from a JSONL file."""
    frames = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    frames.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return frames


def load_decisions(path: Path) -> list[dict]:
    """Load decisions from the decisions JSONL file."""
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
                if "decisions" in data:
                    decisions.extend(data["decisions"])
                else:
                    decisions.append(data)
            except json.JSONDecodeError:
                continue
    return decisions


# ---------------------------------------------------------------------------
# Per-Asset Metrics
# ---------------------------------------------------------------------------

def compute_asset_metrics(frames: list[dict]) -> dict:
    """Compute per-asset metrics from captured frames."""
    assets_data = defaultdict(lambda: {
        "positions": [],
        "speeds": [],
        "statuses": [],
        "waypoint_indices": [],
        "total_waypoints": [],
        "accuracies": [],
        "gps_modes": [],
        "drone_patterns": [],
        "headings": [],
    })

    for frame in frames:
        ts = frame.get("timestamp", 0)
        for asset in frame.get("assets", []):
            aid = asset["asset_id"]
            d = assets_data[aid]
            d["positions"].append((ts, asset.get("x", 0), asset.get("y", 0)))
            d["speeds"].append(asset.get("speed", 0))
            d["statuses"].append(asset.get("status", "unknown"))
            d["waypoint_indices"].append(asset.get("current_waypoint_index", 0))
            d["total_waypoints"].append(asset.get("total_waypoints", 0))
            d["accuracies"].append(asset.get("position_accuracy", 1.0))
            d["gps_modes"].append(asset.get("gps_mode", "full"))
            d["drone_patterns"].append(asset.get("drone_pattern"))
            d["headings"].append(asset.get("heading", 0))

    results = {}
    for aid, d in assets_data.items():
        positions = d["positions"]

        # Total distance traveled
        total_dist = 0
        for i in range(1, len(positions)):
            dx = positions[i][1] - positions[i-1][1]
            dy = positions[i][2] - positions[i-1][2]
            total_dist += math.sqrt(dx*dx + dy*dy)

        # Max speed
        max_speed = max(d["speeds"]) if d["speeds"] else 0

        # Time in each status (approximate: each frame = 0.25s)
        status_time = Counter(d["statuses"])
        status_seconds = {k: v * 0.25 for k, v in status_time.items()}

        # Waypoint completions (count index changes)
        wp_changes = 0
        for i in range(1, len(d["waypoint_indices"])):
            if d["waypoint_indices"][i] != d["waypoint_indices"][i-1]:
                wp_changes += 1

        # Position accuracy stats
        max_accuracy_err = max(d["accuracies"]) if d["accuracies"] else 1.0
        denied_accuracies = [a for a, g in zip(d["accuracies"], d["gps_modes"])
                             if g == "denied" and a > 1.0]

        # DR drift curve: accuracies during DENIED periods with timestamps
        dr_drift = []
        denied_start = None
        for i, (ts, x, y) in enumerate(positions):
            if d["gps_modes"][i] == "denied":
                if denied_start is None:
                    denied_start = ts
                dr_drift.append((ts - denied_start, d["accuracies"][i]))
            else:
                denied_start = None

        results[aid] = {
            "total_distance_m": total_dist,
            "max_speed_ms": max_speed,
            "status_seconds": status_seconds,
            "waypoint_completions": wp_changes,
            "max_position_error_m": max_accuracy_err,
            "dr_drift_curve": dr_drift,  # (seconds_in_denied, accuracy_m)
            "frame_count": len(positions),
        }

    return results


# ---------------------------------------------------------------------------
# Per-Contact Metrics
# ---------------------------------------------------------------------------

def compute_contact_metrics(frames: list[dict]) -> dict:
    """Compute per-contact metrics from captured frames."""
    contacts_data = defaultdict(lambda: {
        "first_seen": None,
        "last_seen": None,
        "positions": [],
        "threat_levels": [],
        "threat_times": defaultdict(float),
        "first_drone_track": None,
        "closest_vessel_dist": float("inf"),
    })

    for frame in frames:
        ts = frame.get("timestamp", 0)
        contacts = frame.get("contacts", [])
        threats = frame.get("threat_assessments", [])

        for c in contacts:
            cid = c["contact_id"]
            cd = contacts_data[cid]
            if cd["first_seen"] is None:
                cd["first_seen"] = ts
            cd["last_seen"] = ts
            cd["positions"].append((ts, c.get("x", 0), c.get("y", 0)))

        # Threat levels
        for t in threats:
            cid = t.get("contact_id", "")
            if cid in contacts_data:
                level = t.get("threat_level", "none")
                contacts_data[cid]["threat_levels"].append((ts, level))
                contacts_data[cid]["threat_times"][level] += 0.25

        # Check if drone is tracking
        for a in frame.get("assets", []):
            if a["asset_id"] == "eagle-1" and a.get("drone_pattern") == "track":
                # The drone is tracking — check which contact
                autonomy = frame.get("autonomy", {})
                targeting = autonomy.get("targeting", {})
                target_cid = targeting.get("contact_id", "")
                if target_cid in contacts_data:
                    cd = contacts_data[target_cid]
                    if cd["first_drone_track"] is None:
                        cd["first_drone_track"] = ts

        # Closest vessel approach to contacts
        for c in contacts:
            cid = c["contact_id"]
            cx, cy = c.get("x", 0), c.get("y", 0)
            for a in frame.get("assets", []):
                if a.get("domain") == "surface":
                    dist = math.sqrt((a["x"] - cx)**2 + (a["y"] - cy)**2)
                    if dist < contacts_data[cid]["closest_vessel_dist"]:
                        contacts_data[cid]["closest_vessel_dist"] = dist

    results = {}
    for cid, cd in contacts_data.items():
        positions = cd["positions"]
        total_dist = 0
        for i in range(1, len(positions)):
            dx = positions[i][1] - positions[i-1][1]
            dy = positions[i][2] - positions[i-1][2]
            total_dist += math.sqrt(dx*dx + dy*dy)

        time_alive = (cd["last_seen"] - cd["first_seen"]) if cd["first_seen"] and cd["last_seen"] else 0

        # Time to first drone track response
        time_to_track = None
        if cd["first_drone_track"] and cd["first_seen"]:
            time_to_track = cd["first_drone_track"] - cd["first_seen"]

        results[cid] = {
            "time_alive_s": time_alive,
            "distance_traveled_m": total_dist,
            "threat_time_by_level": dict(cd["threat_times"]),
            "time_to_drone_track_s": time_to_track,
            "closest_vessel_approach_m": cd["closest_vessel_dist"]
                if cd["closest_vessel_dist"] < float("inf") else None,
        }

    return results


# ---------------------------------------------------------------------------
# Fleet-Level Metrics
# ---------------------------------------------------------------------------

def compute_fleet_metrics(frames: list[dict], decisions: list[dict]) -> dict:
    """Compute fleet-wide metrics."""
    mission_timeline = []
    formation_timeline = []
    gps_timeline = []
    comms_timeline = []
    kc_timeline = []

    for frame in frames:
        ts = frame.get("timestamp", 0)
        mission_timeline.append((ts, frame.get("active_mission")))
        formation_timeline.append((ts, frame.get("formation", "independent")))
        gps_timeline.append((ts, frame.get("gps_mode", "full")))

        autonomy = frame.get("autonomy", {})
        comms_timeline.append((ts, autonomy.get("comms_mode", "full")))
        kc_timeline.append((ts, autonomy.get("kill_chain_phase")))

    # Decision counts
    decision_counts = Counter()
    for d in decisions:
        decision_counts[d.get("type", "unknown")] += 1

    # Autonomous actions
    autonomous_actions = []
    prev_actions = set()
    for frame in frames:
        autonomy = frame.get("autonomy", {})
        actions = autonomy.get("autonomous_actions", [])
        for a in actions:
            if a not in prev_actions:
                autonomous_actions.append((frame.get("timestamp", 0), a))
                prev_actions.add(a)

    # Intercept replanning
    replan_count = 0
    for d in decisions:
        if d.get("type") == "replan":
            replan_count += 1

    # Unique mission types used
    missions_used = set(m for _, m in mission_timeline if m)

    # Unique formations used
    formations_used = set(f for _, f in formation_timeline if f)

    return {
        "total_frames": len(frames),
        "duration_s": (frames[-1].get("timestamp", 0) - frames[0].get("timestamp", 0))
            if len(frames) > 1 else 0,
        "missions_used": sorted(missions_used),
        "formations_used": sorted(formations_used),
        "decision_counts": dict(decision_counts),
        "total_decisions": len(decisions),
        "autonomous_actions": autonomous_actions,
        "replan_count": replan_count,
        "mission_timeline": mission_timeline,
        "formation_timeline": formation_timeline,
        "gps_timeline": gps_timeline,
        "comms_timeline": comms_timeline,
        "kc_timeline": kc_timeline,
    }


# ---------------------------------------------------------------------------
# Edge Case / Bug Detection
# ---------------------------------------------------------------------------

def detect_anomalies(frames: list[dict]) -> list[str]:
    """Look for NaN values, stuck assets, anomalous jumps, etc."""
    issues = []

    prev_positions = {}
    stuck_counts = defaultdict(int)

    for i, frame in enumerate(frames):
        for a in frame.get("assets", []):
            aid = a["asset_id"]
            x, y = a.get("x", 0), a.get("y", 0)
            speed = a.get("speed", 0)

            # NaN check
            if math.isnan(x) or math.isnan(y) or math.isnan(speed):
                issues.append(f"Frame {i}: NaN detected for {aid} (x={x}, y={y}, speed={speed})")

            # Position jump check (>50m in one tick at max 10 m/s = 2.5m/tick)
            if aid in prev_positions:
                px, py = prev_positions[aid]
                jump = math.sqrt((x-px)**2 + (y-py)**2)
                if jump > 50 and a.get("domain") == "surface":
                    issues.append(f"Frame {i}: {aid} position jump of {jump:.1f}m")

            # Stuck check (executing but not moving)
            if a.get("status") == "executing" and aid in prev_positions:
                px, py = prev_positions[aid]
                if abs(x-px) < 0.001 and abs(y-py) < 0.001:
                    stuck_counts[aid] += 1
                else:
                    stuck_counts[aid] = 0
                if stuck_counts[aid] >= 20:  # 5 seconds stuck
                    issues.append(f"Frame {i}: {aid} appears stuck (executing but stationary for 5s)")
                    stuck_counts[aid] = 0  # Don't re-report every frame

            prev_positions[aid] = (x, y)

        # Check for zero-confidence decisions
        for d in frame.get("decisions", []):
            if d.get("confidence", 1) == 0:
                issues.append(f"Frame {i}: Decision with confidence=0: {d.get('type')}")

    return issues


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def write_report(asset_metrics, contact_metrics, fleet_metrics, anomalies, out_path):
    """Write human-readable report."""
    lines = []

    def section(title):
        lines.append("")
        lines.append("=" * 70)
        lines.append(f"  {title}")
        lines.append("=" * 70)
        lines.append("")

    def subsection(title):
        lines.append(f"\n--- {title} ---\n")

    lines.append("=" * 70)
    lines.append("  LOCALFLEET SIMULATION ANALYSIS REPORT")
    lines.append("=" * 70)
    lines.append(f"  Total frames: {fleet_metrics['total_frames']}")
    lines.append(f"  Duration: {fleet_metrics['duration_s']:.1f}s "
                 f"({fleet_metrics['duration_s']/60:.1f} min)")
    lines.append(f"  Effective frame rate: "
                 f"{fleet_metrics['total_frames']/max(fleet_metrics['duration_s'],1):.1f} Hz")

    # ---- Per-Asset ----
    section("PER-ASSET METRICS")
    for aid in sorted(asset_metrics.keys()):
        m = asset_metrics[aid]
        subsection(aid.upper())
        lines.append(f"  Total distance traveled: {m['total_distance_m']:.1f} m")
        lines.append(f"  Max speed achieved:      {m['max_speed_ms']:.2f} m/s")
        lines.append(f"  Waypoint completions:    {m['waypoint_completions']}")
        lines.append(f"  Max position error:      {m['max_position_error_m']:.1f} m")
        lines.append(f"  Frames recorded:         {m['frame_count']}")
        lines.append(f"  Time by status:")
        for status, secs in sorted(m["status_seconds"].items()):
            lines.append(f"    {status:15s} {secs:7.1f}s")

        if m["dr_drift_curve"]:
            max_drift = max(acc for _, acc in m["dr_drift_curve"])
            lines.append(f"  Dead reckoning max drift: {max_drift:.1f} m")
            lines.append(f"  DR drift samples (sec, meters):")
            # Sample every 10s
            last_printed = -10
            for t, acc in m["dr_drift_curve"]:
                if t - last_printed >= 10:
                    lines.append(f"    t={t:6.1f}s  drift={acc:6.1f}m")
                    last_printed = t

    # ---- Per-Contact ----
    section("PER-CONTACT METRICS")
    if not contact_metrics:
        lines.append("  No contacts recorded.")
    for cid in sorted(contact_metrics.keys()):
        m = contact_metrics[cid]
        subsection(cid)
        lines.append(f"  Time alive:              {m['time_alive_s']:.1f}s")
        lines.append(f"  Distance traveled:       {m['distance_traveled_m']:.1f} m")
        lines.append(f"  Closest vessel approach: "
                     f"{m['closest_vessel_approach_m']:.1f} m" if m['closest_vessel_approach_m'] else "  N/A")
        if m["time_to_drone_track_s"] is not None:
            lines.append(f"  Time to drone track:     {m['time_to_drone_track_s']:.1f}s")
        else:
            lines.append(f"  Time to drone track:     N/A")
        lines.append(f"  Time at each threat level:")
        for level, secs in sorted(m["threat_time_by_level"].items()):
            lines.append(f"    {level:15s} {secs:7.1f}s")

    # ---- Fleet-Level ----
    section("FLEET-LEVEL METRICS")

    subsection("Mission Types Exercised")
    for m in fleet_metrics["missions_used"]:
        lines.append(f"  - {m}")

    subsection("Formation Types Exercised")
    for f in fleet_metrics["formations_used"]:
        lines.append(f"  - {f}")

    subsection("Decision Log")
    lines.append(f"  Total decisions:  {fleet_metrics['total_decisions']}")
    for dtype, count in sorted(fleet_metrics["decision_counts"].items()):
        lines.append(f"    {dtype:25s} {count:5d}")

    subsection("Intercept Replanning")
    lines.append(f"  Replan events: {fleet_metrics['replan_count']}")

    subsection("Autonomous Actions")
    if fleet_metrics["autonomous_actions"]:
        for ts, action in fleet_metrics["autonomous_actions"]:
            lines.append(f"  [{ts:.1f}] {action}")
    else:
        lines.append("  None recorded.")

    # ---- Anomalies ----
    section("ANOMALIES & EDGE CASES")
    if anomalies:
        for issue in anomalies[:50]:  # Cap at 50
            lines.append(f"  WARNING: {issue}")
        if len(anomalies) > 50:
            lines.append(f"  ... and {len(anomalies) - 50} more")
    else:
        lines.append("  No anomalies detected.")

    # ---- Analysis Questions ----
    section("ANALYSIS CHECKLIST")

    # Navigation accuracy
    subsection("1. Navigation Accuracy")
    for aid in sorted(asset_metrics.keys()):
        m = asset_metrics[aid]
        lines.append(f"  {aid}: {m['waypoint_completions']} waypoint transitions, "
                     f"{m['total_distance_m']:.0f}m traveled")

    # Mission behavior
    subsection("2. Mission Behavior Correctness")
    lines.append(f"  Missions exercised: {', '.join(fleet_metrics['missions_used'])}")
    expected = {"patrol", "search", "escort", "loiter", "aerial_recon", "intercept"}
    missing = expected - set(fleet_metrics["missions_used"])
    if missing:
        lines.append(f"  MISSING missions: {', '.join(missing)}")
    else:
        lines.append(f"  All 6 mission types exercised.")

    # Threat response
    subsection("3. Threat Response Timing")
    for cid, m in contact_metrics.items():
        lines.append(f"  {cid}:")
        if m["time_to_drone_track_s"] is not None:
            lines.append(f"    Drone track response: {m['time_to_drone_track_s']:.1f}s after spawn")
        for level in ["low", "medium", "high"]:
            t = m["threat_time_by_level"].get(level, 0)
            if t > 0:
                lines.append(f"    Time at {level}: {t:.1f}s")

    # Kill chain
    subsection("4. Kill Chain Integrity")
    kc_phases_seen = set()
    for _, phase in fleet_metrics["kc_timeline"]:
        if phase:
            kc_phases_seen.add(phase)
    lines.append(f"  Kill chain phases observed: {', '.join(sorted(kc_phases_seen)) or 'none'}")
    expected_kc = {"DETECT", "TRACK", "LOCK", "ENGAGE", "CONVERGE"}
    missing_kc = expected_kc - kc_phases_seen
    if missing_kc:
        lines.append(f"  MISSING kill chain phases: {', '.join(missing_kc)}")

    # GPS denied drift
    subsection("7. GPS Denied Drift")
    for aid in sorted(asset_metrics.keys()):
        m = asset_metrics[aid]
        if m["dr_drift_curve"]:
            max_drift = max(acc for _, acc in m["dr_drift_curve"])
            duration = m["dr_drift_curve"][-1][0] if m["dr_drift_curve"] else 0
            rate = max_drift / max(duration, 1) * 60  # m/min
            lines.append(f"  {aid}: max drift={max_drift:.1f}m over {duration:.0f}s "
                         f"(~{rate:.1f} m/min)")

    # Edge cases
    subsection("10. Edge Cases & Bugs")
    lines.append(f"  Total anomalies detected: {len(anomalies)}")

    # Write report
    report_text = "\n".join(lines) + "\n"
    out_path.write_text(report_text)
    return report_text


# ---------------------------------------------------------------------------
# Timeline CSV
# ---------------------------------------------------------------------------

def write_timeline(frames: list[dict], out_path: Path):
    """Write second-by-second timeline CSV."""
    if not frames:
        return

    base_ts = frames[0].get("timestamp", 0)

    # Bucket frames by second
    by_second = defaultdict(list)
    for f in frames:
        sec = int(f.get("timestamp", 0) - base_ts)
        by_second[sec].append(f)

    headers = [
        "second", "mission", "formation", "gps_mode", "comms_mode",
        "kill_chain", "threat_level", "num_contacts",
        "alpha_status", "alpha_x", "alpha_y", "alpha_speed",
        "bravo_status", "bravo_x", "bravo_y", "bravo_speed",
        "charlie_status", "charlie_x", "charlie_y", "charlie_speed",
        "eagle1_status", "eagle1_x", "eagle1_y", "eagle1_speed",
        "eagle1_pattern", "eagle1_altitude",
    ]

    with open(out_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)

        for sec in sorted(by_second.keys()):
            bucket = by_second[sec]
            # Use last frame in each second bucket
            f = bucket[-1]
            autonomy = f.get("autonomy", {})
            threats = f.get("threat_assessments", [])
            max_threat = max((t.get("threat_level", "none") for t in threats),
                             default="none",
                             key=lambda x: {"none": 0, "low": 1, "medium": 2, "high": 3}.get(x, 0))

            assets_by_id = {a["asset_id"]: a for a in f.get("assets", [])}

            row = [
                sec,
                f.get("active_mission", ""),
                f.get("formation", ""),
                f.get("gps_mode", ""),
                autonomy.get("comms_mode", "full"),
                autonomy.get("kill_chain_phase", ""),
                max_threat,
                len(f.get("contacts", [])),
            ]

            for aid in ["alpha", "bravo", "charlie", "eagle-1"]:
                a = assets_by_id.get(aid, {})
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not CAPTURE_FILE.exists():
        print(f"ERROR: Capture file not found: {CAPTURE_FILE}")
        print("Run the simulation first: .venv/bin/python scripts/run_simulation.py")
        sys.exit(1)

    print(f"Loading frames from {CAPTURE_FILE}...")
    frames = load_frames(CAPTURE_FILE)
    print(f"  Loaded {len(frames)} frames")

    if not frames:
        print("ERROR: No frames to analyze.")
        sys.exit(1)

    print("Loading decisions...")
    decisions = load_decisions(DECISIONS_FILE)
    print(f"  Loaded {len(decisions)} decisions")

    print("\nComputing per-asset metrics...")
    asset_metrics = compute_asset_metrics(frames)
    for aid, m in sorted(asset_metrics.items()):
        print(f"  {aid}: {m['total_distance_m']:.0f}m traveled, "
              f"max speed {m['max_speed_ms']:.1f} m/s")

    print("\nComputing per-contact metrics...")
    contact_metrics = compute_contact_metrics(frames)
    for cid, m in sorted(contact_metrics.items()):
        print(f"  {cid}: alive {m['time_alive_s']:.0f}s, "
              f"closest approach {m['closest_vessel_approach_m']:.0f}m"
              if m['closest_vessel_approach_m'] else f"  {cid}: no approach data")

    print("\nComputing fleet-level metrics...")
    fleet_metrics = compute_fleet_metrics(frames, decisions)
    print(f"  Duration: {fleet_metrics['duration_s']:.0f}s")
    print(f"  Missions: {', '.join(fleet_metrics['missions_used'])}")
    print(f"  Decisions: {fleet_metrics['total_decisions']}")

    print("\nDetecting anomalies...")
    anomalies = detect_anomalies(frames)
    print(f"  Found {len(anomalies)} anomalies")

    print(f"\nWriting report to {REPORT_FILE}...")
    report = write_report(asset_metrics, contact_metrics, fleet_metrics, anomalies, REPORT_FILE)

    print(f"Writing timeline to {TIMELINE_FILE}...")
    write_timeline(frames, TIMELINE_FILE)

    print(f"\n{'='*60}")
    print("  ANALYSIS COMPLETE")
    print(f"  Report: {REPORT_FILE}")
    print(f"  Timeline: {TIMELINE_FILE}")
    print(f"{'='*60}\n")

    # Print summary to terminal
    print(report[:3000])
    if len(report) > 3000:
        print(f"\n  ... (full report in {REPORT_FILE})")


if __name__ == "__main__":
    main()
