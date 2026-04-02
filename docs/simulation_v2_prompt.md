# SIMULATION V2: Deep-Diagnostic LocalFleet Test Suite

## YOUR MISSION

You are building the next-generation simulation orchestrator for LocalFleet — a
multi-domain autonomous fleet system (3 surface vessels + 1 drone). The V1
simulation ran successfully and revealed real issues. Your job is to design and
build a V2 that goes **far deeper** — isolating each capability for clean
measurement, resetting to known state between tests, and probing the edge cases
and bugs that V1 exposed.

**You are writing code, not just planning.** Deliverables are at the bottom.

---

## WHAT YOU MUST UNDERSTAND FIRST

Before writing a single line, read and internalize these files:

1. **`CLAUDE.md`** — project rules, tech stack, architecture, absolute rules
2. **`docs/simulation_master_prompt.md`** — the V1 prompt (understand what was
   attempted and how the API works — all endpoint docs are in there)
3. **`scripts/run_simulation.py`** — V1 orchestrator (understand the pattern)
4. **`scripts/analyze_simulation.py`** — V1 analyzer (understand what it measured)
5. **`data/sim_report.txt`** — V1 results (understand what we found)
6. **`data/sim_capture.jsonl`** — raw V1 data (skim a few frames to understand
   the WebSocket payload structure)
7. **`src/schemas.py`** — source of truth for all types
8. **`src/api/ws.py`** — understand that the WS connection IS the simulation
   clock. Each connected client gets `step(0.25)` per message at 4Hz. If you
   disconnect, the sim stops.

---

## WHAT V1 FOUND (and what V2 must investigate deeper)

### Critical Findings

**1. 311 anomalies detected — mostly position jumps**
- Frame 2157: All 3 surface vessels jumped 300+ meters simultaneously. This is
  the moment GPS was restored after DENIED mode — the vessels snapped from DR
  estimated positions to true positions. This is NOT a bug per se, but it means
  the system has NO graceful GPS recovery. A real system would blend DR→GPS
  smoothly. We need to measure the exact magnitude of this snap for every vessel
  and understand if it causes downstream issues (waypoint recalculation, formation
  break, etc.).
- Frames 2993-3004: Sustained position jumps of 50-250m for all vessels. These
  are during GPS DEGRADED mode (50m noise). The 50m noise is showing up as
  actual position jumps in the state, meaning the noise is applied to the
  REPORTED position, not just the accuracy field. V2 must isolate: is this
  noise in display only, or does it affect navigation decisions?

**2. Eagle-1 stuck bug**
- Frames 1249-1529: eagle-1 was "executing" but stationary for 280 frames
  (~70 seconds). This was during the SEARCH phase. The drone had status
  "executing" and drone_pattern "sweep" but speed=0 and position didn't change.
  V2 must reproduce this — run SEARCH for longer, monitor drone position, and
  determine if the drone gets stuck at a sweep endpoint.

**3. Zero intercept replanning events**
- V1 logged 0 replan events despite running INTERCEPT for 120 seconds. The
  system claims to replan every 40 steps (10s) if the shift >100m. Either:
  (a) replanning fired but no decisions were logged, (b) the shift was always
  <100m so no replans triggered, or (c) replanning is broken. V2 must set up
  a scenario where replanning MUST fire (fast-moving contact changing direction).

**4. Decision log was dominated by auto_track (100) and threat_assessment (99)**
- Only 1 kill_chain_transition in the captured decisions. Missing entirely:
  intercept_solution, replan, comms_fallback, auto_engage. These either didn't
  fire or weren't captured by the GET endpoint. V2 must poll decisions more
  aggressively and at targeted moments.

**5. Escort never closed on target**
- escort-target closest approach was 973m. The fleet was dispatched to escort
  but never actually got close to the contact. Either the escort duration was
  too short (60s), or the escort-follow logic has issues. V2 must run escort
  for much longer and with the contact starting closer.

**6. bogey-1 never hit "detected" threat level**
- bogey-1 went straight from "none" to "warning" — skipped the "detected"
  (5000-8000m) range entirely. It was spawned at (4000, 2000) = ~4472m from
  origin, which is already inside WARNING range. V2 must spawn contacts at
  >8000m to capture the full none→detected→warning→critical escalation.

**7. Kill chain cycled rapidly at close range**
- Near bogey-2, the kill chain was cycling NONE→DETECT→TRACK→LOCK→ENGAGE→
  CONVERGE→NONE→DETECT... every ~0.25s. This looks like a reset-and-redetect
  loop. V2 must capture this more precisely and determine if it's expected
  behavior (reset after CONVERGE) or a bug (should hold at CONVERGE).

**8. comms_lost_behavior reverted to return_to_base**
- We set comms_lost_behavior to "continue_mission" via a command, then denied
  comms. But the autonomous actions show "AUTO-RTB: idle_during_denial, standing
  orders = return_to_base" — meaning the behavior reverted. V2 must test all 3
  standing orders explicitly and verify each one persists through comms denial.

**9. No LOITER orbit data was verified**
- V1 ran LOITER for 60s but never checked if vessels actually generated orbit
  waypoints or traced a circular path. V2 must compute the actual path geometry
  and compare to the expected 150m orbit radius.

**10. No formation geometry measured**
- V1 never measured actual inter-vessel distances during formation movement.
  V2 must compute spacing between vessels at every tick during each formation
  type and compare to the commanded 200m spacing.

---

## V2 DESIGN PHILOSOPHY

### Reset Between Every Test

The biggest lesson from V1: **tests bled into each other**. Vessels were still
mid-mission when the next phase started. Contacts from one phase affected the
next. GPS/comms state carried over in confusing ways.

V2 must implement a **reset cycle** between every test:

```
RESET CYCLE:
1. Remove all contacts (GET /api/contacts, DELETE each)
2. Restore GPS to FULL (POST /api/gps-mode {"mode": "full"})
3. Restore comms to FULL (POST /api/comms-mode {"mode": "full"})
4. Issue RTB (POST /api/return-to-base)
5. Wait for ALL 4 assets to reach "idle" status (poll via WS frames)
6. Verify all assets are within 50m of home positions
7. Snapshot fleet state — this is the test's BASELINE
8. Proceed to next test
```

This means V2 will take longer. That's fine. **Clean data > fast data.**

The reset wait should have a timeout (120s max) — if assets don't reach home,
log the failure and force-proceed (the stuck state itself is diagnostic data).

### One Capability Per Test

V1 tried to chain a narrative. V2 tests capabilities in isolation:

- **TEST-PATROL**: Only patrol. Measure formation, waypoint looping, drone orbit.
- **TEST-SEARCH**: Only search. Measure zigzag geometry, drone sweep, coverage.
- **TEST-INTERCEPT**: Only intercept. Precise kill chain timing.
- ...etc.

Then run **combination tests** that stress multiple systems:
- **TEST-COMMS-DENIED-PATROL**: Patrol + comms denial
- **TEST-GPS-DENIED-INTERCEPT**: Intercept under dead reckoning
- ...etc.

### Measure Everything Precisely

V1 captured raw frames but did basic analysis. V2's analyzer must compute:

- **Formation error**: At each tick, compute actual inter-vessel distances vs
  commanded spacing. Report mean, max, and std dev per formation type.
- **Path geometry**: For patrol, compute if vessels actually loop back. For
  search, compute the zigzag angle and line spacing. For loiter, fit a circle
  to the orbit path and report center + radius vs commanded.
- **Timing chains**: For every threat interaction, build a timeline:
  spawn_time → first_detected → first_warning → first_critical →
  drone_track_start → intercept_dispatch → first_lock → first_engage →
  first_converge → contact_removed. Report each delta.
- **DR drift rate**: Compute meters of drift per meter of travel (not per
  second — drift is distance-dependent). Compare to the expected 0.5%.
- **Intercept accuracy**: Record where the fleet was aiming (predicted intercept
  point from decisions) vs where the fleet actually converged on the contact.
  Report the delta in meters.

---

## V2 TEST SUITE

### Test 0: BASELINE HEALTH CHECK
- Verify backend is running
- Verify all 4 assets at home, IDLE
- Verify WebSocket is streaming
- Record starting fleet state
- **Duration**: 10s
- **Pass criteria**: All assets IDLE at home positions

### Test 1: PATROL — Waypoint Loop + Echelon Formation
- Dispatch PATROL to [(1500, 1000), (1500, -500), (0, 0)] at 7 m/s, ECHELON
- Run for **180s** (3 minutes — enough for vessels to complete 1+ full loops)
- **Measure**:
  - Did each vessel visit all 3 waypoints? (waypoint_index transitions)
  - Did vessels loop back to waypoint 0 after reaching waypoint 2?
  - Echelon spacing: actual distance between alpha-bravo and bravo-charlie
    at every tick, compared to 200m commanded
  - Drone: did eagle-1 trace an orbit? Compute orbit radius from positions
    and compare to 150m expected. Compute orbit center vs fleet centroid.
  - Time to form echelon from start
- **RESET** after test

### Test 2: SEARCH — Zigzag Pattern + Line Abreast
- Dispatch SEARCH to [(2000, 1000)] at 5 m/s, LINE_ABREAST
- Run for **150s**
- **Measure**:
  - Zigzag: compute heading changes over time. Count direction reversals.
    Measure sweep width (max lateral extent of zigzag).
  - Line abreast spacing: actual vs 200m commanded
  - Drone sweep: track eagle-1 path, compute sweep line spacing
  - Does the drone get stuck? (Monitor speed — flag if speed=0 for >5s while
    status=executing. This reproduced the V1 eagle-1 stuck bug.)
  - Did vessels loop the search pattern?
- **RESET** after test

### Test 3: ESCORT — Contact Following + Column Formation
- Spawn "escort-target" at **(500, 200)** heading East at 2 m/s (START CLOSE)
- Dispatch ESCORT to [(500, 200)] at 4 m/s, COLUMN
- Run for **120s** (2 minutes — target travels 240m, fleet should follow)
- **Measure**:
  - Distance from fleet centroid to escort-target at every tick
  - Does the fleet maintain column formation while following?
  - Do vessel waypoints update as the contact moves?
  - Time to first close approach (<300m)
  - Minimum distance achieved
  - Drone orbit around escort target
- Remove escort-target, **RESET** after test

### Test 4: LOITER — Orbit Generation + Spread Formation
- Dispatch LOITER to [(1000, 500)] at 5 m/s, SPREAD
- Run for **150s** (need time to arrive + orbit for several loops)
- **Measure**:
  - Time from dispatch to first orbit waypoint generation (when total_waypoints
    jumps from initial count to the orbit waypoint count)
  - Fit circle to each vessel's path during orbit phase. Report center, radius,
    and fitting error. Compare radius to 150m expected.
  - Spread formation spacing vs 1.5x line abreast (300m expected)
  - Drone orbit geometry
  - Number of complete orbit loops per vessel
- **RESET** after test

### Test 5: AERIAL_RECON — Drone Sweep + Surface Hold
- Dispatch AERIAL_RECON to [(2000, 2000)] at 5 m/s
- Run for **120s**
- **Measure**:
  - Surface vessels: are they holding ~500m south of (2000, 2000)?
    Compute distance from each vessel to (2000, 1500) over time.
  - Drone: is it doing SWEEP at 150m altitude? Track altitude over time.
    Compute sweep coverage area.
  - Are surface vessels stationary or moving? (Expected: hold position)
- **RESET** after test

### Test 6: FULL THREAT ESCALATION (contact at 9000m)
- Spawn "bogey-far" at **(7000, 5500)** heading SW at 2 m/s (range ~8900m)
- Do NOT dispatch any mission — just observe autonomous detection
- Run for **240s** (4 minutes — contact travels 480m, crosses all range bands)
- **Measure**:
  - Exact timestamp of each threat level transition:
    none → detected (8000m) → warning (5000m) → critical (2000m)
  - Distance at each transition (verify thresholds match spec)
  - Drone auto-track: when does it retask? At what threat level?
  - Does the system recommend intercept? At what point?
  - Full kill chain if it progresses: DETECT → TRACK timing
  - Is "detected" (5000-8000m) actually a threat level the system uses, or
    is it called something else? V1 never observed it.
- Remove bogey-far, **RESET** after test

### Test 7: INTERCEPT — Full Kill Chain with Forced Replanning
- Spawn "bogey-mover" at **(4000, 3000)** heading SW at 3 m/s
- Wait 5s for detection
- Dispatch INTERCEPT to [(4000, 3000)] at 8 m/s, ECHELON
- After 30s: change bogey-mover's heading — remove it and respawn at its
  current position with a NEW heading (heading North instead of SW). This forces
  a >100m shift in predicted intercept point.
- Run for **180s** total
- **Measure**:
  - Kill chain phases: exact timestamp of each transition
  - LOCK conditions: was range <3000m? Was drone in TRACK pattern?
  - CONVERGE trigger: was vessel <1000m?
  - Replan events: did new decisions appear after contact direction change?
    How many replans? What was the shift magnitude?
  - Intercept prediction accuracy: where did the fleet aim vs where the
    contact actually was when convergence happened?
  - Drone targeting: confidence curve over time, lock acquisition time
- Remove bogey-mover, **RESET** after test

### Test 8: COMMS DENIED — Standing Order: continue_mission
- Dispatch PATROL to [(1500, 1000), (1500, -500), (0, 0)] at 5 m/s
  with comms_lost_behavior="continue_mission"
- Wait 15s for patrol to establish
- Set comms to DENIED
- Run for **90s** in denied state
- **Measure**:
  - Do vessels continue patrol route? Track waypoint_index transitions
    while comms denied.
  - Does the drone maintain its pattern?
  - Are any autonomous actions logged?
  - What happens to the status field? Does it stay "executing"?
- Restore comms, **RESET** after test

### Test 9: COMMS DENIED — Standing Order: hold_position
- Dispatch PATROL to [(1500, 1000)] at 5 m/s
  with comms_lost_behavior="hold_position"
- Wait 30s for vessels to be mid-transit
- Set comms to DENIED
- Run for **60s**
- **Measure**:
  - Do vessels stop? Track speed over time after comms denial.
  - How long until speed reaches 0?
  - Do they drift or hold exact position?
  - Status field — does it change to something specific?
- Restore comms, **RESET** after test

### Test 10: COMMS DENIED — Standing Order: return_to_base
- Dispatch PATROL to [(2000, 1500)] at 5 m/s
  with comms_lost_behavior="return_to_base"
- Wait 30s for vessels to be far from home
- Set comms to DENIED
- Run for **120s**
- **Measure**:
  - Do vessels turn toward home? Track heading changes.
  - Status field — does it change to "returning"?
  - Do they reach home positions?
  - Time to RTB from denial onset
- Restore comms, **RESET** after test

### Test 11: COMMS DENIED — Auto-Engage Timer (60s threshold)
- Dispatch PATROL to [(1500, 1000)] at 5 m/s
  with comms_lost_behavior="continue_mission"
- Wait 10s
- Spawn "bogey-auto" at **(3000, 0)** heading NW at 4 m/s
- Wait 5s for threat detection
- Set comms to DENIED
- Record the exact timestamp of comms denial
- Run for **120s** (need 60s+ for auto-engage)
- **Measure**:
  - Exact time from comms denial to auto-engage action
  - Is it exactly 60s? Or is there variance?
  - What decision type is logged? "auto_engage"? "comms_fallback"?
  - Does the fleet actually execute the intercept?
  - Kill chain progression during autonomous engagement
  - What confidence value does the autonomous intercept decision have?
    (Expected: 0.7 per the spec)
- Remove bogey-auto, restore comms, **RESET** after test

### Test 12: GPS DEGRADED — Noise Characterization
- Dispatch PATROL to [(1500, 1000), (0, 0)] at 5 m/s
- Wait 15s for movement to establish
- Set GPS to DEGRADED with noise_meters=25
- Run for **60s** (capture noise at 25m)
- Set GPS to DEGRADED with noise_meters=50
- Run for **60s** (capture noise at 50m)
- Set GPS to DEGRADED with noise_meters=100
- Run for **60s** (capture noise at 100m)
- **Measure**:
  - Position jitter magnitude at each noise level: compute frame-to-frame
    position delta, subtract expected motion (speed × 0.25s), report the
    residual as noise.
  - Does the noise affect navigation? Do vessels deviate from patrol route
    more at higher noise? Compare waypoint arrival times across noise levels.
  - position_accuracy field: does it match noise_meters?
  - Does the noise appear in BOTH x and y, or just one axis?
- Restore GPS, **RESET** after test

### Test 13: GPS DENIED — Dead Reckoning Drift Curve
- Dispatch PATROL to [(2000, 0), (2000, 2000), (0, 2000), (0, 0)] at 5 m/s
  (a square patrol — known geometry, easy to measure drift)
- Wait 10s for movement
- Set GPS to DENIED
- Run for **180s** (3 minutes — expecting ~18m of drift at 5m/s)
- **Measure**:
  - DR drift vs distance traveled (not time). Compute cumulative distance
    from velocity, plot drift (position_accuracy) vs distance. Expected:
    0.5% of distance.
  - Does drift direction correlate with heading? (Systematic bias?)
  - What is position_accuracy at 30s, 60s, 90s, 120s, 150s, 180s?
  - Does the fleet deviate from the square patrol path visually?
    (Compare actual path to path of vessels with GPS FULL.)
- Restore GPS. **DO NOT RESET YET.**
- Record the position snap magnitude when GPS restores (DR→true delta).
- Now **RESET**.

### Test 14: GPS DENIED + COMMS DENIED — Double Denial Stress Test
- Dispatch PATROL to [(1500, 1000)] at 5 m/s
  with comms_lost_behavior="continue_mission"
- Wait 15s
- Spawn "bogey-stress" at **(3500, 1500)** heading SW at 3 m/s
- Wait 5s
- Set GPS to DENIED
- Wait 5s
- Set comms to DENIED
- Run for **120s**
- **Measure**:
  - Does autonomous behavior still work under DR?
  - Does the auto-engage fire at 60s?
  - Kill chain progression with degraded positions — does LOCK still work?
  - Drone targeting confidence — affected by GPS denial?
  - Total DR drift during autonomous intercept
- Restore both, remove contact, **RESET** after test

### Test 15: FORMATION COMPARISON — All 5 Types
For each formation in [echelon, line, column, spread, independent]:
- Dispatch PATROL to [(2000, 1000)] at 5 m/s with this formation
- Run for **60s**
- Record all vessel positions at every tick
- **RESET** after each

- **Measure (across all 5)**:
  - Actual inter-vessel geometry for each formation type
  - Compare to expected:
    - ECHELON: diagonal right+back, 200m spacing
    - LINE_ABREAST: side-by-side, 200m
    - COLUMN: single file, 200m
    - SPREAD: side-by-side, 300m (1.5x)
    - INDEPENDENT: no constraint (measure natural spacing)
  - Formation establishment time (time from dispatch to stable geometry)
  - Formation maintenance during turns

### Test 16: SPEED TESTS — Response Curve
For each speed in [2, 4, 6, 8, 10]:
- Dispatch PATROL to [(1500, 0)] at this speed, INDEPENDENT
- Run for **45s**
- **RESET** after each

- **Measure**:
  - Actual max speed achieved vs commanded
  - Time to reach commanded speed from standstill (acceleration curve)
  - Speed reduction during turns (30% at 180° per spec)
  - Distance traveled in 45s vs theoretical (speed × 45)

### Test 17: MULTI-CONTACT — Threat Prioritization
- Spawn 3 contacts simultaneously:
  - "bogey-A" at (6000, 3000) heading SW at 2 m/s (slow, far)
  - "bogey-B" at (3000, 1000) heading W at 5 m/s (fast, medium range)
  - "bogey-C" at (1500, -500) heading N at 3 m/s (close, flanking)
- Do NOT dispatch — observe autonomous behavior only
- Run for **60s**
- **Measure**:
  - Which contact does the drone track first?
  - Which contact gets intercept_recommended?
  - Do threat_assessments include all 3 contacts?
  - Kill chain: which contact triggers it?
  - Does the system handle multiple simultaneous threats correctly?
- Remove all contacts, **RESET** after test

### Test 18: EDGE CASE — Waypoint at Max Range (5000m)
- Dispatch PATROL to [(4900, 0)] at 8 m/s (just under 5000m limit)
- Run for **90s**
- **Measure**:
  - Does the vessel reach the waypoint?
  - Any clamping or errors?
  - Waypoint arrival time
- **RESET** after test

### Test 19: EDGE CASE — Rapid Mission Switching
- Dispatch PATROL at 5 m/s — wait 10s
- Dispatch SEARCH at 5 m/s — wait 10s
- Dispatch LOITER at 5 m/s — wait 10s
- Dispatch PATROL at 5 m/s — wait 10s
- Run 10s more after last dispatch
- **Measure**:
  - Do status transitions happen cleanly?
  - Any stuck states?
  - Do waypoints update correctly on each switch?
  - Any position jumps on mission switch?
- **RESET** after test

### Test 20: ENDURANCE — Long Patrol Stability
- Dispatch PATROL to [(2000, 1000), (2000, -1000), (-500, 0)] at 5 m/s, ECHELON
- Run for **300s** (5 minutes — longest single test)
- **Measure**:
  - Waypoint loop count per vessel
  - Formation stability over time — does spacing degrade?
  - Any status anomalies?
  - Drone orbit stability — radius drift over time?
  - Memory/performance: does frame rate degrade? (Measure inter-frame timing)
  - Any NaN values appearing over time?

---

## DATA CAPTURE STRATEGY

### WebSocket Capture
Same as V1: capture every frame to `data/sim_v2_capture.jsonl`. But ALSO:
- Add a `test_id` field to each line (e.g., `{"test": "TEST-01-PATROL", "frame": {...}}`)
  so the analyzer can split data by test without relying on timestamps.
- Record `wall_clock` (time.time()) alongside each frame for timing analysis.

### Per-Test Snapshots
Before and after each test (and after each reset):
- `GET /api/assets` — fleet state
- `GET /api/contacts` — contact state
- `GET /api/decisions?limit=200` — full decision log
- `GET /api/mission` — active mission

Save to `data/sim_v2_snapshots.jsonl` with test_id.

### Decision Capture
- Poll `GET /api/decisions?limit=50` every **5 seconds** during active tests
  (not just at phase transitions like V1).
- Deduplicate by decision ID.
- Save all unique decisions to `data/sim_v2_decisions.jsonl`.

### End-of-Run
- `GET /api/decisions?limit=1000`
- `GET /api/logs?limit=5000`
- `GET /api/logs/summary`
- Full fleet state

---

## ANALYSIS REQUIREMENTS

The V2 analyzer (`scripts/analyze_simulation_v2.py`) must produce:

### `data/sim_v2_report.txt` — Master Report

Organized by test, not by metric type. For each test:
```
=== TEST-01-PATROL ===
Duration: 180s (720 frames)
Pass/Fail: PASS (with notes)

FORMATION:
  Mean echelon spacing: 198.3m (target: 200m, error: 0.85%)
  Max spacing deviation: 47.2m at t=45s (during turn)
  Formation establishment time: 12.4s

WAYPOINT NAVIGATION:
  Alpha: visited WP0→WP1→WP2→WP0→WP1 (1.67 loops)
  Bravo: visited WP0→WP1→WP2→WP0 (1.0 loops)
  Patrol loop confirmed: YES

DRONE:
  Orbit radius (fitted): 143.7m (target: 150m, error: 4.2%)
  Orbit center offset from centroid: 23.1m
  Stuck periods: NONE

ANOMALIES: None
```

### `data/sim_v2_timeline.csv` — Second-by-Second State
Same as V1 but with `test_id` column.

### `data/sim_v2_formation.csv` — Formation Geometry
Per-tick: test_id, second, formation_type, alpha_bravo_dist, bravo_charlie_dist,
alpha_charlie_dist, commanded_spacing, mean_error

### `data/sim_v2_threats.csv` — Threat Escalation Timeline
Per-contact: test_id, contact_id, spawn_time, detected_time, warning_time,
critical_time, drone_track_time, intercept_dispatch_time, lock_time,
engage_time, converge_time, removed_time, closest_approach_m

### `data/sim_v2_drift.csv` — Dead Reckoning Drift Curve
Per-tick during GPS DENIED: test_id, second, asset_id, cumulative_distance_m,
position_accuracy_m, drift_rate_pct

### Pass/Fail Summary
At the top of the report, a table:
```
TEST                              RESULT    KEY METRIC
TEST-00-BASELINE                  PASS      All 4 assets IDLE at home
TEST-01-PATROL                    PASS      1.67 loops, echelon 198m
TEST-02-SEARCH                    WARN      Drone stuck for 12s
TEST-07-INTERCEPT-REPLAN          FAIL      0 replans (expected ≥2)
...
```

---

## CONSTRAINTS

- Use ONLY `requests` and `websocket-client` (both already installed in .venv)
- NO modifications to LocalFleet source code
- Backend must be started separately — the script connects to it
- All data files go in `data/` directory
- The analysis script works offline on captured data
- Print clear test markers: `=== TEST 7: INTERCEPT REPLAN (12:45) ===`
- Print key events in real time (threat transitions, kill chain, autonomous actions)
- The script must handle backend being already in an unknown state (always
  reset before first test)
- Total runtime estimate: ~45-60 minutes (longer is fine — clean data matters)

## IMPORTANT API NOTES (learned from V1)

- Contact headings are in **RADIANS** (math convention: 0=East, CCW+). Use
  `math.radians(90 - compass_deg)` to convert from compass.
- Formation "line_abreast" is sent as `"line"` in the JSON.
- The `/api/command-direct` endpoint bypasses the LLM — use this exclusively.
- GPS mode changes take effect on the next step().
- Comms DENIED blocks command-direct — set comms BEFORE you need to issue
  commands (or set them after).
- When comms are restored, any standing orders may trigger — watch for this.
- The WebSocket auto-sends state at 4Hz. You don't send messages to it, just
  receive. If you disconnect, the simulation stops — keep the connection alive
  for the entire run.
- You can remove a contact and respawn it at a new position/heading to simulate
  a direction change (contacts only move in straight lines).
- The drone auto-tracks threats at WARNING range (2000-5000m), not DETECTED.
- LOITER orbit generation only happens AFTER vessel arrival at the loiter point.
- Dead reckoning drift is 0.5% of **distance traveled**, not time. At 5m/s
  that's 0.025m/step.

## FILE DELIVERABLES

1. `scripts/run_simulation_v2.py` — orchestration + data capture
2. `scripts/analyze_simulation_v2.py` — offline analysis + report generation
3. All output files go in `data/` at runtime

## RUNNING

```bash
# Make sure backend is running first (in a separate terminal):
.venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000

# Run the V2 simulation:
.venv/bin/python scripts/run_simulation_v2.py

# After completion, run analysis:
.venv/bin/python scripts/analyze_simulation_v2.py
```
