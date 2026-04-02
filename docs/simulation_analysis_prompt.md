# FULL-SPECTRUM SIMULATION ANALYSIS: Data-Driven Improvement Plan

## YOUR MISSION

You are performing a comprehensive data analysis of LocalFleet — a multi-domain
autonomous fleet system (3 surface vessels + 1 drone). Two full simulation runs
have been completed (V1 and V2), producing thousands of frames of telemetry,
decisions, threat data, and formation geometry. Your job is to analyze ALL of
this data alongside the source code to produce a prioritized, actionable
improvement plan.

**You are analyzing data and reading code, then writing a detailed report.**
You are NOT modifying source code in this session.

---

## WHAT YOU MUST READ FIRST

### Simulation Data (Primary Sources)
1. **`data/sim_v2_report.txt`** — V2 master report with pass/fail per test
2. **`data/sim_v2_observer_notes.md`** — Human observer notes cross-referenced
   with telemetry (critical — contains visual observations the data can't capture)
3. **`data/sim_report.txt`** — V1 analysis report (baseline comparison)
4. **`data/sim_v2_timeline.csv`** — Second-by-second state for all 21 V2 tests
5. **`data/sim_v2_formation.csv`** — Per-tick inter-vessel distances (21K rows)
6. **`data/sim_v2_threats.csv`** — Threat escalation timeline per contact
7. **`data/sim_v2_drift.csv`** — Dead reckoning drift curves (3.6K rows)
8. **`data/sim_v2_decisions.jsonl`** — 2,656 unique decisions captured

### Project Context
9. **`CLAUDE.md`** — Project rules, architecture, absolute constraints
10. **`docs/localfleet_audit_plan.md`** — Full audit history (13 audits complete),
    blockers identified, dependency chains, known issues
11. **`docs/simulation_v2_prompt.md`** — V2 test design (what each test was
    trying to measure and why)
12. **`docs/simulation_master_prompt.md`** — V1 design (what was attempted)

### Source Code (Read to diagnose root causes)
13. **`src/fleet/formations.py`** — Formation offset calculations
14. **`src/fleet/fleet_manager.py`** — Core simulation step loop
15. **`src/fleet/fleet_commander.py`** — Command dispatch + comms handling
16. **`src/fleet/drone_coordinator.py`** — Drone pattern generation
17. **`src/dynamics/drone_dynamics.py`** — Drone movement physics
18. **`src/navigation/planning.py`** — Waypoint navigation + patrol loops
19. **`src/utils/gps_denied.py`** — Dead reckoning implementation
20. **`src/decision_making/decision_making.py`** — Decision logging
21. **`src/schemas.py`** — Source of truth for all types (DO NOT suggest
    modifying this)

---

## WHAT THE SIMULATIONS FOUND

### V1 Results (Baseline — 14.6 min, 3468 frames)
- 311 anomalies detected (position jumps, stuck drone)
- All 6 mission types exercised, all 5 formations used
- Eagle-1 stuck for 280 frames during SEARCH sweep
- Zero intercept replanning events
- bogey-1 skipped "detected" threat level
- Kill chain cycled rapidly at close range
- comms_lost_behavior reverted to return_to_base
- Escort never closed on target (973m closest)
- No formation geometry measured
- No loiter orbit data verified

### V2 Results (90 min, 21401 frames, 21 isolated tests)
```
PASS/FAIL SUMMARY:
TEST-00-BASELINE                  PASS   All idle
TEST-01-PATROL                    WARN   0 loops, 100m echelon spacing (target: 200m)
TEST-02-SEARCH                    WARN   Eagle stuck 104s, 0 zigzag reversals
TEST-03-ESCORT                    PASS   18m closest (fixed from V1's 973m)
TEST-04-LOITER                    PASS   Orbit generated, 131m radius (target: 150m)
TEST-05-AERIAL-RECON              PASS   Drone at 150m altitude
TEST-06-THREAT-ESCALATION         PASS   "detected" level observed at 8000m
TEST-07-INTERCEPT-REPLAN          PASS   2 replans, full KC: TRACK→LOCK→ENGAGE
TEST-08-COMMS-CONTINUE            PASS   3 WP transitions during denial
TEST-09-COMMS-HOLD                WARN   Vessels did NOT stop (7.3 m/s mean)
TEST-10-COMMS-RTB                 WARN   No RTB action, no autonomous actions
TEST-11-COMMS-AUTOENGAGE          PASS   AUTO-INTERCEPT at 60s
TEST-12-GPS-DEGRADED              PASS   Noise scales: 25→46m, 50→89m, 100→168m
TEST-13-GPS-DENIED-DRIFT          PASS   1.5% drift rate (spec: 0.5%), 80-87m snap
TEST-14-DOUBLE-DENIAL             PASS   Autonomous intercept under GPS+comms denied
TEST-15-FORMATION (5 types)       PASS*  Echelon=67m, Line=53m, Column=210m, Spread=180m
TEST-16-SPEED (5 speeds)          PASS   2→4.4, 4→4.7, 6→5.7, 8→7.5, 10→9.3 m/s actual
TEST-17-MULTI-CONTACT             PASS   Drone targeted closest threat (bogey-C)
TEST-18-MAX-RANGE                 WARN   Alpha reached 2115m of 4900m in 90s
TEST-19-RAPID-SWITCH              PASS   0 position jumps, 0 errors
TEST-20-ENDURANCE                 PASS   0 NaN, stable 254ms frame interval
```

### Human Observer Notes (Key Visual Observations)
- "Formations look funky" — echelon looks like single file because spacing is
  half the commanded distance
- "Boats run into each other" — seen in V1, likely caused by too-tight spacing
- "Eagle paused" — confirmed 104s stuck during sweep
- "They didn't really loop" — patrol visits waypoints once but doesn't cycle
- "Comms down but they kept going" — correct for continue_mission, but
  hold_position and return_to_base standing orders are completely broken
- "Intercept replan looked awesome" — full kill chain, direction change handled

---

## ANALYSIS REQUIREMENTS

### 1. Root Cause Analysis for Every Issue

For each problem found, you MUST:
- Read the relevant source code
- Identify the exact function/line where the behavior originates
- Explain WHY it behaves this way (not just WHAT is wrong)
- Propose a specific fix (file, function, what to change)

Issues to analyze (minimum):

**BROKEN FUNCTIONALITY (P0)**
- [ ] `hold_position` standing order does nothing (TEST-09)
- [ ] `return_to_base` standing order doesn't trigger RTB (TEST-10)

**BUGS (P1)**
- [ ] Eagle-1 sweep stuck bug — speed=0 while status=executing for 100+s (TEST-02)
- [ ] Echelon formation spacing 100m instead of 200m (TEST-01, TEST-15)
- [ ] Line abreast formation spacing 53m instead of 200m (TEST-15)
- [ ] Spread formation spacing 180m instead of 300m (TEST-15)

**INCORRECT BUT FUNCTIONAL (P2)**
- [ ] Loiter orbit radius 131m instead of 150m (TEST-04)
- [ ] No zigzag heading reversals in search pattern (TEST-02)
- [ ] Patrol doesn't loop back to waypoint 0 (TEST-01)
- [ ] DR drift rate 1.5% instead of spec'd 0.5% (TEST-13)
- [ ] GPS restore causes 80-87m position snap instead of smooth blend (TEST-13)
- [ ] Max speed never fully reached — 10 m/s commanded → 9.3 actual (TEST-16)
- [ ] Commanded speed 2 m/s → actual 4.4 m/s (can't go slow) (TEST-16)
- [ ] GPS noise jitter doubles the noise_meters setting (TEST-12)
- [ ] Kill chain doesn't progress past DETECT for distant contacts (TEST-06)

**DESIGN QUESTIONS**
- [ ] Why does the auto-engage timer appear to carry over from V1 sessions?
  (TEST-08 showed V1's autonomous actions in a fresh test)
- [ ] Why does TEST-18 (4900m waypoint) only reach 2115m in 90s at 8 m/s?
  (Expected: ~720m... wait, that's only 90s × 8 = 720m. Is this actually correct
  and the test just needs more time? Or is there a speed limiting issue?)
- [ ] Column formation (210m) is accurate but echelon (67m) is way off — are
  they using different offset math?

### 2. V1 vs V2 Comparison

Compare the same capabilities across both simulation runs:
- Which V1 issues did V2 confirm are real?
- Which V1 issues did V2 fix (e.g., escort close approach)?
- Which issues are NEW in V2 that V1 didn't test?
- What did V1 miss that V2 caught?

### 3. Formation Deep Dive

The formation data is the richest dataset (21K rows in `sim_v2_formation.csv`).

- For each formation type, compute: mean, median, std dev, min, max of
  alpha-bravo and bravo-charlie distances
- Plot (textually) how spacing evolves over time — does it converge?
- During turns, what happens to spacing?
- Compare the formation offset math in `formations.py` to what the data shows
- Read `formations.py` and identify if the offset calculation is using the
  wrong scale factor, wrong coordinate frame, or wrong reference point

### 4. Speed & Dynamics Analysis

Using the speed test data (TEST-16):
- What is the actual acceleration curve? Time from 0 to 90% of target?
- Why can't vessels go below ~4 m/s? Is there a minimum speed clamp?
- At max commanded speed (10), why only 9.3 achieved? Speed reduction from turns?
- How does the PID controller affect speed response? Read `controller.py`.

### 5. Drone Behavior Analysis

- Why does the sweep pattern get stuck? Read `drone_coordinator.py` and
  `drone_dynamics.py` to find the endpoint logic.
- Is the orbit radius being generated correctly? Compare `generate_orbit_waypoints()`
  output to the 131m measured radius.
- Does the drone track pattern actually follow moving contacts, or does it go
  to a single point and stop?

### 6. Comms-Denied Behavior Analysis

- Read `fleet_commander.py` to understand how comms_lost_behavior is stored
  and dispatched
- Read `fleet_manager.py` to find where the standing order check should happen
  during comms denial
- Why does `continue_mission` work but `hold_position` and `return_to_base` don't?
- Are the standing orders being checked in `step()` or only at command dispatch?

### 7. Navigation & Patrol Loop Analysis

- Read `planning.py` to understand how waypoint cycling works
- Why do vessels visit WP0→WP1→WP2 but not cycle back to WP0?
- Is there a loop flag or does patrol rely on modular waypoint indexing?
- The search pattern should zigzag — is the zigzag being generated in
  `planning.py` or is it expected to come from the waypoints themselves?

### 8. GPS/DR Analysis

Using `sim_v2_drift.csv`:
- Compute actual drift rate as percentage of distance traveled
- Compare to the 0.5% spec in `gps_denied.py`
- Read the DR implementation — is the 0.5% correctly applied per step?
- The GPS noise at 25m setting produces 46m jitter — is the noise being
  applied to BOTH x and y independently (which would give √2 × 25 ≈ 35m)?
  Or is there a different multiplier?

---

## DELIVERABLE

Write `data/sim_full_analysis.md` containing:

### Section 1: Executive Summary (1 page)
- Total capabilities tested, pass rate, critical findings
- Top 5 issues that would be most visible in a demo
- Overall system maturity assessment

### Section 2: Issue Registry (the main deliverable)
A table with columns:
| ID | Severity | Test | Issue | Root Cause File:Line | Fix Description | Effort |
Each issue gets one row. Sort by severity (P0 → P3).

### Section 3: Root Cause Deep Dives
For each P0 and P1 issue, a detailed section:
- What the test measured
- What the data shows (with specific numbers)
- What the code does (with file paths and line numbers)
- Why the code produces this behavior
- Exact fix proposed

### Section 4: V1 → V2 Delta Report
What improved, what regressed, what's new.

### Section 5: Formation Geometry Analysis
The full breakdown of all 5 formation types with statistics.

### Section 6: Recommended Audit 14+ Roadmap
Based on everything found, what should the next audits focus on?
Prioritized by: (1) demo impact, (2) fix difficulty, (3) system reliability.

### Section 7: Demo Readiness Assessment
If Johno were to record a demo video tomorrow for a defense tech CEO:
- What works well enough to show?
- What must be fixed first?
- What should be avoided in the demo?
- Suggested demo script that plays to strengths

---

## CONSTRAINTS

- DO NOT modify any source code — this is analysis only
- Read source files to understand root causes, not to fix them
- Reference specific file paths and line numbers in all findings
- Use actual numbers from the data, not approximations
- The analysis must be reproducible — someone should be able to verify
  every claim by reading the referenced data file and line
- `src/schemas.py` is immutable — never suggest schema changes
- Total output should be thorough — 3000+ words expected
- Focus on actionable findings, not theoretical improvements

## RUNNING

```bash
# This prompt is designed for a Claude Code session.
# All data files are already in data/ — no simulation needed.
# Just read and analyze.
```
