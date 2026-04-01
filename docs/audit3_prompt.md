Execute Audit 3 — GPS Signal Loss & Dead Reckoning for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 3
(GPS Signal Loss & Dead Reckoning).

COMPLETED AUDITS (do NOT touch these files/features):
- Audit 1 (Navigation Circling): Waypoint completion fixed — vessels reach IDLE
- Audit 6 (Timing & Trajectory): Heading wrapping, speed scaling, yaw noise,
  acceptance circle, pure pursuit — all fixed in controller.py, fleet_manager.py,
  vessel_dynamics.py, planning.py
- Audit 7 (LLM Command Quality): Waypoint clamping, asset ID validation,
  system prompt expanded, 30s LLM timeout, retry with prompt variation — all in
  ollama_client.py and fleet_commander.py
- Audit 2 (Land Avoidance): Cape Cod polygon in land_check.py, land_repulsion_heading()
  integrated into fleet_manager.py step() after planning() and before PID controller.
- Audit 4 (Intercept/Contacts): INTERCEPT mission type, Contact model, FleetState.contacts,
  spawn/remove contacts, straight-line contact motion, API endpoints, LLM prompt updated.
  141 tests passing.

YOUR TASK: Execute Audit 3 — GPS Signal Loss & Dead Reckoning.

The goal is to make GPS-denied mode actually affect NAVIGATION, not just display. Currently
degrade_position() adds Gaussian noise to the REPORTED position in get_fleet_state(), but
the ACTUAL vessel state used for navigation in step() is unaffected. Vessels navigate
perfectly even when GPS is "denied."

────────────────────────────────────────────────────────────────────
WHAT THE CURRENT GPS-DENIED CODE DOES (cosmetic only)
────────────────────────────────────────────────────────────────────

1. src/utils/gps_denied.py:
   - degrade_position(x, y, noise_meters) — adds Gaussian noise, returns (noisy_x, noisy_y, accuracy)
   - should_update(asset_id, update_rate_hz) — rate-limits updates per asset
   These functions EXIST but degrade_position is only called in get_fleet_state() for display.

2. src/fleet/fleet_manager.py:
   - set_gps_mode(mode, noise_meters) sets self.gps_mode and self.noise_meters
   - In get_fleet_state(): when DEGRADED, calls degrade_position() on reported x,y
   - In step(): navigation reads from v["state"] (TRUE position). GPS mode has ZERO effect.

3. src/schemas.py:
   - GpsMode enum has FULL and DEGRADED (no DENIED state)

────────────────────────────────────────────────────────────────────
IMPORTANT SCHEMA DECISION — READ CAREFULLY
────────────────────────────────────────────────────────────────────

CLAUDE.md rule #1 says "SCHEMAS ARE GOD — Never modify schemas."

However, Audit 3 REQUIRES one schema addition. The user has authorized:

  1. Add DENIED = "denied" to GpsMode enum

DO NOT modify any EXISTING fields, enums, or models. Only ADD the one item above.

────────────────────────────────────────────────────────────────────
WHAT NEEDS TO BE BUILT
────────────────────────────────────────────────────────────────────

1. SCHEMA ADDITION (src/schemas.py):
   - Add DENIED = "denied" to GpsMode enum. That's it.

2. DEAD RECKONING ENGINE (src/utils/gps_denied.py):
   - Add a DeadReckoningState class that tracks per-vessel estimated position:
     - estimated_x, estimated_y: position as the vessel "thinks" it is
     - drift_error: accumulated drift in meters
     - time_denied: seconds since GPS was lost
   - Add dead_reckon_step(dr_state, speed, heading_rad, dt) function:
     - Updates estimated position using speed * cos/sin(heading) * dt
     - Adds small drift: ~0.5% of distance traveled per step, random walk direction
     - Increments time_denied
   - Add get_navigated_position(true_x, true_y, dr_state, gps_mode) function:
     - FULL: returns (true_x, true_y) — no degradation
     - DEGRADED: returns degrade_position(true_x, true_y) — existing noise behavior
     - DENIED: returns (dr_state.estimated_x, dr_state.estimated_y) — pure dead reckoning

3. INTEGRATION IN FLEET_MANAGER (src/fleet/fleet_manager.py):
   - Add a dr_states dict in __init__(): maps vessel_id -> DeadReckoningState
   - Initialize each vessel's DR state with its starting position
   - In step(), for each vessel, BEFORE the navigation pipeline:
     - If gps_mode is DENIED: update DR state, then use DR estimated position
       for waypoint_selection and planning instead of true state[0], state[1]
     - If gps_mode is DEGRADED: use degrade_position(true_x, true_y) for nav
     - If gps_mode is FULL: use true position (current behavior)
   - IMPORTANT: The actual physics simulation (vessel_dynamics, integration) ALWAYS
     uses the TRUE state. Only the NAVIGATION INPUT (what position the nav system
     "sees") changes. The vessel still physically moves correctly — it just might be
     steering to the wrong place because it thinks it's somewhere else.
   - In set_gps_mode(): when switching TO denied, initialize DR states from current
     true positions. When switching FROM denied to FULL, reset DR states.
   - In get_fleet_state(): when DENIED, report DR estimated positions (not true).
     Include drift error in position_accuracy field.

4. DRONE HANDLING:
   - For simplicity, the drone navigates perfectly in all GPS modes (it has INS).
   - Only surface vessels are affected by GPS degradation.

5. DO NOT IMPLEMENT:
   - Smooth position correction on GPS recovery (nice-to-have but not needed now)
   - Dashboard GPS-denied UI changes (that's Audit 5)
   - DENIED mode for contacts (contacts have perfect position always)

────────────────────────────────────────────────────────────────────
KEY INTEGRATION DETAIL — READ CAREFULLY
────────────────────────────────────────────────────────────────────

The step() function in fleet_manager.py currently does this for each vessel:

    x_nmi = state[0] * METERS_TO_NMI   # <-- TRUE position
    y_nmi = state[1] * METERS_TO_NMI

    i_wpt = waypoint_selection(wpts_x, wpts_y, x_nmi, y_nmi, i_wpt)
    psi_desired = planning(wpts_x, wpts_y, x_nmi, y_nmi, i_wpt)

For GPS denied, you need to change the x_nmi/y_nmi that feed into waypoint_selection
and planning — NOT the actual state array. Something like:

    # Get navigated position (may differ from true if GPS denied)
    nav_x, nav_y = state[0], state[1]  # default: true position
    if self.gps_mode == GpsMode.DENIED:
        dr = self.dr_states[vid]
        dead_reckon_step(dr, state[5], state[2], dt)  # state[5]=speed, state[2]=heading
        nav_x, nav_y = dr.estimated_x, dr.estimated_y
    elif self.gps_mode == GpsMode.DEGRADED:
        nav_x, nav_y, _ = degrade_position(state[0], state[1], self.noise_meters)

    x_nmi = nav_x * METERS_TO_NMI
    y_nmi = nav_y * METERS_TO_NMI

    # Rest of navigation pipeline uses x_nmi, y_nmi (potentially wrong)
    # Physics (vessel_dynamics, integration) still uses true state — unchanged

The land_repulsion_heading() call MUST still use TRUE position (state[0], state[1])
because we need actual land avoidance regardless of GPS mode. Don't let a vessel
physically run aground just because its DR position says it's in open water.

────────────────────────────────────────────────────────────────────
WHAT NOT TO TOUCH
────────────────────────────────────────────────────────────────────

  - src/dynamics/controller.py — heading wrapping fixed in Audit 6
  - src/dynamics/vessel_dynamics.py — yaw noise fixed in Audit 6
  - src/navigation/planning.py — acceptance circle + pure pursuit fixed in Audit 6
  - src/navigation/land_check.py — land avoidance working from Audit 2
  - The land_repulsion_heading() call in fleet_manager.py step()
  - The speed-scaling-during-turns block in fleet_manager.py step()
  - Contact simulation logic in fleet_manager.py step()
  - src/llm/ollama_client.py, src/fleet/fleet_commander.py
  - Existing test files (don't modify, only add new tests)

────────────────────────────────────────────────────────────────────
FILES TO READ BEFORE CODING
────────────────────────────────────────────────────────────────────

  - CLAUDE.md — project rules and conventions
  - src/schemas.py — GpsMode enum, AssetState (has position_accuracy, gps_mode fields)
  - src/utils/gps_denied.py — current cosmetic-only implementation
  - src/fleet/fleet_manager.py — step(), get_fleet_state(), set_gps_mode()
  - tests/test_fleet_manager.py — existing test_gps_denied_adds_noise test

────────────────────────────────────────────────────────────────────
PHYSICS REMINDERS
────────────────────────────────────────────────────────────────────

  - Vessel state: [x, y, psi, r, b, u] — x,y meters, psi radians (0=East, CCW+)
  - state[0]=x, state[1]=y, state[2]=psi (heading), state[5]=u (speed state)
  - NOTE: actual vessel speed for position is from u_c (commanded), NOT state[5].
    state[5] ramps up slowly. For DR step, use v["desired_speed"] as the speed
    the vessel "thinks" it's going, since that's what a real INS would integrate.
    Or use state[5] for more realistic drift — either is acceptable.
  - Waypoints in navigation are in nautical miles (÷1852)
  - Simulation tick: dt=0.25s at 4Hz
  - Vessel speed: 5.0 m/s, drone speed: 15.0 m/s

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

  1. Modified src/schemas.py — add DENIED to GpsMode
  2. Modified src/utils/gps_denied.py — DeadReckoningState, dead_reckon_step(),
     get_navigated_position()
  3. Modified src/fleet/fleet_manager.py — dr_states dict, GPS-mode-aware nav
     in step(), DR positions in get_fleet_state()
  4. Tests (new file tests/test_gps_denied.py):
     - test_dead_reckon_step_accumulates_drift
     - test_denied_mode_affects_navigation (integration: dispatch command,
       enable DENIED, step 200 times, verify vessel trajectory differs from
       FULL GPS trajectory)
     - test_denied_mode_drift_grows_over_time (DR drift increases with steps)
     - test_gps_restore_resets_dr_state
     - test_degraded_mode_adds_nav_noise
     - test_land_avoidance_uses_true_position (verify land_repulsion_heading
       still uses real position even in DENIED mode — vessel near coast should
       still avoid land)
  5. Run full test suite: .venv/bin/python -m pytest tests/ -v
     All 141 existing tests must still pass.
  6. Commit when done.

EXISTING TEST COUNT: 141 tests passing as of Audit 4 completion.
