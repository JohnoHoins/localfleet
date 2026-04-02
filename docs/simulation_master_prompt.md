# THE SIMULATION: Full-Spectrum LocalFleet Demonstration & Data Capture

## CONTEXT FOR THE PLANNER

You are planning a single, continuous, live simulation of LocalFleet — a
multi-domain autonomous fleet system (3 surface vessels + 1 drone) operating
off Cape Cod. The operator will be watching the React dashboard in real time.
The simulation will be driven by a Python orchestration script that issues
REST API calls on a timed schedule while the backend (FastAPI + WebSocket)
runs the physics at 4Hz.

The TWO goals, in order of priority:

1. **Collect every data point the system can produce** — position, heading,
   speed, waypoint progress, GPS accuracy, dead reckoning drift, threat
   assessments, kill chain phases, decision log entries, autonomous actions,
   drone sensor confidence, formation offsets, contact motion, closing rates,
   intercept predictions, replanning events, comms state transitions — ALL
   of it, timestamped, logged to files that can be analyzed after.

2. **Showcase every capability in a coherent tactical narrative** — not a
   random feature checklist, but a story that flows: peaceful patrol →
   contact appears → threat escalates → drone tracks → fleet intercepts →
   comms go down → fleet acts autonomously → GPS denied → dead reckoning
   drift visible → comms restored → new mission → return to base. Every
   mission type, every formation, every GPS mode, every drone pattern, every
   kill chain phase, every autonomous behavior — exercised and recorded.

## WHAT THE SYSTEM CAN DO (use all of it)

### Assets
- 3 surface vessels: alpha (0,0), bravo (200,0), charlie (400,0)
- 1 drone: eagle-1 (200,-100), 15 m/s, altitude 10-500m
- Home positions above are also RTB targets

### 6 Mission Types (each with distinct behavior)
| Mission | Surface Behavior | Drone Behavior | Formation |
|---------|-----------------|----------------|-----------|
| PATROL | Loop waypoints continuously | ORBIT over centroid @ 100m | ECHELON |
| SEARCH | Zigzag lawnmower, loops | SWEEP pattern | LINE_ABREAST |
| ESCORT | Follow closest contact continuously | ORBIT @ 150m | COLUMN |
| LOITER | Arrive → generate 150m orbit, loop | ORBIT @ 100m | SPREAD |
| AERIAL_RECON | Hold 500m south of recon area | SWEEP @ 150m | INDEPENDENT |
| INTERCEPT | Navigate to predicted intercept point | TRACK target | any |

### 5 Formation Types
- ECHELON: diagonal right+back, 200m spacing
- LINE_ABREAST: side-by-side
- COLUMN: single file
- SPREAD: 1.5x line abreast
- INDEPENDENT: no formation constraint

### 4 Drone Patterns
- ORBIT: 9 waypoints (center + 8 perimeter), 150m radius default
- SWEEP: lawnmower raster, 100m line spacing
- TRACK: single offset waypoint following contact
- STATION: hold position

### GPS Modes
- FULL: true position, accuracy=1.0
- DEGRADED: Gaussian noise (configurable, default 25m)
- DENIED: dead reckoning, drift ~0.5%/distance, monotonic error growth

### Comms Modes
- FULL: all commands accepted
- DENIED: commands blocked, autonomous behavior activates
  - Standing orders: return_to_base / hold_position / continue_mission
  - Auto-engage: after 60s if critical threat + no operator

### Threat Detection Ranges
- >8000m: none
- 5000-8000m: detected (monitor)
- 2000-5000m: warning (auto-track drone)
- <2000m: critical (intercept recommended)

### Kill Chain Phases
DETECT → TRACK → LOCK → ENGAGE → CONVERGE → (reset)
- LOCK requires: drone TRACK pattern + range<3000m + target in FOV
- CONVERGE triggers when vessel <1000m from contact
- Resets when vessel <200m or contact removed

### Intercept Replanning
- Every 10s (40 steps), recompute predicted intercept point
- Only update if shift >100m from current waypoint
- Prefers drone targeting data (locked) over raw contact position

### Decision Log Types
intercept_solution, replan, threat_assessment, auto_track,
kill_chain_transition, comms_fallback, auto_engage

### API Endpoints Available
```
POST /api/command-direct  — structured FleetCommand (bypass LLM)
POST /api/contacts        — spawn contact {contact_id, x, y, heading, speed}
DELETE /api/contacts/{id} — remove contact
POST /api/gps-mode        — {mode, noise_meters}
POST /api/comms-mode      — {mode: "full"|"denied"}
POST /api/return-to-base  — all assets RTB
GET  /api/assets          — full FleetState snapshot
GET  /api/decisions       — decision audit trail (limit, type filters)
GET  /api/logs            — mission event log
GET  /api/logs/summary    — event count summary
GET  /api/contacts        — active contacts
GET  /api/mission         — active mission info
```

### WebSocket
- `ws://localhost:8000/ws` — FleetState dict at 4Hz
- Includes: assets, contacts, threat_assessments, decisions (last 10),
  autonomy state (comms, kill chain, targeting), GPS mode

### Key Physics Constants
- Vessel max speed: 10 m/s, min: 1 m/s
- Drone speed: 15 m/s constant
- Waypoint arrival: <27m (50/1852 nmi)
- Waypoint range limit: ±5000m
- Land avoidance look-ahead: 75m
- Speed reduction on hard turns: down to 30% at 180° error
- Operating area: 42.0°N, -70.0°W origin, Cape Cod polygon nearby

## SIMULATION DESIGN REQUIREMENTS

### Orchestration Script
Create `scripts/run_simulation.py` that:
- Assumes backend is already running at `http://localhost:8000`
- Uses `requests` for REST, `websocket-client` for WS data capture
- Runs the narrative on a **timed schedule** (real wall-clock seconds)
- Captures ALL WebSocket frames to `data/sim_capture.jsonl` (one JSON per line per tick)
- Captures all decision log entries to `data/sim_decisions.jsonl`
- Captures all mission log entries to `data/sim_mission_log.jsonl`
- Prints phase headers to terminal so operator knows what's happening
- Has a `PHASE_TIMING` dict at the top so durations are easy to tune
- Total runtime: ~8-12 minutes (adjustable)

### Data Capture Strategy
The WebSocket stream gives us 4 frames/second. For an 8-minute sim that's
~1920 frames. Each frame contains:
- 4 asset positions (x, y, heading, speed, altitude, status, waypoint progress, GPS accuracy)
- N contact positions (x, y, heading, speed)
- Threat assessments (distance, bearing, closing_rate, threat_level per contact)
- Autonomy state (comms_mode, kill_chain_phase, targeting lock/confidence)
- Last 10 decisions (type, action, rationale, confidence, assets)

The script should ALSO poll these endpoints at key moments:
- `GET /api/decisions?limit=200` — full decision trail at phase transitions
- `GET /api/logs/summary` — event counts at start and end
- `GET /api/assets` — snapshot before and after each phase
- `GET /api/contacts` — verify contact state

### Analysis Script
Create `scripts/analyze_simulation.py` that reads `data/sim_capture.jsonl` and produces:

**Per-asset metrics:**
- Total distance traveled (meters)
- Max speed achieved
- Time in each status (IDLE, EXECUTING, RETURNING, AVOIDING)
- Waypoint completion count
- Max lateral deviation from straight-line paths
- Position accuracy over time (GPS mode dependent)
- Dead reckoning drift curve (meters vs seconds in DENIED mode)

**Per-contact metrics:**
- Time alive (spawn to removal)
- Distance traveled
- Time at each threat level (none→detected→warning→critical)
- Time to first drone track response
- Time to intercept dispatch
- Closest approach by any vessel

**Fleet-level metrics:**
- Mission type timeline (what mission active at each second)
- Formation type timeline
- GPS mode timeline
- Comms mode timeline
- Kill chain phase timeline
- Total decisions logged, by type
- Autonomous actions count and timeline
- Intercept prediction accuracy (predicted point vs actual convergence point)
- Replanning count and shift magnitudes

**Output:**
- `data/sim_report.txt` — human-readable summary with all metrics
- `data/sim_timeline.csv` — second-by-second state (mission, formation, gps, comms, kill_chain, threat_level, asset_statuses)

## THE NARRATIVE (timed phase sequence)

Design the exact sequence. Here is the MINIMUM that must be covered — you
should expand, reorder, or add phases as needed for the most compelling and
data-rich demonstration:

### Phase 0: Baseline (0:00-0:30)
- Verify all 4 assets at home, IDLE
- Snapshot baseline fleet state
- Log starting conditions

### Phase 1: PATROL Mission (0:30-2:00)
- Dispatch PATROL to waypoint ~1500m northeast, ECHELON formation, 5 m/s
- Observe: vessels form echelon, drone orbits centroid
- Verify: vessels loop back to first waypoint (never go IDLE)
- Data: formation geometry, patrol path, drone orbit radius

### Phase 2: Contact Appears — Threat Escalation (2:00-3:00)
- Spawn contact "bogey-1" at (4000, 2000) heading southwest toward fleet at 3 m/s
- Watch threat level escalate: none → detected → warning → critical
- Observe: drone auto-retasks to TRACK bogey-1
- Data: threat distance curve, closing rate, drone retask timing, kill chain DETECT→TRACK

### Phase 3: INTERCEPT Mission — Full Kill Chain (3:00-5:00)
- Dispatch INTERCEPT, ECHELON formation, 8 m/s (max useful speed)
- Observe: predictive intercept point, fleet converges, replanning events
- Observe: kill chain TRACK → LOCK → ENGAGE → CONVERGE
- Observe: drone targeting lock, confidence increasing
- Data: intercept prediction accuracy, replanning shifts, convergence distance, time-to-intercept
- Remove bogey-1 when vessel gets within 300m (simulating neutralization)

### Phase 4: SEARCH Mission — Post-Contact Area Sweep (5:00-6:30)
- Dispatch SEARCH to area where bogey-1 was neutralized, LINE_ABREAST, 5 m/s
- Observe: zigzag lawnmower pattern, vessels in parallel sweeps
- Observe: drone SWEEP pattern over search area
- Data: search pattern geometry, coverage area, sweep spacing

### Phase 5: COMMS DENIED — Autonomous Operations (6:30-8:00)
- Set comms_lost_behavior to "continue_mission" first
- Set comms mode to DENIED
- Spawn contact "bogey-2" at (3000, -1000) heading north at 4 m/s (faster threat)
- Wait 60+ seconds for autonomous escalation
- Observe: threat detected, drone auto-tracks, intercept recommended
- After 60s: observe AUTO-INTERCEPT (autonomous engage without operator)
- Data: comms denial duration, autonomous action log, decision confidence (0.7 for auto-engage)

### Phase 6: GPS DENIED During Autonomous Intercept (8:00-9:00)
- Set GPS to DENIED while fleet is autonomously intercepting
- Observe: dead reckoning kicks in, position accuracy degrades
- Observe: fleet continues mission on DR estimates
- Data: drift error accumulation curve, true vs estimated positions

### Phase 7: COMMS + GPS RESTORED — Damage Assessment (9:00-9:30)
- Restore comms to FULL
- Restore GPS to FULL
- Remove bogey-2
- Snapshot: compare DR estimated positions to true positions (drift magnitude)
- Data: total drift accumulated, position error at restoration

### Phase 8: ESCORT Mission — Contact Following (9:30-10:30)
- Spawn friendly contact "escort-target" at (1000, 500) heading east at 2 m/s
- Dispatch ESCORT to follow escort-target, COLUMN formation, 4 m/s
- Observe: fleet follows moving contact, waypoints update continuously
- Data: escort tracking accuracy, formation maintenance during following

### Phase 9: LOITER Mission — Holding Pattern (10:30-11:30)
- Remove escort-target
- Dispatch LOITER at (2000, 1000), SPREAD formation, 5 m/s
- Observe: fleet arrives, generates orbit pattern, loops indefinitely
- Observe: drone holds orbit above loiter point
- Data: time to orbit generation, orbit geometry, loiter stability

### Phase 10: AERIAL_RECON — Drone-Primary Mission (11:30-12:30)
- Dispatch AERIAL_RECON at (1500, 1500), 5 m/s
- Observe: drone does SWEEP at 150m altitude, surface holds 500m south
- Data: drone sweep coverage, surface holding accuracy

### Phase 11: GPS DEGRADED Test (12:30-13:00)
- Set GPS to DEGRADED with noise_meters=50
- Observe: position jitter on dashboard, accuracy values in asset state
- Data: noise magnitude, position accuracy field values

### Phase 12: Return to Base (13:00-14:00)
- Restore GPS to FULL
- Issue return-to-base
- Observe: all assets navigate home
- Verify: all assets reach IDLE at home positions
- Data: RTB time, path efficiency, final positions vs home positions

### Phase 13: Final Data Dump (14:00-14:30)
- Poll all endpoints one final time
- GET /api/decisions?limit=500
- GET /api/logs?limit=1000
- GET /api/logs/summary
- GET /api/assets
- Close WebSocket capture
- Write final summary to terminal

## DATA POINTS TO CAPTURE (exhaustive checklist)

For every WebSocket frame (4Hz), record the full JSON. Then extract:

### Per-Tick (every 0.25s)
- [ ] timestamp
- [ ] Per asset: asset_id, domain, x, y, heading, speed, altitude, status, current_waypoint_index, total_waypoints, gps_mode, position_accuracy, drone_pattern
- [ ] Per contact: contact_id, x, y, heading, speed, domain
- [ ] active_mission, formation, gps_mode (fleet-level)
- [ ] Per threat: contact_id, distance, bearing_deg, closing_rate, threat_level, recommended_action, reason
- [ ] intercept_recommended, recommended_target
- [ ] autonomy.comms_mode, comms_denied_duration, comms_lost_behavior
- [ ] autonomy.kill_chain_phase, kill_chain_target
- [ ] autonomy.targeting.contact_id, bearing_deg, range_m, confidence, locked
- [ ] autonomy.autonomous_actions (list)
- [ ] decisions (last 10): id, type, action, rationale, confidence, assets

### Per-Phase Transition
- [ ] Full decision log dump (GET /api/decisions?limit=200)
- [ ] Fleet state snapshot (GET /api/assets)
- [ ] Contact state (GET /api/contacts)
- [ ] Mission state (GET /api/mission)

### End-of-Simulation
- [ ] Complete decision log (GET /api/decisions?limit=500)
- [ ] Complete mission log (GET /api/logs?limit=2000)
- [ ] Mission log summary (GET /api/logs/summary)
- [ ] Final fleet state
- [ ] Final contacts (should be empty)

## WHAT WE ARE LOOKING FOR (analysis priorities)

The simulation exists to find problems. After analyzing the captured data,
the report should specifically answer:

1. **Navigation accuracy**: Do vessels actually reach waypoints? What is the
   lateral deviation? Do they overshoot on turns? How tight are the turns?

2. **Mission behavior correctness**: Does PATROL actually loop? Does SEARCH
   actually zigzag? Does LOITER actually orbit? Does ESCORT actually follow
   the contact? Does AERIAL_RECON actually hold surface vessels south?

3. **Threat response timing**: How many seconds from contact spawn to
   detected? To warning? To critical? To drone track? To intercept dispatch?
   Is the timing reasonable?

4. **Kill chain integrity**: Does every phase transition happen? In order?
   Does LOCK actually require range<3000m? Does CONVERGE trigger at <1000m?
   Does it reset cleanly?

5. **Intercept accuracy**: How far is the predicted intercept point from
   where the fleet actually converges on the contact? Does replanning
   actually improve accuracy?

6. **Autonomous behavior**: Does comms-denied auto-engage actually fire
   after 60s? Does the fleet continue mission or RTB correctly based on
   standing orders? Are autonomous actions logged?

7. **GPS denied drift**: How much does DR drift accumulate per minute? Is
   the fleet still functional under DR? Does it deviate from the mission
   path? How far off are the estimated positions from true?

8. **Formation maintenance**: Do vessels maintain formation spacing during
   movement? During turns? During mission transitions?

9. **Drone patterns**: Does the drone actually trace an orbit? A sweep?
   Does TRACK keep the drone near the contact? What is the orbit radius
   in practice vs the 150m target?

10. **Edge cases and bugs**: Any NaN values? Any assets stuck? Any status
    that doesn't transition? Any waypoints that are never reached? Any
    contacts that aren't detected? Any decisions with confidence=0?
    Any anomalous position jumps?

## CONSTRAINTS

- The script must use ONLY `requests` and `websocket-client` (both pip-installable)
- No modifications to the LocalFleet source code
- The backend + dashboard must be started separately by the operator
- The script orchestrates via the REST API — it does NOT import LocalFleet modules
- All data files go in a `data/` directory (create if needed)
- The analysis script must work offline on the captured data files
- Print clear phase markers to terminal: "=== PHASE 3: INTERCEPT (3:00) ==="
- Print key events in real time: "bogey-1 now at WARNING range", "kill chain: TRACK → LOCK"
- The operator should be able to watch the dashboard AND the terminal simultaneously

## FILE DELIVERABLES

1. `scripts/run_simulation.py` — orchestration + data capture
2. `scripts/analyze_simulation.py` — offline analysis + report generation
3. `data/` directory created at runtime for output files

## IMPORTANT NOTES

- The WebSocket at `/ws` drives the simulation forward — each connection
  gets one `step(0.25)` per message. The orchestration script's WS
  connection IS the simulation clock. If you disconnect, the sim stops.
- Contact headings in the API are in RADIANS (math convention: 0=East, CCW+).
  A contact heading southwest is approximately `math.pi + math.pi/4` ≈ 3.93 rad.
  Convert from compass degrees to math radians: `math.radians(90 - compass_deg)`.
- The `/api/command-direct` endpoint accepts a raw FleetCommand JSON — use
  this instead of `/api/command` to avoid LLM dependency.
- GPS mode changes take effect immediately on the next step().
- Comms mode "denied" blocks `/api/command` and `/api/command-direct` — set
  comms mode BEFORE spawning contacts if you want the fleet to respond
  autonomously. Actually: spawn contacts FIRST, then deny comms, so the
  threat detector picks them up before the auto-engage timer starts.
- The drone auto-tracks on WARNING range (2000-5000m), not on DETECTED.
  Plan contact spawn positions and speeds so you hit each range band
  with enough dwell time to capture the data.
- INTERCEPT replanning happens every 40 steps (10s). Make sure the
  intercept phase runs long enough to see at least 2-3 replans.
- LOITER orbit generation happens only AFTER the vessel reaches its
  waypoint. The vessel must travel to the loiter point first, so give
  it close enough that arrival takes ~30-45s, not 5 minutes.
- Dead reckoning drift is 0.5% of distance traveled. At 5 m/s that is
  0.025 m/step = ~6m/minute. Run GPS DENIED for at least 60s to see
  meaningful drift (~6m). Longer is better.
