
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
- Drone: `src/fleet/drone_coordinator.py`
- LLM: `src/llm/ollama_client.py`
- Decision making: `src/decision_making/decision_making.py`
- GPS: `src/utils/gps_denied.py`
- Dashboard: `dashboard/src/components/FleetMap.jsx`, `dashboard/src/App.jsx`
- Schemas: `src/schemas.py` (source of truth — never modify schemas to fix bugs)
- API: `src/api/routes.py`, `src/api/server.py`

**Hardware**: Mac Studio M3 Ultra 256GB, everything runs air-gapped.
**Test suite**: 147 tests passing. Run with `.venv/bin/python -m pytest tests/ -v`

---

## EXECUTION ORDER — STATUS TRACKER

| Order | Audit | Status | Commit | Tests |
|-------|-------|--------|--------|-------|
| 1 | Audit 1: Navigation Circling | DONE | (early commits) | Waypoint completion fixed |
| 2 | Audit 6: Timing & Trajectory | DONE | `054c6cf` | 3 trajectory tests |
| 3 | Audit 7: LLM Command Quality | DONE | `478a866` | Validation + timeout tests |
| 4 | Audit 2: Land Avoidance | DONE | `e46962c` | 17 land_check tests |
| 5 | Audit 4: Mission Lifecycle | DONE | `098222b` | 5 intercept tests |
| 6 | Audit 3: GPS Denied | DONE | `c2caeed` | 6 dead reckoning tests |
| 7 | Audit 5: Dashboard C2 Ops | DONE | `dd49d20` | pnpm build clean |
| 8 | **Audit 8: Predictive Intercept** | **NEXT** | — | — |
| 9 | **Audit 9: Autonomous Threat Response** | PENDING | — | — |
| 10 | **Audit 10: Comms-Denied Autonomy** | PENDING | — | — |
| 11 | **Audit 11: Cross-Domain Kill Chain** | PENDING | — | — |
| 12 | **Audit 12: Decision Audit Trail** | PENDING | — | — |
| 13 | **Audit 13: Mission-Specific Behaviors** | PENDING | — | — |

---

## AUDIT 8: Predictive Intercept — Lead the Target
**Goal**: Fleet converges on where the target WILL BE, not where it was when the command was issued. This is the single highest-impact change for demonstrating tactical intelligence.

```
Execute Audit 8 — Predictive Intercept for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 8.

COMPLETED AUDITS (all backend + dashboard work is done):
- Audits 1-7 + Audit 5: Navigation, land avoidance, GPS-denied DR, intercept
  mission, contact tracking, LLM hardening, full C2 dashboard.
- 147 backend tests passing. Do NOT break them.
- POST /api/command-direct endpoint exists — accepts structured FleetCommand
  JSON directly, bypassing the LLM. Use this for testing.

YOUR TASK: Make the intercept mission predict where a moving contact will be
when the fleet arrives, and dispatch to THAT point instead of the contact's
current position.

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

Current intercept behavior (fleet_manager.py dispatch_command(), lines 99-164):
- Operator says "intercept contact at 3000 1500"
- Fleet dispatches all vessels to (3000, 1500) — the contact's CURRENT position
- Contact is moving at 1.5 m/s heading southwest
- Fleet takes 20+ minutes to arrive at 8 m/s
- By then, contact has moved ~1800m from dispatch point
- Fleet arrives at EMPTY WATER

This looks stupid in a demo. A defense CEO would immediately ask: "why doesn't
it lead the target?"

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

A) INTERCEPT POINT COMPUTATION (new function in fleet_manager.py)

   Create a function that computes the predicted intercept point:

   def compute_intercept_point(fleet_x, fleet_y, fleet_speed,
                                target_x, target_y, target_heading,
                                target_speed) -> (float, float):

   The math (iterative proportional navigation):
   1. Estimate time-to-intercept: T0 = distance / fleet_speed
   2. Predict target position at T0:
      pred_x = target_x + target_speed * cos(target_heading) * T0
      pred_y = target_y + target_speed * sin(target_heading) * T0
   3. Recalculate distance to predicted position
   4. New T1 = new_distance / fleet_speed
   5. Iterate 2-3 times (converges fast)
   6. Return the predicted intercept point

   This is standard proportional navigation — well-known in missile guidance
   and maritime interception. 2-3 iterations is sufficient for convergence.

   The fleet centroid is the reference point:
   fleet_x = mean of all surface vessel x positions
   fleet_y = mean of all surface vessel y positions
   fleet_speed = commanded speed from the intercept command (typically 8 m/s)

B) INTEGRATE INTO DISPATCH (modify dispatch_command in fleet_manager.py)

   When mission_type == "intercept" AND self.contacts is not empty:
   1. Find the target contact (first contact, or closest to the fleet)
   2. Compute intercept point using the function above
   3. Replace the commanded waypoints with the intercept point
   4. Apply formation offsets to the intercept point (existing code)
   5. Log: "Intercept solution: target at (x,y) moving HDG at SPD,
      fleet dispatching to predicted position (px, py), ETA ~Ts"

   When there are no contacts (manual coordinate intercept):
   - Keep current behavior — dispatch to the commanded waypoint as-is

C) CONTINUOUS REPLANNING (modify step() in fleet_manager.py)

   The intercept point drifts as the contact moves. Every N steps (e.g.,
   every 10 seconds = 40 steps at 4Hz), if the mission is INTERCEPT and
   contacts exist:
   1. Recompute the intercept point
   2. If it has shifted more than 100m from the current waypoint, update
      the vessel waypoints in-place
   3. Don't update too frequently — creates heading jitter

   Implementation: add a `_replan_counter` attribute, increment each step(),
   replan when counter hits threshold. Reset counter on replan.

   CRITICAL: Only update surface vessel waypoints. Drone in TRACK pattern
   should keep tracking the contact's CURRENT position, not the predicted
   one — the drone is fast enough (15 m/s) to just follow directly.

D) DASHBOARD — INTERCEPT GEOMETRY (modify FleetMap.jsx)

   When an intercept mission is active and contacts exist:
   - Draw a thin dotted line from contact to predicted intercept point
     (shows where the system thinks convergence will happen)
   - Small circle or crosshair marker at the intercept point (yellow/amber)
   - This line already partially exists (fleet-to-contact line) — extend it

   The intercept point can be computed client-side using the same math,
   or the backend can include it in FleetState. Client-side is simpler
   since it avoids schema changes.

────────────────────────────────────────────────────────────────────
COORDINATE CONVENTIONS
────────────────────────────────────────────────────────────────────

- All positions in meters (local frame, origin at 42°N, -70°W)
- Headings in radians, math convention (0=East, CCW+)
- Contact heading is stored as radians in Contact.heading
- cos(heading) gives x-component, sin(heading) gives y-component
- Fleet speed is from AssetCommand.speed (typically 8.0 m/s for surface)

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT modify schemas.py
- Do NOT change contact motion model (straight-line is correct for now)
- Do NOT add pursuit curves or complex guidance laws — simple iterative
  prediction is sufficient and more understandable
- Do NOT replan every single step — too much heading jitter. 10s interval.
- Do NOT change how the drone operates — it's fast enough to just track

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

Add to tests/test_intercept.py:

1. test_compute_intercept_point_stationary:
   Contact at (2000, 0) not moving → intercept point IS (2000, 0)

2. test_compute_intercept_point_moving:
   Fleet at (0, 0) at 8 m/s. Contact at (2000, 0) heading west at 2 m/s.
   Intercept point should be WEST of (2000, 0) — roughly (1600, 0) area.
   Verify intercept_x < 2000.

3. test_intercept_dispatch_uses_prediction:
   Spawn contact moving west. Dispatch intercept. Verify vessel waypoints
   are NOT at the contact's current position — they should be ahead of it.

4. test_intercept_replan_updates_waypoints:
   Dispatch intercept. Run 100 steps. Verify waypoints have shifted from
   original dispatch point (replan triggered).

5. test_fleet_converges_on_moving_target:
   Integration test: spawn contact at (5000, 2000) heading SW at 1.5 m/s.
   Dispatch intercept at 8 m/s. Run 1500 steps (~375s). Verify at least
   one surface vessel is within 500m of the contact's current position.
   This is the "did they actually meet?" test.

Run: .venv/bin/python -m pytest tests/ -v (expect 147 + new tests passing)

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. compute_intercept_point() function in fleet_manager.py
2. dispatch_command() uses prediction when mission is INTERCEPT + contacts exist
3. step() replans every ~10s when INTERCEPT mission active
4. Dashboard shows predicted intercept point on map
5. 5 new tests in test_intercept.py
6. Run full test suite — no regressions
7. Commit when done

DEMO VERIFICATION:
After implementation, run this sequence via curl:
  1. POST /api/contacts — spawn bogey-1 at (8000, 4000) heading -2.356 (SW) at 1.5 m/s
  2. POST /api/command-direct — intercept with all assets at 8 m/s
  3. Watch dashboard — fleet should head to a point AHEAD of the contact,
     not to (8000, 4000)
  4. After 10-15 minutes, fleet and contact should converge
```

---

## AUDIT 9: Autonomous Threat Response — Auto-Detect and Propose
**Goal**: When a contact enters detection range, the fleet automatically detects it, the drone re-tasks to track, and the system proposes a response to the operator. This is "human-on-the-loop" autonomy.

```
Execute Audit 9 — Autonomous Threat Response for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 9.

COMPLETED AUDITS: Audits 1-8 complete. Predictive intercept working.
147+ tests passing. Do NOT break them.

YOUR TASK: Make the fleet automatically detect contacts and propose a response,
without requiring the operator to manually issue an intercept command.

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

Currently, contacts are invisible to the fleet's decision-making. A contact
can be 100m away and the fleet will ignore it unless the operator types
"intercept." There is zero autonomous awareness.

The decision_making.py module has a COLREG classifier (decision_making()
function) that is NEVER CALLED — it's dead code. The reactive_avoidance.py
module has fuzzy obstacle avoidance that is ONLY called by the legacy
simulation.py, NOT by fleet_manager.py.

A defense tech CEO's first question: "What happens if a threat appears and
the operator doesn't respond?" The answer should NOT be "nothing."

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

A) THREAT DETECTION ENGINE (new file: src/fleet/threat_detector.py)

   Create a module that evaluates contacts relative to the fleet:

   class ThreatAssessment:
       contact_id: str
       distance: float          # meters from fleet centroid
       bearing: float           # radians from fleet centroid to contact
       closing_rate: float      # m/s — negative means closing
       threat_level: str        # "none", "detected", "warning", "critical"
       recommended_action: str  # "monitor", "track", "intercept"
       reason: str              # human-readable explanation

   def assess_threats(vessels: dict, contacts: dict) -> List[ThreatAssessment]:
       """Evaluate all contacts against fleet position."""

   Detection ranges (thresholds):
   - > 8000m: "none" — not detected, no action
   - 5000-8000m: "detected" — long-range detection, recommend "monitor"
   - 2000-5000m: "warning" — closing, recommend "track" (re-task drone)
   - < 2000m: "critical" — close range, recommend "intercept"

   Closing rate computation:
   - Compute fleet centroid (mean of surface vessel positions)
   - Current distance to contact
   - Project contact position 1s forward using its heading/speed
   - closing_rate = current_distance - projected_distance (positive = opening)

   The reason field should be human-readable:
   "bogey-1 detected at 6.2km bearing 045°, closing at 3.1 m/s"
   "bogey-1 CRITICAL at 1.8km bearing 032°, closing at 4.2 m/s — INTERCEPT recommended"

B) AUTO-RESPONSE IN FLEET MANAGER (modify step() in fleet_manager.py)

   In step(), after updating contacts (lines 231-234), call assess_threats().
   Store the result in self.threat_assessments (list of ThreatAssessment).

   AUTO-ACTIONS based on threat level (these happen WITHOUT operator command):

   1. "detected" → No auto-action. Just record assessment.

   2. "warning" → If drone is IDLE or in a non-TRACK pattern, automatically
      re-task drone to TRACK the contact:
      - Use DroneCoordinator.assign_pattern(TRACK, [contact_position], altitude=100)
      - Set drone status to EXECUTING
      - Log: "AUTO: Eagle-1 re-tasked to TRACK bogey-1 (warning range)"
      - Do NOT auto-task surface vessels — only the drone responds automatically

   3. "critical" → Same as warning (drone tracks), PLUS set a flag:
      self.intercept_recommended = True
      self.recommended_target = contact_id
      This flag is read by the dashboard to show a recommendation.
      The operator must still click a button to dispatch the fleet.

   IMPORTANT: Auto-response should NOT override an active mission. If the
   fleet is already EXECUTING an intercept, don't re-task the drone.
   Only auto-respond when the fleet is IDLE or on a non-intercept mission.

C) THREAT ASSESSMENTS IN FLEET STATE (modify get_fleet_state())

   Add threat assessment data to the WebSocket stream. Since we can't modify
   schemas.py, add it as a dict field that gets serialized:

   In get_fleet_state(), after building the FleetState:
   - Add threat_assessments to the response dict (as extra JSON)
   - Include: [{contact_id, distance, bearing_deg, closing_rate, threat_level,
     recommended_action, reason}]
   - Include: intercept_recommended (bool), recommended_target (str or null)

   Use FleetState's model_dump() then inject the extra fields before return.
   Or add these as Optional fields to FleetState if that's cleaner without
   violating the schema-stability rule (check if adding Optional fields with
   defaults is considered "modifying" schemas — it shouldn't break anything).

D) DASHBOARD — THREAT OVERLAY (modify multiple dashboard files)

   1. FleetMap.jsx:
      - Color-code contact markers by threat level:
        none=gray, detected=yellow, warning=orange, critical=red (pulsing)
      - Detection range ring: faint circle at 8000m around fleet centroid
      - Warning range ring: amber circle at 5000m
      - Critical range ring: red circle at 2000m
      - Only show rings when contacts exist (don't clutter empty map)

   2. MissionStatus.jsx:
      - When threat_level is "warning" or "critical", show alert:
        "⚠ THREAT: bogey-1 — 3.2km @ 045° CLOSING 4.1 m/s"
      - When intercept_recommended is true, show a prominent
        "INTERCEPT RECOMMENDED" indicator

   3. New: InterceptButton in ContactPanel.jsx or as standalone
      - When intercept_recommended is true, show a pulsing red button:
        "INTERCEPT bogey-1"
      - On click: POST /api/command-direct with an intercept command
        using the recommended target's position
      - This is the "human approves" step in human-on-the-loop autonomy

   4. MissionLog.jsx:
      - Log auto-actions: "AUTO: Eagle-1 tracking bogey-1 (warning range)"
      - Log threat level changes: "THREAT: bogey-1 escalated to CRITICAL"

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT auto-dispatch surface vessels — only the drone auto-responds.
  Surface vessel intercept requires operator approval (the button).
- Do NOT modify the contact motion model
- Do NOT add complex threat classification (friend/foe) — all contacts
  are threats for now
- Do NOT run threat detection every single step — every 1-2 seconds
  (4-8 steps) is sufficient
- Do NOT break existing intercept flow — manual "intercept" commands
  must still work exactly as before

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

New file: tests/test_threat_detector.py

1. test_no_contacts_no_threats:
   No contacts → empty threat assessment list

2. test_contact_out_of_range:
   Contact at 10000m → threat_level "none"

3. test_contact_detected_range:
   Contact at 6000m → threat_level "detected", action "monitor"

4. test_contact_warning_range:
   Contact at 3000m → threat_level "warning", action "track"

5. test_contact_critical_range:
   Contact at 1500m → threat_level "critical", action "intercept"

6. test_closing_rate_computation:
   Contact heading toward fleet → closing_rate is negative (closing)
   Contact heading away → closing_rate is positive (opening)

7. test_auto_drone_retask_on_warning:
   Fleet idle, contact enters warning range → drone pattern changes to TRACK

8. test_no_auto_retask_during_active_mission:
   Fleet executing intercept → drone NOT re-tasked on new contact warning

9. test_intercept_recommended_flag:
   Contact at critical range → fleet_manager.intercept_recommended is True

10. test_threat_in_fleet_state:
    Spawn contact at 3000m → get_fleet_state() includes threat assessment data

Run: .venv/bin/python -m pytest tests/ -v

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. src/fleet/threat_detector.py — ThreatAssessment + assess_threats()
2. fleet_manager.py — threat detection in step(), auto-drone retask
3. fleet_manager.py — threat data in get_fleet_state()
4. Dashboard — threat-colored contacts, range rings, intercept recommendation
5. 10 new tests
6. Full test suite passes — no regressions
7. Commit when done

DEMO STORY:
  Fleet is idle at base. Contact spawned at 9000m. Dashboard shows "detected"
  (yellow marker). Contact closes. At 5000m, drone auto-launches to track
  (cyan trail toward red marker). At 2000m, dashboard flashes
  "INTERCEPT RECOMMENDED" with a red button. Operator clicks it. Fleet
  dispatches with predictive intercept. All without typing a single command.
```

---

## AUDIT 10: Comms-Denied Autonomous Behavior
**Goal**: When communications are denied, the fleet continues operating on pre-briefed behaviors instead of going dead. The `comms_lost_behavior` field already exists in FleetCommand but is never triggered.

```
Execute Audit 10 — Comms-Denied Autonomy for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 10.

COMPLETED AUDITS: Audits 1-9 complete. Predictive intercept + auto threat
response working. 147+ tests passing. Do NOT break them.

YOUR TASK: Add a COMMS DENIED mode where the operator loses the ability to
send commands, but the fleet continues operating autonomously on last orders.

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

GPS-denied simulates losing satellite navigation. But in contested
environments, the MORE likely failure is COMMUNICATIONS denial — the
operator can't reach the fleet at all. Jamming, distance, terrain.

The FleetCommand schema already has: comms_lost_behavior = "return_to_base"
This field is stored but NEVER READ or ACTED ON by any code.

Currently if you "deny comms" there's no mechanism for it — the WebSocket
just keeps streaming. There's no simulation of command link loss.

For a defense demo, this is the money shot: "I jam comms, and the fleet
keeps operating." It shows the system doesn't need a human in the loop
for every decision.

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

A) COMMS MODE STATE (add to fleet_manager.py)

   Add a comms_mode attribute: "full" or "denied"
   Add a comms_denied_since timestamp (or None)
   Add a comms_denied_timeout: float = 300.0 (5 minutes default)

   When comms_mode == "denied":
   - POST /api/command and POST /api/command-direct should return
     {"success": false, "error": "COMMS DENIED — fleet operating autonomously"}
   - POST /api/return-to-base should also be blocked
   - The fleet continues executing whatever it was doing
   - Contact spawn/remove should still work (that's a sim control, not C2)
   - GPS mode changes should still work (that's environmental, not C2)

B) AUTONOMOUS BEHAVIORS WHEN COMMS DENIED (modify step() in fleet_manager.py)

   When comms_mode == "denied", the fleet executes pre-briefed logic:

   1. IF fleet has an active mission → CONTINUE executing it
      - Intercept: keep navigating to intercept point (with replanning)
      - Patrol: keep following waypoints
      - Any mission: continue as normal

   2. IF fleet is IDLE when comms are denied → execute comms_lost_behavior
      - "return_to_base" (default): call self.return_to_base()
      - "hold_position": set all vessels to LOITER at current position
      - "continue_mission": do nothing, wait for comms restore

   3. IF comms denied for longer than comms_denied_timeout (300s) AND
      fleet is still executing a mission → switch to comms_lost_behavior
      - This simulates "mission complete but can't report back, fall back
        to standing orders"
      - When vessels reach IDLE after mission waypoints exhausted, trigger
        comms_lost_behavior

   4. THREAT RESPONSE still operates autonomously (from Audit 9)
      - Drone auto-tracks on warning range
      - But intercept_recommended flag has no one to click it
      - Add: if comms_denied AND intercept_recommended AND
        comms_denied_timeout has elapsed → auto-dispatch intercept
        (this is the "fully autonomous" escalation)

C) API ENDPOINT (add to routes.py)

   POST /api/comms-mode
   Body: { "mode": "full" | "denied" }
   Response: { "comms_mode": "full"|"denied" }

   When switching to denied:
   - Record timestamp
   - Block command endpoints
   - Fleet continues on autopilot

   When switching back to full:
   - Log "COMMS RESTORED — X seconds denied"
   - Resume normal command acceptance

D) COMMS STATE IN FLEET STATE (modify get_fleet_state())

   Include in WebSocket stream:
   - comms_mode: "full" | "denied"
   - comms_denied_duration: float (seconds since denial, or 0)
   - autonomous_action: str | null (what the fleet is doing on its own)

E) DASHBOARD — COMMS DENIED OVERLAY

   1. New toggle: CommsDeniedToggle.jsx (or extend GpsDeniedToggle)
      - Button to toggle comms mode
      - POST /api/comms-mode on click
      - Colors: FULL=green, DENIED=red

   2. When comms denied:
      - Header bar turns red/amber with "COMMS DENIED" flashing
      - CommandPanel input is disabled with overlay: "COMMS DENIED"
      - RTB button is disabled with same overlay
      - MissionStatus shows: "AUTONOMOUS — [executing last orders]"
      - Timer showing duration of comms denial

   3. When comms restored:
      - Brief green flash "COMMS RESTORED"
      - All controls re-enabled
      - MissionLog entry: "COMMS RESTORED after Xs"

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT actually disconnect the WebSocket — the operator can still
  OBSERVE the fleet (imagine a separate sensor feed), they just can't
  COMMAND it. The C2 link is denied, not the surveillance link.
- Do NOT modify schemas.py
- Do NOT make comms denial affect GPS mode — they are independent failures
- Do NOT make autonomous intercept happen instantly — there should be a
  delay (the timeout) before fully autonomous escalation
- Do NOT change existing command dispatch logic — just gate it behind
  comms_mode check

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

New file: tests/test_comms_denied.py

1. test_comms_denied_blocks_commands:
   Set comms denied → attempt command dispatch → verify blocked with error

2. test_comms_denied_fleet_continues_mission:
   Start patrol → set comms denied → run 100 steps → verify fleet still
   EXECUTING (not stopped)

3. test_comms_denied_idle_triggers_rtb:
   Fleet idle → set comms denied → run 10 steps → verify fleet RETURNING

4. test_comms_denied_timeout_triggers_fallback:
   Fleet executing → set comms denied → run enough steps to exceed timeout
   → verify comms_lost_behavior triggered

5. test_comms_restored_accepts_commands:
   Set comms denied → restore → attempt command → verify accepted

6. test_comms_denied_contacts_still_work:
   Set comms denied → spawn contact → verify contact appears

7. test_comms_denied_in_fleet_state:
   Set comms denied → get_fleet_state() includes comms_mode and duration

8. test_comms_denied_duration_tracks:
   Set comms denied → run 40 steps (10s) → verify duration ~10s

Run: .venv/bin/python -m pytest tests/ -v

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. fleet_manager.py — comms_mode state, command gating, autonomous behaviors
2. routes.py — POST /api/comms-mode endpoint
3. fleet_manager.py — comms state in get_fleet_state()
4. Dashboard — comms toggle, disabled controls overlay, status indicator
5. 8 new tests
6. Full test suite — no regressions
7. Commit when done

DEMO STORY:
  Fleet executing intercept mission. Operator toggles COMMS DENIED.
  Header turns red: "COMMS DENIED." Command panel greys out. Fleet keeps
  pursuing the contact. Drone keeps tracking. After 5 minutes, fleet
  completes intercept and autonomously returns to base (comms_lost_behavior).
  Operator restores comms. Green flash: "COMMS RESTORED." Controls re-enabled.
  The fleet operated for 5 minutes with zero human input.
```

---

## AUDIT 11: Cross-Domain Kill Chain — Drone Hands Off to Fleet
**Goal**: Drone detects and tracks a contact, provides targeting data to surface vessels, fleet converges based on drone's sensor feed. This demonstrates multi-domain coordination and is the core of JADC2.

```
Execute Audit 11 — Cross-Domain Kill Chain for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 11.

COMPLETED AUDITS: Audits 1-10 complete. Predictive intercept, auto threat
response, comms-denied autonomy all working. 147+ tests passing.

YOUR TASK: Make the drone provide targeting data to surface vessels, creating
a sensor-to-effector loop across domains (air → surface).

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

Currently the drone and surface vessels operate independently. They happen
to be on the same map, but:
- The drone doesn't "see" contacts or relay information
- Surface vessels don't receive targeting data from the drone
- There's no handoff between domains
- The drone patterns (ORBIT, SWEEP, TRACK, STATION) are geometric — they
  don't interact with the contact system

A defense CEO would ask: "Do they talk to each other?"
The answer is no. This is the biggest architectural gap.

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

A) DRONE SENSOR MODEL (modify drone_dynamics.py or new: src/fleet/drone_sensor.py)

   The drone has a simulated sensor with a detection range:

   DRONE_SENSOR_RANGE = 3000.0  # meters — drone can "see" contacts within 3km
   DRONE_SENSOR_FOV = 120.0     # degrees — forward-looking sensor cone

   def drone_detect_contacts(drone_x, drone_y, drone_heading,
                              contacts: dict) -> List[str]:
       """Return contact_ids visible to the drone's sensor."""
       For each contact:
       - Compute distance from drone
       - Compute bearing from drone
       - If distance < SENSOR_RANGE and bearing within FOV: detected
       Return list of detected contact_ids

   When the drone is in TRACK pattern and within sensor range of a contact:
   - The drone "locks on" — it has a targeting solution
   - Store: drone.tracked_contact_id = contact_id
   - Store: drone.target_bearing, drone.target_range (updated each step)

B) TARGETING DATA RELAY (modify fleet_manager.py step())

   When the drone has a tracked contact:
   1. Compute contact position from drone's perspective
      (drone_x + range * cos(bearing), drone_y + range * sin(bearing))
   2. Store as drone.relayed_target = {contact_id, x, y, bearing, range, confidence}
   3. Surface vessels can "receive" this targeting data

   In step(), when the drone has a locked target AND fleet is executing
   intercept AND continuous replanning is active:
   - Use the DRONE'S tracked position for intercept replanning
     (instead of the omniscient contact.x, contact.y from the sim)
   - This creates the relay chain: drone sensor → drone targeting → fleet nav

   For now, the relay is perfect (no noise, no latency). Future enhancement
   could add sensor noise proportional to range.

C) AUTOMATIC HANDOFF SEQUENCE (modify fleet_manager.py)

   The full kill chain sequence (triggered by threat detector from Audit 9):

   Phase 1 — DETECT: Contact enters detection range (8km).
     Fleet logs: "CONTACT DETECTED: bogey-1 at 7.2km"
     No auto-action yet.

   Phase 2 — TRACK: Contact enters warning range (5km).
     Drone auto-tasks to TRACK the contact (Audit 9).
     Fleet logs: "AUTO: Eagle-1 vectored to track bogey-1"

   Phase 3 — LOCK: Drone gets within sensor range (3km) of contact.
     Drone achieves targeting solution.
     Fleet logs: "LOCK: Eagle-1 tracking bogey-1 — bearing 042° range 2.8km"
     Dashboard shows targeting data on map (bearing line from drone to contact)

   Phase 4 — ENGAGE: Operator approves intercept (or auto after comms timeout).
     Surface vessels dispatch to intercept point using DRONE's targeting data.
     Fleet logs: "ENGAGE: Fleet intercepting bogey-1 via Eagle-1 targeting"

   Phase 5 — CONVERGE: Fleet closes on contact while drone maintains track.
     Drone updates targeting. Fleet replans based on drone's data.
     When fleet is within 500m of contact: "INTERCEPT COMPLETE"

   Store the current phase in fleet_manager as self.kill_chain_phase (str or None).
   Include in FleetState for dashboard display.

D) DASHBOARD — KILL CHAIN VISUALIZATION

   1. FleetMap.jsx:
      - When drone has a targeting lock, draw a line from drone to contact
        (yellow, thin, labeled "TRACK")
      - When fleet is engaging, draw lines from fleet to intercept point
        (red, converging arrows)
      - Show drone's sensor cone as a semi-transparent wedge (optional,
        nice-to-have)

   2. MissionStatus.jsx:
      - Show kill chain phase: "PHASE 3: DRONE LOCK — bogey-1"
      - Show targeting data: "TGT: bogey-1 via Eagle-1 — 2.8km @ 042°"

   3. MissionLog.jsx:
      - Log each phase transition with timestamp

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT add actual radar/sensor physics — simple range+FOV check is enough
- Do NOT add sensor noise yet — perfect relay first, noise is a future enhancement
- Do NOT modify DroneCoordinator patterns — just add sensor awareness on top
- Do NOT modify schemas.py
- Do NOT break the ability to manually dispatch intercepts without the kill chain

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

New file: tests/test_kill_chain.py

1. test_drone_detects_contact_in_range:
   Drone at (0,0), contact at (2000, 0) → detected

2. test_drone_no_detect_out_of_range:
   Drone at (0,0), contact at (5000, 0) → not detected

3. test_drone_no_detect_outside_fov:
   Drone heading east, contact behind it → not detected

4. test_drone_tracks_and_relays:
   Drone in TRACK near contact → tracked_contact_id set, relay data available

5. test_kill_chain_phase_progression:
   Spawn contact at 9000m, run steps, verify phase transitions:
   None → DETECT → TRACK → LOCK → (await engage)

6. test_fleet_uses_drone_targeting:
   Drone has lock on contact → fleet replan uses drone's relayed position

7. test_kill_chain_in_fleet_state:
   Active kill chain → get_fleet_state() includes phase and targeting data

Run: .venv/bin/python -m pytest tests/ -v

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. Drone sensor model (detection range + FOV)
2. Targeting data relay from drone to fleet_manager
3. Kill chain phase state machine in fleet_manager
4. Fleet replanning uses drone targeting data
5. Dashboard — targeting lines, phase display, log entries
6. 7 new tests
7. Full test suite — no regressions
8. Commit when done

DEMO STORY:
  Fleet idle. Contact spawned at 9km. "CONTACT DETECTED" appears in log.
  Contact closes to 5km. Drone auto-launches to track. Cyan trail streaks
  toward red marker. Drone gets within 3km: "LOCK — Eagle-1 tracking bogey-1."
  Yellow targeting line appears from drone to contact. Operator clicks
  "INTERCEPT." Fleet dispatches to predicted intercept point. Blue arrows
  converge. Drone maintains overhead track. Fleet arrives: "INTERCEPT COMPLETE."
  The entire sequence played out across air and surface domains.
```

---

## AUDIT 12: Decision Audit Trail — Explainable Autonomy
**Goal**: Log not just what happened, but WHY. Every autonomous decision gets a human-readable rationale. This is non-negotiable for defense — operators must trust the system.

```
Execute Audit 12 — Decision Audit Trail for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 12.

COMPLETED AUDITS: Audits 1-11 complete. Full kill chain working.
147+ tests passing. Do NOT break them.

YOUR TASK: Add explainable decision logging — every autonomous action the
system takes must be accompanied by a human-readable rationale showing WHY.

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

The system now makes autonomous decisions (drone auto-track, threat
assessment, intercept prediction, comms-denied fallback). But when these
happen, the only feedback is "alpha → EXECUTING." The operator has no
idea WHY alpha was chosen, why the intercept point is where it is, or
why the drone went to track that specific contact.

Defense systems require EXPLAINABILITY. An autonomous action that can't
be explained is an autonomous action that won't be trusted. Every
operator, every commander, every review board will ask: "Why did it do
that?"

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

A) DECISION LOG DATA STRUCTURE (new: src/fleet/decision_log.py)

   class DecisionEntry:
       timestamp: float
       decision_type: str    # "intercept_solution", "threat_assessment",
                             # "auto_track", "comms_fallback", "replan",
                             # "asset_allocation"
       action_taken: str     # "Dispatched alpha to (4200, 1800)"
       rationale: str        # "Alpha selected: closest to target (2.1km),
                             #  heading within 15° of intercept bearing,
                             #  ETA 4m 22s. Bravo rejected: 3.8km, 
                             #  unfavorable heading (87° off)."
       assets_involved: List[str]
       alternatives_considered: List[str]  # what was NOT chosen and why

   class DecisionLog:
       entries: List[DecisionEntry]  # bounded ring buffer, max 200

       def log_decision(self, decision_type, action, rationale, assets, alternatives)
       def get_recent(self, n=20) -> List[DecisionEntry]
       def get_by_type(self, decision_type) -> List[DecisionEntry]

B) INSTRUMENT ALL AUTONOMOUS DECISIONS

   Go through every place the system makes a choice and add a decision log
   entry. These are the key decision points:

   1. INTERCEPT PREDICTION (fleet_manager.py — compute_intercept_point):
      Log: "Intercept solution computed. Target bogey-1 at (3000, 1500)
      heading 225° at 1.5 m/s. Fleet centroid at (500, 200). Predicted
      intercept at (2400, 1100), ETA 280s. Convergence angle: 32°."

   2. ASSET ALLOCATION (fleet_manager.py — dispatch_command):
      For each asset dispatched, log why:
      "Alpha dispatched to (2400, 1100): distance 2.1km, heading offset 15°,
       ETA 4m22s — best candidate."
      "Bravo dispatched to (2600, 1100): echelon offset from lead (Alpha)."
      "Eagle-1 dispatched to TRACK bogey-1: fastest asset (15 m/s), air
       domain provides overhead surveillance."

   3. THREAT DETECTION (threat_detector.py — assess_threats):
      Log: "bogey-1 assessed: distance 3200m (WARNING range), closing at
      2.8 m/s, bearing 045° from fleet. Action: recommend TRACK."

   4. AUTO-DRONE RETASK (fleet_manager.py — auto-response):
      Log: "AUTO-TRACK decision. Eagle-1 re-tasked from STATION to TRACK
      bogey-1. Reason: contact entered warning range (3200m). Fleet was
      idle — no active mission conflict."

   5. COMMS-DENIED FALLBACK (fleet_manager.py):
      Log: "COMMS FALLBACK: comms denied for 312s, exceeding 300s timeout.
      Standing orders: return_to_base. Dispatching all assets to home."

   6. REPLAN (fleet_manager.py — continuous replan):
      Log: "Replan triggered. Intercept point shifted 180m (from (2400,1100)
      to (2220,1020)). Target moved since last plan. Fleet waypoints updated."

C) DECISION LOG API ENDPOINT (add to routes.py)

   GET /api/decisions?limit=20&type=intercept_solution
   Returns recent decision entries, optionally filtered by type.

D) DASHBOARD — DECISION PANEL (new: DecisionPanel.jsx or extend MissionLog)

   Display decision log entries in a scrollable panel:
   - Each entry shows: timestamp, decision_type badge, action (bold),
     rationale (expandable), assets involved
   - Color-code by type: intercept=red, threat=amber, auto=cyan, comms=orange
   - Most recent at top
   - Expandable: click to see alternatives_considered

   This can replace or augment the existing MissionLog, or be a new tab
   in the sidebar.

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT use the existing SQLite mission_logger for this — that's for
  event replay. The decision log is for real-time explainability.
- Do NOT log every step() tick — only log when a DECISION is made
- Do NOT modify schemas.py
- Do NOT make the rationale computation expensive — it's string formatting
  of data you already have

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

New file: tests/test_decision_log.py

1. test_decision_log_stores_entries:
   Log 3 decisions → get_recent(3) returns all 3

2. test_decision_log_bounded:
   Log 250 decisions → length is 200 (ring buffer)

3. test_intercept_logs_rationale:
   Dispatch intercept → decision log has entry with type "intercept_solution"
   and non-empty rationale containing distance and ETA

4. test_threat_assessment_logs:
   Contact at warning range → decision log has "threat_assessment" entry

5. test_auto_track_logs_reason:
   Drone auto-tracks → decision log has "auto_track" entry explaining why

6. test_decision_log_api:
   GET /api/decisions returns JSON list of entries

Run: .venv/bin/python -m pytest tests/ -v

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. src/fleet/decision_log.py — DecisionEntry + DecisionLog classes
2. fleet_manager.py — instrument all decision points
3. routes.py — GET /api/decisions endpoint
4. Dashboard — decision panel with rationale display
5. 6 new tests
6. Full test suite — no regressions
7. Commit when done

DEMO STORY:
  During the intercept demo, the decision panel shows WHY each choice was
  made in real time. "Alpha selected: closest asset, 15° heading offset."
  "Intercept point: (2400, 1100) — target predicted 280s ahead." "Drone
  re-tasked: contact entered warning zone." The operator can SEE the AI
  thinking. This is the trust-builder.
```

---

## AUDIT 13: Mission-Specific Behaviors — Make Each Mission Type Matter
**Goal**: The 6 mission types (PATROL, SEARCH, ESCORT, LOITER, AERIAL_RECON, INTERCEPT) should each produce distinct, intelligent fleet behavior instead of all being "go to waypoint."

```
Execute Audit 13 — Mission-Specific Behaviors for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 13.

COMPLETED AUDITS: Audits 1-12 complete. Full autonomous C2 system working.
147+ tests passing. Do NOT break them.

YOUR TASK: Make each of the 6 mission types produce visually distinct and
tactically appropriate fleet behavior.

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

Right now, ALL mission types do the same thing: go to waypoints in a
straight line. PATROL and SEARCH look identical. ESCORT doesn't escort
anything. LOITER doesn't loiter. The mission_type field is stored in
fleet_manager but IGNORED during execution.

A demo that shows "intercept" and "patrol" looking exactly the same is a
demo that shows you didn't implement mission behaviors.

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

Modify fleet_manager.py dispatch_command() and step() to handle each
mission type differently. The changes should be MINIMAL and build on
existing infrastructure.

A) PATROL — Continuous Loop

   Current: Go to waypoints, stop at last one, go IDLE.
   New behavior: When reaching the last waypoint, loop back to the first.
   Continue indefinitely until RTB or new command.

   Implementation in step():
   When mission == PATROL and vessel reaches last waypoint:
     - Reset i_wpt to 0 (loop back to first waypoint)
     - Don't go IDLE — stay EXECUTING
   This creates a visible patrol loop on the map.
   Drone: ORBIT pattern around the patrol centroid.

B) SEARCH — Expanding Sweep

   Current: Go to waypoints (same as patrol).
   New behavior: Generate a lawnmower/zigzag search pattern from the
   commanded area.

   Implementation in dispatch_command():
   When mission == SEARCH:
     - Take the commanded waypoint as the center of the search area
     - Generate a zigzag pattern: 4-6 waypoints in a raster scan
       covering a 500m x 500m area centered on the target
     - Each vessel gets a slightly offset pattern (parallel tracks
       with spacing_meters between them)
   Drone: SWEEP pattern over the same area.

   The waypoint generation can be simple:
     base_x, base_y = commanded waypoint
     for i in range(num_legs):
       if i % 2 == 0: add (base_x + offset, base_y + i * leg_spacing)
       else: add (base_x - offset, base_y + i * leg_spacing)

C) ESCORT — Follow a Friendly Contact

   Current: Go to waypoints (same as all others).
   New behavior: Maintain formation around a designated friendly unit.

   Implementation:
   When mission == ESCORT:
     - The first waypoint is treated as the escort target's current position
     - In step(), vessels maintain their formation offset RELATIVE to the
       escort point (which could be another vessel or a moving waypoint)
     - For the demo: escort a contact (the contact model already exists)
     - Vessels match the contact's speed and heading, maintaining formation

   This is the simplest approach: in step(), if mission == ESCORT and
   contacts exist, recompute desired waypoint as:
     escort_x = contact.x + formation_offset_x
     escort_y = contact.y + formation_offset_y
   This keeps the fleet "attached" to the contact.

D) LOITER — Station-Keeping Pattern

   Current: Go to waypoint, stop, go IDLE.
   New behavior: Arrive at waypoint, then orbit in a small circle.

   Implementation in step():
   When mission == LOITER and vessel reaches the waypoint:
     - Don't go IDLE
     - Switch to a small orbit: generate 4 waypoints in a 200m circle
       around the loiter point
     - Loop through them continuously (like PATROL but in a circle)
   Drone: ORBIT pattern at the loiter point.

E) AERIAL_RECON — Drone-Primary Mission

   Current: Same as everything else.
   New behavior: Drone does a wide SWEEP while surface vessels hold position.

   Implementation in dispatch_command():
   When mission == AERIAL_RECON:
     - Drone: SWEEP pattern over a large area (1000m x 1000m)
     - Surface vessels: move to a holding point near the recon area and
       LOITER (small orbit)
     - Surface vessels provide security while drone does the actual work

F) INTERCEPT — Already enhanced (Audit 8)
   Predictive interception with continuous replanning. No changes needed.

────────────────────────────────────────────────────────────────────
DASHBOARD CHANGES
────────────────────────────────────────────────────────────────────

- MissionStatus.jsx should show the mission type with a distinctive icon
  or color for each type
- Patrol loops should be visible as repeating trail patterns on the map
- Search zigzags should be visible as the fleet sweeps
- No new components needed — the existing map and status bar handle this

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT modify schemas.py
- Do NOT add new mission types — use the existing 6
- Do NOT make the behaviors complex — simple geometric patterns are fine
- Do NOT break the intercept flow (Audit 8)
- Do NOT change how dispatch_command handles formation offsets —
  layer mission behaviors ON TOP of existing formation logic

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

Add to tests/test_fleet_manager.py or new tests/test_mission_behaviors.py:

1. test_patrol_loops_back:
   Dispatch patrol with 2 waypoints. Run enough steps for vessel to reach
   last waypoint. Verify it goes back to first waypoint (i_wpt resets).
   Verify status remains EXECUTING (not IDLE).

2. test_search_generates_zigzag:
   Dispatch search to (500, 500). Verify generated waypoints form a
   zigzag pattern (alternating x values, increasing y values).

3. test_loiter_orbits_after_arrival:
   Dispatch loiter to (300, 300). Run steps until arrival. Verify vessel
   does NOT go IDLE. Verify position stays within 300m of loiter point
   after 200 more steps.

4. test_escort_follows_contact:
   Spawn contact moving east. Dispatch escort. Run 200 steps. Verify
   fleet centroid tracks the contact's movement direction.

5. test_aerial_recon_drone_sweeps:
   Dispatch aerial_recon. Verify drone has SWEEP pattern. Verify surface
   vessels are near the area (not dispatched to distant waypoints).

6. test_intercept_unchanged:
   Verify existing intercept tests still pass (regression check).

Run: .venv/bin/python -m pytest tests/ -v

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. fleet_manager.py — mission-specific logic in dispatch_command() and step()
2. Patrol loops, search zigzags, loiter orbits, escort follows, recon sweeps
3. 6 new tests
4. Full test suite — no regressions
5. Commit when done

DEMO STORY:
  Show all 5 non-intercept missions in quick succession:
  "All vessels patrol sector in column" → visible loop pattern
  "Search the area around 800 400" → zigzag sweep visible
  "Loiter at 500 500" → small orbit pattern
  "Escort the contact" → fleet shadows the moving target
  "Aerial recon of sector north" → drone sweeps, vessels hold
  Each mission looks DIFFERENT on the map. That's the point.
```

---

## COMPLETED AUDIT ARCHIVE

The detailed prompts for completed audits are preserved below for reference.
These audits are DONE — do not re-execute them.

<details>
<summary>AUDIT 1: Navigation Circling (DONE)</summary>

**Status**: DONE — Waypoint completion fixed. Vessels reach IDLE.

AUDIT TASK: Fix the vessel circling/endless-loop navigation bug.

CONTEXT: Vessels were going in endless circles instead of reaching waypoints.
Root cause: waypoint_selection() never advanced past the last waypoint.

FIXED:
- `src/navigation/planning.py` — waypoint_selection() now advances i_wpt past
  the last waypoint (i_wpt = j + 1), allowing completion detection
- `src/fleet/fleet_manager.py` — Added `continue` after setting IDLE
- `tests/test_fleet_manager.py` — Added test_vessel_reaches_waypoint_and_goes_idle

Remaining trajectory issues moved to Audit 6.
</details>

<details>
<summary>AUDIT 6: Vessel Timing & Trajectory (DONE — commit 054c6cf)</summary>

**Status**: DONE — All 6 issues fixed + 3 trajectory tests added.

| File | Issue | Fix |
|------|-------|-----|
| controller.py | Heading wrapping | `(e_psi + pi) % (2*pi) - pi` |
| fleet_manager.py | Speed during turns | `max(0.3, 1.0 - 0.7 * err/pi)` |
| vessel_dynamics.py | Yaw bias noise | `0.1 * randn()` (was 0.5) |
| planning.py | Acceptance circle | 27m (was 108m) |
| planning.py | Pure pursuit fallback | Within 500m, steer directly |

Tests: test_vessel_does_not_overshoot_on_uturn, test_return_to_base_no_loop,
test_vessel_straight_line_accuracy.
</details>

<details>
<summary>AUDIT 7: LLM Command Quality (DONE — commit 478a866)</summary>

**Status**: DONE — Waypoint clamping, asset ID validation, timeout, retry variation.

Changes: ollama_client.py (expanded prompt, 30s timeout, varied retries),
fleet_commander.py (waypoint bounds ±5000m, asset ID validation, dispatch summary).
</details>

<details>
<summary>AUDIT 2: Land Avoidance (DONE — commit e46962c)</summary>

**Status**: DONE — Cape Cod polygon + land_check.py + heading correction.

New file: src/navigation/land_check.py — 24-vertex Cape Cod polygon, ray-casting
point-in-polygon, land_repulsion_heading() called in fleet_manager step().
17 tests in test_land_check.py. 136 total tests passing.
</details>

<details>
<summary>AUDIT 4: Mission Lifecycle / Intercept (DONE — commit 098222b)</summary>

**Status**: DONE — INTERCEPT mission type, Contact model, target simulation.

Schema additions: INTERCEPT MissionType, Contact model, FleetState.contacts.
fleet_manager.py: contacts dict, spawn/remove, straight-line step, API endpoints.
5 tests in test_intercept.py. 141 total tests passing.
</details>

<details>
<summary>AUDIT 3: GPS-Denied Dead Reckoning (DONE — commit c2caeed)</summary>

**Status**: DONE — DeadReckoningState, DENIED mode affects navigation, drift accumulates.

Schema: DENIED added to GpsMode. gps_denied.py: dead_reckon_step().
fleet_manager.py: navigation uses DR position in DENIED mode, physics uses true.
6 tests in test_gps_denied.py. 147 total tests passing.
</details>

<details>
<summary>AUDIT 5: Dashboard C2 Ops Center (DONE — commit dd49d20)</summary>

**Status**: DONE — Full functional C2 dashboard.

New components: RTBButton, ContactPanel, MissionStatus, ScenarioPanel.
Modified: FleetMap (contact markers, trails, coastline overlay),
GpsDeniedToggle (3-state FULL/DEGRADED/DENIED), App.jsx (wired everything).
pnpm build clean. 147 backend tests unaffected.
</details>

<details>
<summary>FUTURE: Rhode Island Harbor Navigation Roadmap</summary>

Full roadmap preserved from original plan:
- Phase 1: RI Coastline Data (Narragansett Bay polygons)
- Phase 2: Channel Waypoint Graph (A* through harbor)
- Phase 3: Target/Contact Model (DONE — Audit 4)
- Phase 4: Land-Aware Return-to-Base
- Phase 5: Slow-Speed Harbor Maneuvering
- Phase 6: LLM + Dashboard Updates

Dependency: Phase 1 → 2 → 4 → 5. Phase 3 independent. Phase 6 last.
This is deferred until the core autonomy features (Audits 8-13) are complete.
</details>

---

## THE DEMO SCRIPT — "THE 3-MINUTE HIRE"

After all audits (8-13) are complete, this is the demo video that gets the job:

**0:00 — OPENING SHOT**
Map loads. Dark theme. Cape Cod coastline visible. 3 blue vessel markers + 1 cyan drone at base. Header: "LOCALFLEET C2 DASHBOARD." Status: "STANDBY."

**0:15 — VOICE COMMAND: PATROL**
Operator speaks: "All vessels, patrol sector northeast in echelon."
Fleet moves out in formation. Drone orbits ahead. Trail lines draw on map.
Decision log: "Echelon formation applied. Alpha lead, bravo +200m offset..."

**0:30 — CONTACT APPEARS**
Bogey-1 spawned at 9km. Yellow marker appears. Mission log: "CONTACT DETECTED: bogey-1 at 8.7km."

**0:45 — AUTO-TRACK**
Contact closes to 5km. Drone auto-retasks. Cyan trail streaks toward contact. Log: "AUTO: Eagle-1 vectored to track bogey-1 — warning range."
Decision log: "Eagle-1 selected: only air asset, fastest platform (15 m/s)."

**1:00 — DRONE LOCK**
Drone reaches sensor range. Yellow targeting line appears. "LOCK: Eagle-1 tracking bogey-1 — 2.8km @ 042°." Phase indicator: "PHASE 3: LOCK."

**1:15 — INTERCEPT COMMAND**
Dashboard flashes "INTERCEPT RECOMMENDED." Operator clicks red button.
Fleet dispatches to PREDICTED intercept point (ahead of target). Blue arrows converge. "Intercept solution: target at 4.2km heading 225°, fleet dispatching to (2400, 1100), ETA 5m12s."

**1:30 — GPS DENIED**
Mid-intercept, operator toggles GPS DENIED. Red uncertainty rings grow. "GPS: DENIED — DR active." Fleet continues on dead reckoning. Drift counter ticking.

**1:45 — COMMS DENIED**
Operator toggles COMMS DENIED. Header turns red. Controls grey out. "COMMS DENIED — fleet autonomous." Fleet keeps closing on target. Drone keeps tracking.

**2:15 — CONVERGENCE**
Fleet arrives at intercept point. Contact and vessels converge on map. "INTERCEPT COMPLETE." All under GPS-denied + comms-denied conditions.

**2:30 — COMMS RESTORED**
Operator restores comms. Green flash. "COMMS RESTORED after 45s." RTB button re-enabled. Operator clicks RTB. Fleet turns home.

**2:45 — GPS RESTORED**
GPS restored. Uncertainty rings collapse. DR drift: 42m. Fleet navigates home cleanly.

**3:00 — CLOSING SHOT**
All assets IDLE at base. Decision panel shows full audit trail of every choice. Cape Cod coastline in the background. Status: "STANDBY."

**THE KICKER (text overlay):**
"Multi-domain autonomous C2. Natural language command. GPS-denied. Comms-denied. Predictive intercept. Cross-domain kill chain. Explainable decisions. Running fully air-gapped on Apple Silicon."
