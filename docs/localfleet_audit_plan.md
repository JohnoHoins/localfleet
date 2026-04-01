# LocalFleet — Comprehensive Audit Plan for Claude Code

## Project Overview (Context for Every Prompt)

LocalFleet is a multi-domain (surface + air) naval fleet simulation with:
- **Backend**: Python/FastAPI at `src/`, WebSocket streaming at 4Hz
- **Frontend**: React/Vite dashboard at `dashboard/`
- **Physics**: CORALL-based vessel dynamics (surface), simple waypoint follower (drone)
- **AI**: Ollama LLM for NL command parsing + COLREGs decision-making
- **Architecture**: FleetCommander → FleetManager → vessel_dynamics/DroneAgent

Key files by subsystem:
- Navigation: `src/navigation/planning.py`, `src/navigation/reactive_avoidance.py`, `src/navigation/land_check.py`
- Dynamics: `src/dynamics/vessel_dynamics.py`, `src/dynamics/controller.py`, `src/dynamics/drone_dynamics.py`
- Fleet: `src/fleet/fleet_manager.py`, `src/fleet/fleet_commander.py`, `src/fleet/formations.py`
- LLM: `src/llm/ollama_client.py`, `src/decision_making/decision_making.py`
- GPS: `src/utils/gps_denied.py`
- Dashboard: `dashboard/src/components/FleetMap.jsx`, `dashboard/src/App.jsx`
- Schemas: `src/schemas.py`

---

## AUDIT 1: Navigation & Circling Bug
**Goal**: Find and fix why vessels go in endless circles.

```
AUDIT TASK: Fix the vessel circling/endless-loop navigation bug.

CONTEXT: Vessels are going in endless circles instead of reaching waypoints. 
The navigation pipeline is:

1. `src/navigation/planning.py` — `waypoint_selection()` decides when to advance 
   to next waypoint (threshold: 200/1852 nmi ≈ 108m). `planning()` computes 
   desired heading using cross-track error correction.

2. `src/navigation/reactive_avoidance.py` — `reactive_avoidance()` computes an 
   avoidance heading offset (psi_oa) using Gaussian bearing weights and Z-shaped 
   range membership functions.

3. `src/fleet/fleet_manager.py` — `FleetManager.step()` at line ~2663 calls 
   waypoint_selection, planning, then feeds psi_desired to the PID controller.

4. `src/dynamics/controller.py` — PID yaw controller with kp=100, kd=-500, ki=0.

5. `src/dynamics/vessel_dynamics.py` — First-order Nomoto-like dynamics with 
   Euler integration.

KNOWN ISSUES TO INVESTIGATE:

A) In `planning.py`, the `planning()` function uses cross-track error with 
   `rho = 2200/1852`. This look-ahead distance may be too large relative to 
   the waypoint acceptance circle (200/1852). Check if the vessel oscillates 
   around the path or overshoots waypoints.

B) In `fleet_manager.py` step(), when `i_wpt >= len(wpts_x)`, it sets 
   `i_wpt = len(wpts_x) - 1` and status to IDLE, BUT then continues to call 
   `planning()` with that same i_wpt. Check if this causes the vessel to keep 
   turning toward an already-reached waypoint.

C) The heading convention may be inconsistent: `vessel_dynamics.py` uses 
   mathematical convention (psi in radians, 0 = East, CCW positive), but 
   `fleet_manager.py` converts heading for display as `(90 - degrees(psi)) % 360` 
   (nautical: 0 = North). Verify that `planning()` output matches what 
   `controller()` expects.

D) The PID controller has kd = -500 (negative derivative gain). This is unusual 
   and could cause oscillation. Check if this creates a positive feedback loop 
   on yaw rate.

E) In `waypoint_selection()`, the for-loop iterates from i_wpt to end and can 
   increment i_wpt multiple times in one call if multiple waypoints are within 
   the threshold. This could skip waypoints unexpectedly.

F) The `planning()` function returns None when i_wpt == 0. In `fleet_manager.py`, 
   this is handled by falling back to current heading, but check edge cases where 
   i_wpt stays at 0.

DELIVERABLES:
1. Identify the root cause(s) of circular motion
2. Provide fixed code for each affected file
3. Add a simple test that verifies a vessel reaches a waypoint 1000m away 
   within a reasonable number of simulation steps
```

---

## AUDIT 2: Land Avoidance & Coastline Data
**Goal**: Add land/coastline awareness so vessels don't cross land.

```
AUDIT TASK: Implement land avoidance for surface vessels and harbor navigation.

CONTEXT: The system currently has ZERO land awareness. There is no coastline 
data, no geofencing, and no land collision checking anywhere in the codebase.

The dashboard uses OpenStreetMap tiles centered at:
- ORIGIN_LAT = 42.0, ORIGIN_LNG = -70.0 (off the coast of Massachusetts)
- Defined in `dashboard/src/components/FleetMap.jsx` lines 44-47

Vessel positions are in meters (local frame) converted to lat/lng for display.
The simulation runs in `src/fleet/fleet_manager.py` FleetManager.step().

The reactive avoidance in `src/navigation/reactive_avoidance.py` only avoids 
OTHER VESSELS (dynamic obstacles), not static terrain/land.

WHAT NEEDS TO HAPPEN:

1. **Coastline Data**: We need coastline polygon data for the operating area. 
   Options (recommend one and implement it):
   - Natural Earth 1:10m coastline (simple, ~5MB shapefile)
   - OpenStreetMap coastline extract for the local area
   - A simplified polygon manually defined for the demo area
   
2. **Land Check Function**: Create `src/navigation/land_check.py` with:
   - `is_on_land(x, y) -> bool` — point-in-polygon test
   - `nearest_water_point(x, y) -> (float, float)` — if on land, find closest water
   - `check_path_clear(x1, y1, x2, y2) -> bool` — line-segment vs coastline test
   
3. **Integration with FleetManager**: In `fleet_manager.py` step(), before 
   applying vessel dynamics, check if the next position would be on land. 
   If so, either:
   - Clamp to the coastline and redirect heading, OR
   - Add a strong repulsive force (like reactive_avoidance but for land)

4. **Harbor Navigation**: For the demo, vessels start near 42°N, -70°W. 
   If this is in a harbor or near shore, they need to be able to navigate 
   out through channels. Consider adding predefined safe waypoints or a 
   simple A* grid-based path planner for harbor exits.

5. **Dashboard Enhancement**: In `FleetMap.jsx`, optionally render the 
   coastline polygon as a Leaflet overlay so the operator can see the 
   no-go zones.

CONSTRAINTS:
- Keep it lightweight — this is a demo, not a full ENC system
- Shapely is already likely available via pip, or use a pure-numpy approach
- The solution must work with the existing meters-based coordinate system
- Don't break the existing reactive_avoidance (vessel-vessel) system

DELIVERABLES:
1. Recommended coastline data source + instructions to download
2. New `src/navigation/land_check.py` module
3. Modified `fleet_manager.py` with land avoidance integrated
4. Test that verifies a vessel heading toward land is redirected
```

---

## AUDIT 3: GPS Signal Loss & Dead Reckoning
**Goal**: Make GPS denied mode actually affect navigation, not just display.

```
AUDIT TASK: Fix GPS-denied mode so it affects actual navigation, not just display noise.

CONTEXT: The current GPS-denied implementation is COSMETIC ONLY. Here's what 
happens now:

1. `src/utils/gps_denied.py` — `degrade_position()` adds Gaussian noise to 
   reported positions. `should_update()` rate-limits updates. These functions 
   exist but are barely used.

2. `src/fleet/fleet_manager.py` — In `get_fleet_state()` (line ~2716), when 
   GPS is degraded, noise is added to the REPORTED position sent to the dashboard. 
   But the ACTUAL vessel state (`v["state"]`) used for navigation is UNAFFECTED.

3. `src/fleet/fleet_manager.py` — In `step()` (line ~2663), the navigation 
   pipeline reads from `v["state"]` directly with no GPS degradation applied. 
   This means vessels navigate perfectly even when "GPS denied" is toggled.

4. `src/schemas.py` — `GpsMode` has only FULL and DEGRADED (no DENIED state).

WHAT NEEDS TO CHANGE:

A) **True Dead Reckoning**: When GPS is degraded/denied, the vessel should:
   - Maintain a separate "estimated_position" that drifts from true position
   - Use heading + speed integration for position estimation (dead reckoning)
   - Accumulate drift error over time (maybe 1-2% of distance traveled)
   - Navigate using the estimated position, NOT the true position

B) **GPS Modes**: Add a DENIED mode to GpsMode enum:
   - FULL: perfect position, normal navigation
   - DEGRADED: noisy position (current behavior) + slight nav degradation
   - DENIED: pure dead reckoning, no GPS corrections, drift accumulates

C) **Signal Recovery**: When GPS is restored (DENIED → FULL):
   - Show the gap between estimated and true position on the dashboard
   - Smoothly correct (don't snap) — blend over ~5 seconds
   - Log the position error at recovery time

D) **Dashboard Indicator**: The `GpsDeniedToggle.jsx` component should show:
   - Current GPS mode
   - Accumulated position error (when in DEGRADED/DENIED)
   - Time since GPS was lost

E) **Demo Scenario**: When filming the demo, the flow should be:
   1. Start mission with GPS FULL — vessels navigate correctly
   2. Toggle to DENIED — vessels continue on dead reckoning
   3. Toggle back to FULL — show that vessels stayed roughly on course 
      (position error displayed), then smoothly correct

AFFECTED FILES:
- `src/schemas.py` — add DENIED to GpsMode
- `src/utils/gps_denied.py` — add dead reckoning logic
- `src/fleet/fleet_manager.py` — integrate DR into step() and state reporting
- `dashboard/src/components/GpsDeniedToggle.jsx` — enhance UI
- `src/api/routes.py` — may need to support DENIED mode

DELIVERABLES:
1. Modified schemas with DENIED mode
2. New dead reckoning engine in gps_denied.py
3. Modified fleet_manager.py that navigates on estimated position when denied
4. Test showing position drift accumulates when GPS denied, corrects on restore
```

---

## AUDIT 4: Mission Lifecycle & Multi-Vessel Coordination
**Goal**: Make intercept-and-return-to-base work end-to-end.

```
AUDIT TASK: Fix the complete mission lifecycle: command → execute → intercept → return to base.

CONTEXT: The demo needs to show:
1. Operator issues a mission command (NL text or voice)
2. Multiple vessels + drone execute in formation
3. Fleet intercepts a target entity
4. Fleet returns to base
5. All without hitting land, with proper formation

CURRENT STATE OF EACH COMPONENT:

A) **Command Parsing** (`src/llm/ollama_client.py`):
   - Uses Ollama (local LLM) to parse NL → FleetCommand
   - The parse_fleet_command() function exists but may produce hallucinated 
     waypoints or invalid asset IDs
   - Need to verify: does it handle "intercept target at position X,Y" correctly?
   - Need to verify: does it produce valid formation types?

B) **Fleet Commander** (`src/fleet/fleet_commander.py`):
   - Bridges NL → FleetManager. Looks correct structurally.
   - `return_to_base()` delegates to fleet_manager.return_to_base()

C) **Fleet Manager** (`src/fleet/fleet_manager.py`):
   - `dispatch_command()` handles formation offsets correctly for surface vessels
   - `return_to_base()` sends all vessels back to start positions
   - BUG: return_to_base uses home positions (0,0), (200,0), (400,0) — these 
     are the STARTING positions, not necessarily a safe base location
   - BUG: return_to_base doesn't check for land obstacles on the return path

D) **Formations** (`src/fleet/formations.py`):
   - Supports ECHELON, LINE_ABREAST, COLUMN, SPREAD
   - `apply_formation()` rotates offsets by heading — looks correct
   - BUT: formation is only applied at command dispatch time, not maintained 
     during transit. Vessels just go to their individual waypoints.

E) **Missing: INTERCEPT mission type**:
   - `src/schemas.py` MissionType has: PATROL, SEARCH, ESCORT, LOITER, AERIAL_RECON
   - There is NO "intercept" mission type
   - Need to add INTERCEPT to MissionType enum
   - Need corresponding behavior: track toward a moving target

F) **Missing: Target Entity**:
   - There's no concept of a "target" or "contact" in the fleet system
   - The CORALL simulation has obstacles (other vessels), but these are separate 
     from the fleet management layer
   - Need: a Contact model in schemas.py, tracking in fleet_manager.py

G) **Drone Coordination** (`src/fleet/drone_coordinator.py`):
   - Orbit, sweep, track, station patterns work
   - For intercept: drone should switch to TRACK pattern on the target

DELIVERABLES:
1. Add INTERCEPT mission type to schemas.py
2. Add Contact/Target model to schemas.py
3. Implement target tracking in fleet_manager.py
4. Fix return_to_base to use safe waypoints (not just straight line home)
5. Add formation maintenance during transit (not just initial positioning)
6. Test: issue intercept command → vessels converge on target → RTB
```

---

## AUDIT 5: Dashboard & Demo Readiness
**Goal**: Make the dashboard demo-video ready.

```
AUDIT TASK: Polish the dashboard for a compelling demo video.

CONTEXT: The dashboard is a React/Vite app using Leaflet for the map, 
connecting via WebSocket to the FastAPI backend. It currently shows vessel 
markers, trails, GPS status, and has a command panel + voice input.

CURRENT COMPONENTS:
- `FleetMap.jsx` — Leaflet map with vessel/drone markers, trails, GPS rings
- `AssetCard.jsx` — Status cards per asset (domain, speed, heading, GPS, etc.)
- `CommandPanel.jsx` — Text input + voice button for NL commands
- `GpsDeniedToggle.jsx` — Toggle for GPS degradation mode
- `MissionLog.jsx` — Event log showing status changes
- `App.jsx` — Layout: 70% map / 30% sidebar

ISSUES TO FIX FOR DEMO:

A) **Map Tiles**: Using OpenStreetMap standard tiles with a CSS dark filter 
   (`brightness(0.6) invert(1) contrast(3) hue-rotate(200deg)`). This works 
   but land/water distinction is poor after the filter. Consider:
   - Using CartoDB dark_all or Stamen toner tiles (natively dark)
   - Or adjusting the filter to better show coastlines

B) **Missing Components** from screenshot: The original project had 
   `MissionStatus.jsx`, `HeaderBar.jsx`, `ScenarioButton.jsx`, `RTBButton.jsx` 
   in the dashboard/src/components/ directory but they're NOT imported in App.jsx.
   - `RTBButton.jsx` — Return to Base button. MUST be visible for the demo.
   - `ScenarioButton.jsx` — Pre-built scenario launcher. Useful for demo.
   - Check if these components exist and wire them into App.jsx.

C) **No Target/Contact Display**: If we add intercept capability (Audit 4), 
   the map needs to show the target entity with a distinct marker (red?).

D) **Formation Visualization**: No visual indication of formation type. 
   Add dashed lines between vessels when in formation, or a formation label.

E) **Mission Status Display**: The `active_mission` from FleetState is available 
   but may not be prominently displayed. Add a banner showing current mission 
   type and status.

F) **GPS Denied Visual**: The uncertainty ring exists but the toggle might not 
   cycle through all modes (if we add DENIED). Update the toggle to support 
   FULL → DEGRADED → DENIED.

G) **Trail Persistence**: Trails reset if the page reloads. For a demo video 
   this is fine, but trails should be more visible — increase opacity or width.

H) **Responsive Layout**: The 70/30 split may not work well at all screen sizes. 
   For the demo video, optimize for a specific resolution (1920x1080 or 2560x1440).

DELIVERABLES:
1. Switch to better dark map tiles (CartoDB dark_all)
2. Wire in RTBButton and ScenarioButton components
3. Add target marker for intercept missions
4. Add formation lines between vessels
5. Add prominent mission status banner
6. Verify all WebSocket data is rendering correctly
7. List any remaining visual bugs
```

---

## AUDIT 6: Vessel Timing, Speed & Trajectory — Figure-8s, Wide Loops, Sluggish Turns
**Goal**: Fix why vessels make wide loops/figure-8 patterns, travel in the wrong direction for 20+ seconds before correcting, and take unreasonably long to reach destinations.

```
AUDIT TASK: Fix vessel turn dynamics so they don't loop, figure-8, or travel 
the wrong direction for extended periods during missions and return-to-base.

CONTEXT: After fixing the waypoint completion bug (Audit 1), vessels now 
correctly reach IDLE status — but their TRAJECTORIES are terrible. They make 
wide arcs, travel the wrong direction for 20+ seconds, and trace figure-8 
patterns visible on the dashboard. The root causes are in the physics chain:

The full navigation + physics pipeline per tick (dt=0.25s) is:

1. `src/navigation/planning.py` — `planning()` computes desired heading (psi_p) 
   using cross-track error correction. Look-ahead: rho = 2200/1852 ≈ 1.19 NMI.
   Waypoint acceptance: Circ = 200/1852 NMI ≈ 108 meters.

2. `src/dynamics/controller.py` — PID: kp=100, kd=-500, ki=0. Computes yaw 
   torque tau_c from heading error e_psi = psi_p - psi (NO ANGLE WRAPPING).

3. `src/dynamics/actuator_modeling.py` — Hard-clamps tau_c to ±20 (SAT_AMP=20).

4. `src/dynamics/vessel_dynamics.py` — Nomoto model:
   - k_psi = 0.01 (rudder gain), t_psi = 30.0s (yaw time constant)
   - Max steady-state yaw rate: r_ss = k_psi × SAT_AMP = 0.2 rad/s ≈ 11.5°/s
   - 180° turn takes ~16 seconds minimum
   - Random yaw bias: w_b = 0.5 × randn() EVERY tick (accumulates via t_b=600s)
   - CRITICAL: x_dot = u_c × cos(psi) — uses COMMANDED speed, not actual speed 
     state. Vessel moves at full 5 m/s instantly, even while turning 180°.

5. `src/core/integration.py` — Euler integration: x_new = x + x_dot × dt

6. `src/fleet/fleet_manager.py:141` — step() runs this chain every 0.25s.

MEASURED BEHAVIOR FROM DIAGNOSTIC RUNS:

Return-to-base from (500, 300) to home (0, 0) — distance 583m:
- Step 0:   vessel at (501, 301), heading 29° (NE) — home is SW
- Step 80:  vessel at (595, 313), heading 326° — went 100m the WRONG WAY
- Step 160: vessel at (583, 236), heading 197° — finally pointing homeward
- Step 509: IDLE at (180, 88) — took 127 seconds, traced a VISIBLE LOOP

The initial loop pattern IS the figure-8 the user sees on screen.

KNOWN ISSUES — FIX ALL OF THESE:

A) HEADING ANGLE WRAPPING BUG (CRITICAL — causes wrong-direction turns):
   In `src/dynamics/controller.py` line 31: `e_psi = psi_p - psi`
   This has NO angle wrapping. When psi_p = -170° and psi = +170°, the 
   error computes as -340° instead of +20°. The vessel turns 340° the LONG 
   way instead of 20° the SHORT way.
   
   FIX: Wrap e_psi to [-pi, pi]:
   ```python
   e_psi = psi_p - psi
   e_psi = (e_psi + np.pi) % (2 * np.pi) - np.pi  # wrap to [-pi, pi]
   ```
   This requires `import numpy as np` at the top of controller.py.

B) NO SPEED REDUCTION DURING LARGE HEADING ERRORS (causes wide arcs):
   The vessel moves at full commanded speed (5 m/s) even when the heading 
   error is 90° or 180°. At 5 m/s with a 16-second turn, it covers 80m+ 
   in the wrong direction.
   
   FIX in `src/fleet/fleet_manager.py` step(), after computing psi_desired 
   and before calling controller():
   ```python
   # Reduce speed when turning hard to prevent wide arcs
   heading_err = abs((psi_desired - state[2] + np.pi) % (2 * np.pi) - np.pi)
   speed_scale = max(0.3, 1.0 - 0.7 * heading_err / np.pi)
   effective_speed = v["desired_speed"] * speed_scale
   ```
   Then pass effective_speed to controller() instead of v["desired_speed"].
   This makes vessels slow to 30% speed during 180° turns (tight arcs) 
   and full speed when heading is correct.

C) RANDOM YAW BIAS NOISE IS TOO AGGRESSIVE (causes persistent drift):
   In `src/dynamics/vessel_dynamics.py` line 31: `w_b = 0.5 * np.random.randn()`
   This injects fresh random noise EVERY 0.25s tick. The bias state b has a 
   600-second time constant, so noise accumulates into persistent heading drift 
   of 10-15m over a 160-second mission.
   
   FIX: Either:
   - Reduce magnitude: `w_b = 0.1 * np.random.randn()` (still realistic, less disruptive)
   - Or scale by sqrt(dt): `w_b = 0.5 * np.sqrt(dt) * np.random.randn()` (physically correct)
   - Or remove entirely for deterministic behavior: `w_b = 0.0`
   Recommendation: reduce to 0.1 — keeps some realism without wrecking trajectories.

D) WAYPOINT ACCEPTANCE CIRCLE MAY BE TOO LARGE FOR SHORT MISSIONS:
   Circ = 200/1852 NMI ≈ 108 meters. For harbor patrols with waypoints 
   200-400m apart, the vessel "arrives" when still 108m away and skips ahead.
   
   FIX in `src/navigation/planning.py`: Reduce to 50m:
   `Circ = 50/1852`
   Or make it configurable — but 50m is a reasonable default for this sim.

E) CROSS-TRACK ERROR CORRECTION CAUSES OSCILLATION NEAR WAYPOINTS:
   In `planning()`, rho = 2200/1852 ≈ 1.19 NMI (2200m look-ahead). When 
   the vessel is within a few hundred meters of the waypoint, the cross-track 
   correction can flip sign rapidly, causing heading wobble.
   
   FIX: When distance to waypoint is small (< 500m), switch to pure pursuit 
   (just steer directly toward the waypoint, ignore cross-track):
   ```python
   dist_to_wpt = np.sqrt(Xewpt**2 + Yewpt**2)
   if dist_to_wpt < 500/1852:  # within 500m, use pure pursuit
       psi_p = np.arctan2(Yewpt, Xewpt)
   else:
       # existing cross-track correction
       ...
   ```

F) VESSEL DYNAMICS USES u_c FOR POSITION INSTEAD OF u STATE:
   `x_dot = u_c * cos(psi)` means position updates use the commanded speed 
   input directly, not the actual velocity state u (which has a 50-second 
   ramp-up time constant). The u state is computed but NEVER affects position.
   This means vessels have zero speed dynamics — they instantly move at 
   commanded speed. This is inconsistent and confusing.
   
   FIX: Either use u for position (realistic speed ramp):
   `x_dot = u * np.cos(psi)` and `y_dot = u * np.sin(psi)`
   Or document the current behavior as intentional and accept instant speed.
   Recommendation: keep u_c for now (instant speed is fine for demos) but 
   be aware this is why "speed" in the state display ramps up slowly while 
   the vessel is already moving at full speed.

TIMING REFERENCE TABLE (post-fix expected values):
| Distance | Speed | Expected Time | Notes |
|----------|-------|---------------|-------|
| 200m     | 5 m/s | ~40-50s       | Including initial turn alignment |
| 500m     | 5 m/s | ~100-110s     | ~1.7 minutes |
| 1000m    | 5 m/s | ~200-210s     | ~3.3 minutes |
| 2000m    | 5 m/s | ~400-420s     | ~6.7 minutes |
| 180° turn| any   | ~5-8s         | With heading wrapping fix, much tighter |
| RTB 500m | 5 m/s | ~100-120s     | Should NOT loop — direct path |

DELIVERABLES:
1. Fix heading wrapping in controller.py (Issue A) — MOST IMPORTANT
2. Add speed scaling during turns in fleet_manager.py step() (Issue B)
3. Reduce yaw bias noise in vessel_dynamics.py (Issue C)
4. Reduce waypoint acceptance circle in planning.py (Issue D)
5. Add pure pursuit fallback near waypoints in planning.py (Issue E)
6. Add these trajectory tests to tests/test_fleet_manager.py:
   a) test_vessel_does_not_overshoot_on_uturn: vessel at heading 0° targeting 
      waypoint at 180° should NOT travel more than 100m in the wrong direction 
      before correcting course
   b) test_return_to_base_no_loop: vessel 500m from home should return in under 
      150 seconds without its trajectory exceeding 150% of the straight-line distance
   c) test_vessel_straight_line_accuracy: vessel navigating 1000m in a straight 
      line should stay within 30m of the ideal path (lateral deviation)

FILES TO MODIFY:
- `src/dynamics/controller.py` — heading wrapping (Issue A)
- `src/fleet/fleet_manager.py` — speed scaling during turns (Issue B)
- `src/dynamics/vessel_dynamics.py` — yaw bias noise (Issue C)
- `src/navigation/planning.py` — acceptance circle + pure pursuit fallback (Issues D, E)
- `tests/test_fleet_manager.py` — three new trajectory tests
```

---

## AUDIT 7: LLM Command Quality & Waypoint Validation
**Goal**: Ensure the Ollama LLM produces correct, safe, and consistent FleetCommands from natural language input.

```
AUDIT TASK: Audit and harden the LLM command parsing pipeline so that 
natural language commands reliably produce valid, safe fleet commands.

CONTEXT: The LLM pipeline is:
1. User types/speaks a command (e.g., "All vessels patrol the harbor in echelon")
2. `src/llm/ollama_client.py` — parse_fleet_command() sends NL text to Ollama 
   with a system prompt and Pydantic schema enforcement. Model: Qwen 2.5 72B.
3. Ollama returns structured JSON matching FleetCommand.model_json_schema()
4. Pydantic validates the response into a FleetCommand object
5. `src/fleet/fleet_commander.py` — handle_command() calls parse_fleet_command() 
   then dispatches the result to FleetManager

THE SYSTEM PROMPT (in ollama_client.py) tells the LLM:
- Fleet roster: alpha, bravo, charlie (surface), eagle-1 (air)
- Waypoints in meters, range 0-2000
- Speed: surface 3-8 m/s, drone 10-20 m/s
- Pick best mission type from: patrol, search, escort, loiter, aerial_recon
- Has 1 example command

KNOWN ISSUES TO INVESTIGATE AND FIX:

A) WAYPOINT VALIDATION — NO BOUNDS CHECKING:
   The LLM can generate waypoints at ANY coordinate. The system prompt says 
   "range 0-2000" but Pydantic doesn't enforce this. The LLM could produce:
   - Negative coordinates (behind the fleet)
   - Coordinates at 50000+ meters (off the map entirely)
   - Coordinates at 0,0 (on top of the starting position)
   - NaN or extremely large floats
   
   FIX: Add post-parse validation in fleet_commander.py or ollama_client.py:
   ```python
   MAX_RANGE = 5000  # meters — reasonable operating area
   for asset_cmd in command.assets:
       for wp in asset_cmd.waypoints:
           wp.x = max(-MAX_RANGE, min(MAX_RANGE, wp.x))
           wp.y = max(-MAX_RANGE, min(MAX_RANGE, wp.y))
   ```
   Also validate: speed clamping (1-25 m/s), altitude clamping (10-500m for air),
   and reject commands with zero waypoints for EXECUTING assets.

B) ASSET ID HALLUCINATION:
   The LLM might produce asset_ids that don't exist ("delta", "eagle-2", 
   "drone-1"). Pydantic won't catch this because asset_id is just a str field.
   The fleet_manager.py dispatch_command() silently ignores unknown surface IDs 
   (line 96: `if ac.asset_id in self.vessels`) and unknown drone IDs (line 120: 
   `if ac.asset_id == self.drone.asset_id`). This means a hallucinated ID causes 
   that asset to do NOTHING with no error feedback.
   
   FIX: In fleet_commander.py, after parsing, check all asset IDs are valid:
   ```python
   VALID_IDS = {"alpha", "bravo", "charlie", "eagle-1"}
   invalid = [ac.asset_id for ac in command.assets if ac.asset_id not in VALID_IDS]
   if invalid:
       # Log warning and filter out invalid assets
   ```

C) SYSTEM PROMPT HAS ONLY 1 EXAMPLE:
   The LLM has a single example in the system prompt. For a 72B model with 
   schema enforcement, this may be sufficient for simple commands, but complex 
   or ambiguous commands will produce inconsistent results.
   
   FIX: Add 3-4 more examples covering edge cases:
   - Voice-style command: "Send alpha and bravo to patrol around 800 600"
   - Drone-only command: "Eagle one, orbit over position 500 300 at 200 meters"
   - RTB-adjacent: "All vessels move to 100 100" (should still be a valid mission)
   - Ambiguous: "Search the northern area" (LLM must generate reasonable waypoints)
   
   Also add negative examples (what NOT to produce):
   - "Do NOT create asset IDs that aren't in the roster"
   - "Do NOT set surface vessel altitude"
   - "If the user says 'drone', they mean eagle-1"

D) NO TIMEOUT ON LLM CALL:
   The `chat()` call in ollama_client.py has no explicit timeout. On a 72B model, 
   inference takes 5-15 seconds normally, but could hang for 60+ seconds if the 
   model gets stuck or Ollama has issues.
   
   FIX: Add timeout handling. The ollama Python library's chat() function may 
   not support a direct timeout parameter. Wrap it with asyncio.wait_for() 
   or use a threading-based timeout:
   ```python
   import signal
   
   class TimeoutError(Exception):
       pass
   
   def _timeout_handler(signum, frame):
       raise TimeoutError("LLM inference timed out")
   
   # In parse_fleet_command:
   signal.signal(signal.SIGALRM, _timeout_handler)
   signal.alarm(30)  # 30 second timeout
   try:
       response = chat(...)
   finally:
       signal.alarm(0)
   ```
   Or use the httpx-based approach with a timeout parameter if calling 
   the Ollama HTTP API directly.

E) VOICE TRANSCRIPTION MISMATCHES:
   mlx-whisper may transcribe "Eagle-1" as "Eagle One", "Eagle 1", "eagle one", 
   or "eagle-one". The system prompt should explicitly list these variations:
   "If the user says 'eagle', 'eagle one', 'eagle 1', or 'eagle-1', the 
   asset_id is always 'eagle-1'"
   
   Similarly: "alpha" might be transcribed as "Alpha", "alfa", or "Alfa".
   Add normalization in the system prompt or as a pre-processing step.

F) NO FEEDBACK ON PARTIAL FAILURES:
   If the LLM produces a command where 2 of 3 assets are valid but 1 has a 
   hallucinated ID, the response still shows success=True. The user never 
   knows that one asset was silently ignored.
   
   FIX: In fleet_commander.py, after dispatch, return a summary of which 
   assets were actually activated. The CommandResponse schema has an 
   Optional[str] error field that could hold warnings.

G) RETRY LOGIC DOESN'T VARY THE PROMPT:
   parse_fleet_command() retries 3 times on failure, but sends the EXACT 
   same messages each time. If the LLM consistently fails on a particular 
   input, retrying identically won't help.
   
   FIX: On retry, slightly modify the prompt — e.g., add "Please ensure 
   your response is valid JSON matching the schema exactly." or increase 
   temperature slightly on retry.

DELIVERABLES:
1. Add waypoint bounds clamping after LLM parse (Issue A)
2. Add asset ID validation with warning (Issue B)
3. Expand system prompt with 3-4 more examples (Issue C)
4. Add timeout protection on LLM inference (Issue D)
5. Add voice transcription aliases for asset names (Issue E)
6. Return dispatch summary showing which assets were activated (Issue F)
7. Improve retry logic with prompt variation (Issue G)
8. Add tests:
   a) test_waypoint_clamping: verify out-of-range waypoints are clamped
   b) test_invalid_asset_id_filtered: verify hallucinated IDs are caught
   c) test_parse_timeout: verify timeout triggers after N seconds (mock)

FILES TO MODIFY:
- `src/llm/ollama_client.py` — system prompt examples, timeout, retry logic
- `src/fleet/fleet_commander.py` — waypoint validation, asset ID check, dispatch summary
- `tests/test_fleet_commander.py` — new validation tests
- `tests/test_ollama_client.py` — new edge case tests (can mock Ollama)
```

---

## AUDIT 1 STATUS UPDATE (Post-Fix Notes)

Audit 1 was partially completed in a prior session. Here's what was fixed and 
what remains:

**FIXED (committed or staged):**
- `src/navigation/planning.py` — waypoint_selection() now advances i_wpt past 
  the last waypoint (i_wpt = j + 1), allowing completion detection
- `src/fleet/fleet_manager.py` — Added `continue` after setting IDLE so the 
  vessel stops navigating after reaching the last waypoint
- `tests/test_fleet_manager.py` — Added test_vessel_reaches_waypoint_and_goes_idle

**NOT YET FIXED (these are now covered by Audit 6):**
- Heading angle wrapping in controller.py (causes figure-8 wrong-direction turns)
- Speed reduction during large heading errors (causes wide arcs)
- Yaw bias noise too aggressive (causes heading drift)
- Waypoint acceptance circle too large (108m)
- Cross-track oscillation near waypoints

Audit 1 fixed "vessel never stops" but Audit 6 fixes "vessel takes a terrible 
path to get there." Both are needed for correct navigation behavior.

---

## AUDIT 6 STATUS UPDATE (Completed 2026-04-01)

**ALL 6 ISSUES FIXED + 3 TRAJECTORY TESTS ADDED.** Commit: `054c6cf`

**Changes by file:**

| File | Issue | Fix Applied |
|------|-------|-------------|
| `src/dynamics/controller.py` | A — Heading wrapping | `e_psi = (e_psi + np.pi) % (2*np.pi) - np.pi` — vessels now take the short-way turn |
| `src/fleet/fleet_manager.py` | B — Speed during turns | Speed scales to 30% at 180° error: `max(0.3, 1.0 - 0.7 * err/pi)` — tight arcs instead of wide loops |
| `src/dynamics/vessel_dynamics.py` | C — Yaw bias noise | Reduced `w_b` from `0.5 * randn()` to `0.1 * randn()` — less drift, still realistic |
| `src/navigation/planning.py` | D — Acceptance circle | Reduced from 108m (`200/1852`) to 27m (`50/1852`) — better for short missions |
| `src/navigation/planning.py` | E — Pure pursuit fallback | Within 500m of waypoint, steer directly (ignore cross-track) — eliminates near-waypoint wobble |
| N/A | F — `u_c` vs `u` for position | No change — instant speed via `u_c` is acceptable for demo. Documented as intentional. |

**Tests added to `tests/test_fleet_manager.py`:**
- `test_vessel_does_not_overshoot_on_uturn` — U-turn overshoot < 100m
- `test_return_to_base_no_loop` — RTB 500m in < 150s, trajectory < 150% straight-line
- `test_vessel_straight_line_accuracy` — lateral deviation < 30m over 1000m

**Live verification:** Patrol to (800, 400) with all assets → RTB. Clean arcs, no figure-8, 
no wrong-direction travel. Visible improvement on dashboard trail lines.

**Note on Issue F (instant speed):** The vessel dynamics use `u_c` (commanded speed) 
directly for position updates rather than the `u` state (which ramps up via a 50s time 
constant). This means vessels move at full speed instantly. The `u` state IS computed 
and ramps up, but only affects the reported speed in `get_fleet_state()`, not the actual 
trajectory. This is a known inconsistency but acceptable for demo purposes. If realistic 
speed ramp-up is ever needed (e.g., for harbor maneuvering), change lines 26-27 in 
`vessel_dynamics.py` from `u_c * cos/sin(psi)` to `u * cos/sin(psi)`.

**Future consideration — simulation time scaling:** The physics engine uses `dt` passed 
into `step()`. A time multiplier (e.g., 2x, 4x, 8x) can be implemented by calling 
`step(dt * time_scale)` or by calling `step(dt)` multiple times per real-time tick. 
This would let the operator fast-forward missions on screen without changing physics 
constants. The WebSocket tick rate (4Hz) stays the same — only the sim advances faster. 
This is safe as long as `dt * time_scale` stays below ~1.0s to avoid Euler integration 
instability. Recommended approach: multiple sub-steps per tick rather than one large dt.

---

## AUDIT 2 STATUS UPDATE (Completed 2026-04-01)

**LAND AVOIDANCE MODULE BUILT + INTEGRATED.** Commit: `e46962c`

**Approach chosen:** Simplified Cape Cod polygon defined inline (24 lat/lng vertices, ~500m 
accuracy), converted to local meters at import time. Pure ray-casting — no Shapely or 
external data files. Extensible: add RI harbor polygons by appending to `LAND_POLYGONS` list.

**New file: `src/navigation/land_check.py`**
- `is_on_land(x, y)` — ray-casting point-in-polygon against all land polygons
- `nearest_water_point(x, y)` — projects to nearest polygon edge + 10m margin into water
- `check_path_clear(x1, y1, x2, y2)` — sampled line-segment vs coastline (20 sample points)
- `land_repulsion_heading(x, y, psi, look_ahead)` — sweeps left/right to find clear water, returns partial heading correction (radians)
- `latlng_to_meters(lat, lng)` — coordinate conversion using shared ORIGIN_LAT/ORIGIN_LNG
- Cape Cod polygon covers from Canal (Bourne) through Provincetown, both Atlantic and bay coasts

**Integration in `fleet_manager.py step()`:**
- 6 lines added after `planning()` computes `psi_desired`, before speed-scaling block
- Calls `land_repulsion_heading(state[0], state[1], psi_desired, look_ahead=75.0)`
- Adds correction to `psi_desired` — the existing speed-scaling-during-turns and PID controller then operate on the corrected heading
- Does NOT touch reactive_avoidance (vessel-vessel), controller, or vessel_dynamics

**Tests: `tests/test_land_check.py` — 17 new tests**
- Coordinate conversion (3), is_on_land point-in-polygon (5), check_path_clear (3), nearest_water_point (2), land_repulsion_heading (3), integration sim (1)
- Integration test: vessel near Truro coast heading toward land for 50s — land correction prevents grounding
- **136 total tests passing** (119 existing + 17 new), zero regressions

**What's NOT yet done (needed for RI harbor):**
- Dashboard coastline overlay (optional Audit 5 item)
- Higher-resolution polygons for harbor approaches
- Channel waypoint planning (safe routes through narrow passages)
- Return-to-base land-aware pathfinding

---

## AUDIT 4 STATUS UPDATE (Completed 2026-04-01)

**INTERCEPT MISSION + CONTACT TRACKING BUILT.** 141 tests passing (136 existing + 5 new).

**Schema additions (`src/schemas.py`):**
- `INTERCEPT = "intercept"` added to `MissionType` enum (now 6 mission types)
- `Contact` model: `contact_id`, `x`, `y`, `heading` (radians, math convention), `speed` (m/s), `domain`
- `contacts: List[Contact] = []` field added to `FleetState`

**Contact simulation (`src/fleet/fleet_manager.py`):**
- `contacts` dict in `__init__()` — starts empty
- `spawn_contact(contact_id, x, y, heading, speed, domain)` — creates simulated target
- `remove_contact(contact_id)` — removes by ID, returns bool
- In `step()`: contacts move in straight lines — `x += speed * cos(heading) * dt`
- In `get_fleet_state()`: contacts included in FleetState response

**Intercept behavior:** One-shot waypoint dispatch. Surface vessels navigate to target position via existing waypoint nav. Drone assigned TRACK pattern. No continuous pursuit — dynamic re-targeting is a future enhancement.

**LLM update (`src/llm/ollama_client.py`):**
- Added `intercept` to mission type list in system prompt rule #7
- Added Example 6: intercept command with echelon formation and drone TRACK

**API endpoints (`src/api/routes.py`):**
- `GET /api/contacts` — list active contacts
- `POST /api/contacts` — spawn contact (contact_id, x, y, heading, speed, domain)
- `DELETE /api/contacts/{contact_id}` — remove contact

**Tests (`tests/test_intercept.py` — 5 new tests):**
- `test_spawn_and_remove_contact` — create, verify, remove, verify gone
- `test_contact_moves_in_step` — straight-line motion matches expected displacement
- `test_intercept_dispatch_sets_waypoints` — vessels EXECUTING, drone TRACK, mission recorded
- `test_contacts_in_fleet_state` — contacts appear/disappear in FleetState
- `test_intercept_mission_vessels_converge` — 200-step integration, all assets closer to target

**What's NOT in this audit (deferred):**
- Continuous pursuit / dynamic re-targeting (future enhancement)
- Formation maintenance during transit (formations applied at dispatch only)
- Land-aware return-to-base (Phase 4 of RI roadmap, needs channel_nav.py)
- Dashboard contact markers (Audit 5 scope)

---

## FUTURE GOAL: Rhode Island Harbor Navigation — Full Roadmap

The end-state demo: fleet departs an RI harbor, transits the channel to open water, 
intercepts a target, and returns through the channel to dock. This section breaks down 
every capability needed, what exists today, and what must be built — without breaking 
anything that already works.

### What Exists Today (foundation)
| Capability | Status | Files |
|------------|--------|-------|
| Surface vessel dynamics | Working | `vessel_dynamics.py`, `controller.py` |
| Waypoint navigation + pure pursuit | Working (Audit 6) | `planning.py` |
| Heading wrapping + speed scaling | Working (Audit 6) | `controller.py`, `fleet_manager.py` |
| Vessel-vessel reactive avoidance | Working | `reactive_avoidance.py` |
| Land detection (Cape Cod polygon) | Working (Audit 2) | `land_check.py` |
| Land repulsion heading correction | Working (Audit 2) | `land_check.py` → `fleet_manager.py` |
| LLM command parsing + validation | Working (Audit 7) | `ollama_client.py`, `fleet_commander.py` |
| Drone coordination patterns | Working | `drone_coordinator.py`, `drone_dynamics.py` |
| Return-to-base (straight line) | Working but naive | `fleet_manager.py` |
| Formation dispatch | Working (at dispatch time) | `formations.py` |

### Gap Analysis — What Must Be Built

**PHASE 1: RI Coastline Data** (extends Audit 2, no code changes beyond land_check.py)
- Add Narragansett Bay polygon(s) to `LAND_POLYGONS` in `land_check.py`
- Need: Point Judith → Newport → Jamestown → Conanicut → Prudence Island → Providence shoreline
- Accuracy needed: ~100m for open bay, ~25m for harbor channels
- Data source options:
  - Manual polygon from nautical charts (lightest, same approach as Cape Cod)
  - NOAA ENC extract for Narragansett Bay (accurate, public domain, but needs parsing)
  - Natural Earth 1:10m coastline shapefile clipped to area (middle ground)
- Move `ORIGIN_LAT`/`ORIGIN_LNG` to a shared config or accept per-scenario origins
- **Risk:** Large/complex polygons slow down ray-casting. Mitigate with bounding-box pre-check per polygon.

**PHASE 2: Channel Waypoint Graph** (new module, ~1 file)
- Create `src/navigation/channel_nav.py` with a graph of safe waypoints through the harbor
- Nodes: named waypoints along the channel center (e.g., "harbor_mouth", "channel_buoy_3", "breakwater_exit", "open_water_start")
- Edges: straight-line segments verified clear via `check_path_clear()`
- `plan_channel_route(start_xy, end_xy) -> List[Waypoint]` — A* or Dijkstra from nearest channel node to open water
- This replaces the current straight-line waypoint approach for harbor transits
- **Key constraint:** Must output waypoints in the same format that `fleet_manager.py dispatch_command()` already consumes (list of `Waypoint(x, y)` in meters). No schema changes needed.
- For return-to-base: `fleet_manager.py return_to_base()` currently sends vessels straight home. Must route through channel graph instead.

**PHASE 3: Target / Contact Model** ✅ DONE (Audit 4)
- `INTERCEPT` added to `MissionType`, `Contact` model added, `FleetState.contacts` field added
- `fleet_manager.py` has contacts dict, spawn/remove, straight-line step update
- Intercept is one-shot waypoint dispatch (no lead-angle computation yet — future enhancement)
- Drone switches to TRACK pattern on target
- API endpoints for contact CRUD at `/api/contacts`

**PHASE 4: Land-Aware Return-to-Base** (modifies fleet_manager.py)
- Current `return_to_base()` draws a straight line from current position to home
- If the fleet is in open water and home is in a harbor, the straight line crosses land
- Fix: use channel_nav to plan the return route through the harbor entrance
- `return_to_base()` calls `plan_channel_route(current_pos, home_pos)` and dispatches those waypoints
- The land_repulsion_heading in `step()` acts as a safety net, but the PRIMARY avoidance should be the channel route

**PHASE 5: Slow-Speed Harbor Maneuvering** (optional, vessel_dynamics.py)
- Current vessels use `u_c` (instant speed) for position. Fine in open water.
- In a narrow harbor channel, instant speed changes look unrealistic and could overshoot turns
- Fix: switch to `u` (ramped speed state) for position updates in `vessel_dynamics.py` lines 26-27
- Also need tighter turn radius at slow speed — reduce `SAT_AMP` or increase `k_psi` proportionally
- **Only do this if channel navigation looks wrong at the current instant-speed behavior. Don't fix preemptively.**

**PHASE 6: LLM + Dashboard Updates** (Audit 5/7 scope)
- Update `ollama_client.py` system prompt: new coordinate ranges, RI harbor location, channel terminology
- Dashboard: render coastline polygons as Leaflet overlays (no-go zones), channel waypoints as markers
- Add target/contact marker (red) for intercept missions
- Move ORIGIN_LAT/ORIGIN_LNG to scenario config so Cape Cod and RI demos can coexist

### Dependency Chain (build order)
```
Phase 1 (RI polygons)
    └─→ Phase 2 (channel nav graph)
            └─→ Phase 4 (land-aware RTB)
                    └─→ Phase 5 (slow-speed, if needed)

Phase 3 (intercept/target — Audit 4, independent of land)
    └─→ Phase 6 (dashboard + LLM — after everything else works)
```

### What NOT To Do
- Do NOT add a full GIS/ENC parsing pipeline — manually-defined polygons are sufficient for the demo
- Do NOT modify `schemas.py` beyond adding INTERCEPT to MissionType (if needed) and Contact model
- Do NOT change physics constants (k_psi, t_psi, SAT_AMP) — tune behavior through speed scaling and waypoint placement
- Do NOT break the existing Cape Cod demo — RI harbor should be an additional scenario, not a replacement
- Do NOT implement real-time AIS or external sensor feeds — the target/contact is simulated internally

### Test Strategy for Each Phase
| Phase | Key Tests |
|-------|-----------|
| 1 | Point-in-polygon for RI bay land points, path_clear through channel |
| 2 | Route from harbor to open water has no land crossings, correct waypoint count |
| 3 | Intercept command dispatches, vessels converge on moving target |
| 4 | RTB from open water routes through channel, no land crossings |
| 5 | Vessel speed ramps up smoothly, doesn't overshoot turns in channel |
| 6 | LLM generates valid commands for RI scenario, dashboard renders polygons |

### Estimated Scope
- Phase 1: 1 session (polygon data entry + tests)
- Phase 2: 1-2 sessions (channel graph + A* + integration)
- Phase 3: 1-2 sessions (Audit 4 — schemas, target tracking, intercept logic)
- Phase 4: 1 session (RTB routing through channel graph)
- Phase 5: 0-1 sessions (only if needed after testing Phase 4)
- Phase 6: 1-2 sessions (dashboard + LLM updates)

---

## RECOMMENDED EXECUTION ORDER

| Order | Audit | Priority | Why |
|-------|-------|----------|-----|
| 1 | **Audit 1: Navigation Circling** | DONE ✓ | Waypoint completion fixed — vessels reach IDLE |
| 2 | **Audit 6: Timing & Trajectory** | DONE ✓ | Heading wrapping, speed scaling, yaw noise, acceptance circle, pure pursuit |
| 3 | **Audit 7: LLM Command Quality** | DONE ✓ | Waypoint clamping, asset ID validation, expanded prompt, timeout, retry variation |
| 4 | **Audit 2: Land Avoidance** | DONE ✓ | Cape Cod polygon, land_check.py, heading correction in fleet_manager |
| 5 | **Audit 4: Mission Lifecycle** | DONE ✓ | Intercept mission, Contact model, target simulation, API endpoints |
| 6 | **Audit 3: GPS Denied** | HIGH — NEXT | Key differentiator — dead reckoning + drift accumulation |
| 7 | **Audit 5: Dashboard Polish** | MEDIUM | Visual polish + contact markers + coastline overlay after functionality works |

**Current state (5 of 7 audits complete):** Navigation is solid, LLM commands are validated, 
land avoidance works, and intercept/contact tracking is operational. The remaining audits 
(3, 5) build on this foundation.

**Why Audit 3 is next:** GPS-denied mode is currently cosmetic — noise is added to display 
positions but navigation uses true state. Making dead reckoning actually affect navigation 
is a key differentiator for the demo and doesn't depend on any unfinished work.

## CRITICAL PHYSICS PARAMETERS TO KNOW

These numbers define how the simulation ACTUALLY behaves. Every session that touches 
navigation, physics, or timing needs to understand these:

| Parameter | Value | Location | Effect |
|-----------|-------|----------|--------|
| Vessel speed | 5.0 m/s (commanded) | fleet_manager.py dispatch | ~18 km/h, ~10 knots |
| Drone speed | 15.0 m/s (default) | ollama_client.py prompt | 54 km/h |
| Simulation tick | 0.25s (dt) | ws.py | 4 Hz update rate |
| Yaw time constant | 30.0s (t_psi) | vessel_dynamics.py | How fast rudder responds |
| Max yaw rate | 11.5°/s | Derived: k_psi × SAT_AMP | From k_psi=0.01, SAT_AMP=20 |
| 180° turn time | ~16 seconds | Derived | 80m traveled during turn at 5 m/s |
| Speed time constant | 50.0s (t_v) | vessel_dynamics.py | u state ramp-up (BUT see note) |
| Position uses u_c | COMMANDED speed | vessel_dynamics.py line 26 | Instant speed, no ramp |
| Waypoint acceptance | 27m (50/1852 NMI) | planning.py | Reduced in Audit 6 from 108m |
| Pure pursuit fallback | < 500m to waypoint | planning.py | Ignores cross-track, steers direct (Audit 6) |
| Cross-track look-ahead | 2200m (2200/1852 NMI) | planning.py | Path correction distance (> 500m only) |
| Actuator saturation | ±20 | fleet_manager.py SAT_AMP | Limits max rudder torque |
| Yaw bias noise | 0.1 × randn() per tick | vessel_dynamics.py | Reduced in Audit 6 from 0.5 |
| PID gains | kp=100, kd=-500, ki=0 | controller.py | Heading wrapping fixed in Audit 6 |
| Speed scaling (turns) | max(0.3, 1.0 - 0.7×err/π) | fleet_manager.py | Slows to 30% at 180° error (Audit 6) |
| Land avoidance look-ahead | 75m (1× and 2×) | fleet_manager.py → land_check.py | Checks 75m and 150m ahead (Audit 2) |

**Speed vs Distance Quick Reference:**
- 200m at 5 m/s = 40 seconds + turn time
- 500m at 5 m/s = 100 seconds + turn time  
- 1000m at 5 m/s = 200 seconds + turn time
- A 90° course change adds ~8 seconds and ~40m of arc
- A 180° course change adds ~16 seconds and ~80m of arc (or MUCH worse without heading wrapping fix)

## TIPS FOR SAVING CREDITS

- Run each audit as a SEPARATE Claude Code session (don't mix)
- Copy the FULL audit prompt above — it has all the context Claude Code needs
- After each audit produces fixes, COMMIT to git before starting the next
- If an audit runs long, don't let it explore endlessly — if it hasn't found 
  the fix in ~10 minutes of iteration, stop it and share the findings here 
  so we can refine the prompt
- Use `git diff` after each session to review what changed before accepting
- **Always run the full test suite** after fixes: `.venv/bin/python -m pytest tests/ -v`
- **Read CLAUDE.md first** — it has the project rules, file map, and unit conventions
- The reference dump files are in `docs/reference/` — useful for full-text search 
  but may be slightly stale compared to actual source files
