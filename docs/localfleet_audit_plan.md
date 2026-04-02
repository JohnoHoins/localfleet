
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
| 8 | Audit 8: Predictive Intercept | DONE | `6778446` | 5 intercept prediction tests |
| 9 | Audit 9: Autonomous Threat Response | DONE | `2502bab` | 10 threat detector tests |
| 10 | Audit 10: Comms-Denied Autonomy | DONE | `41808ce` | Comms-denied behavior tests |
| 11 | Audit 11: Cross-Domain Kill Chain | DONE | `412d7b6` | Kill chain phase tests |
| 12 | Audit 12: Decision Audit Trail | DONE | `16fb530` | Decision logging tests |
| 13 | Audit 13: Mission-Specific Behaviors | DONE | `2100d59` | Mission behavior tests |
| — | **V1 Simulation** | DONE | — | 3468 frames, 311 anomalies |
| — | **V2 Simulation (21 tests)** | DONE | — | 21401 frames, 24 PASS / 5 WARN / 0 FAIL |

---

## CRITICAL BLOCKERS & DEPENDENCIES

**READ THIS BEFORE STARTING ANY AUDIT.**

### BLOCKER 1: Audit 9 Work is Uncommitted
`src/fleet/threat_detector.py` and `tests/test_threat_detector.py` are **untracked**.
Changes to `fleet_manager.py`, `App.jsx`, `ContactPanel.jsx`, `FleetMap.jsx`,
`MissionLog.jsx`, `MissionStatus.jsx`, and `ws.py` are **unstaged**.
**Action**: Commit all Audit 9 work before starting Audit 10. Run full test suite first.

### BLOCKER 2: fleet_manager.py God-Class Risk
`step()` already handles 10 responsibilities (physics, GPS-DR, nav, land avoidance,
speed scaling, contacts, intercept replan, threat check, drone step, waypoint completion).
Audits 10-13 each add more. By Audit 13, step() will be unmanageable.
**Action**: Each audit MUST extract new behavior into private methods (`_handle_comms_denied()`,
`_advance_kill_chain()`, `_mission_specific_step()`). step() itself stays as a dispatcher.

### BLOCKER 3: get_fleet_state_dict() Injection Scaling
Currently injects: threat_assessments, intercept_recommended, recommended_target.
Audits 10-13 need: comms_mode, comms_denied_duration, kill_chain_phase, targeting_data,
recent_decisions. All injected into the same dict.
**Action**: Structure injections into namespaced sub-dicts:
```python
data["autonomy"] = {
    "comms_mode": ..., "comms_denied_duration": ...,
    "kill_chain_phase": ..., "targeting_data": ...,
}
data["decisions"] = [...]  # recent decision log entries
```

### BLOCKER 4: Audit 11 Duplicates Audit 9 Threat Logic
Kill chain phases (DETECT/TRACK/LOCK/ENGAGE/CONVERGE) map directly to
threat_detector levels (detected/warning/critical). Building a parallel system
creates divergence.
**Action**: Kill chain phases are DRIVEN BY threat_detector output + drone sensor data.
- `threat_level == "detected"` → kill chain DETECT
- `threat_level == "warning"` + drone auto-tracked → kill chain TRACK
- Drone within sensor range (3km) of contact → kill chain LOCK
- Operator approves (or comms-denied auto-escalation) → kill chain ENGAGE
- Fleet within 500m of contact → kill chain CONVERGE

### BLOCKER 5: ESCORT Mission Needs a Designatable Contact
Audit 13's ESCORT follows a contact. But all contacts are "threats." No friend/foe.
**Action**: Do NOT modify schemas. Use mission semantics: when mission_type == ESCORT,
the target contact is the one to escort (operator picks it). The contact_id can be
passed via the intercept waypoint convention or a new `escort_target` field in
the dispatch logic. The simplest approach: ESCORT treats the closest contact as the
escort target, same way INTERCEPT picks the closest contact to intercept.

### BLOCKER 6: decision_making.py is Dead Code
`src/decision_making/decision_making.py` contains a COLREG classifier that is never
called by any module. It was bypassed by threat_detector.py and reactive_avoidance.py.
**Action**: Leave it alone. Don't integrate, don't delete. It's harmless dead code.
Future audits do not depend on it.

### BLOCKER 7: DroneCoordinator TRACK Pattern is Single-Point
`generate_track_waypoints()` produces ONE point behind the target. For Audit 11's
continuous sensor lock, the drone needs sustained tracking (orbit within sensor range).
**Action**: Audit 11 must update TRACK to generate an orbit around the contact
(reusing `generate_orbit_waypoints()` centered on contact position), refreshed each
threat check cycle. This keeps the drone within sensor FOV.

### BLOCKER 8: Comms-Denied Needs Last Command Reference
When comms are denied, the fleet needs to reference its last orders. The last
FleetCommand is stored on `fleet_commander.last_command`, not on `fleet_manager`.
**Action**: Audit 10 must store `self.last_command` on fleet_manager when
dispatch_command() is called.

### Dependency Chain
```
Audit 9 (commit first!) → Audit 10 (comms-denied uses intercept_recommended)
                         → Audit 11 (kill chain uses threat_detector + drone sensor)
                         → Audit 12 (instruments ALL decisions from 9-11)
                         → Audit 13 (mission behaviors are independent, could run earlier)
```
Audit 13 has NO dependency on 10-12. It could be executed right after 9.
Consider running 13 before 10 if you want quick visual wins for the demo.

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

## AUDIT 10: Comms-Denied Autonomous Behavior — Fleet Keeps Fighting
**Goal**: When the C2 link goes down, the fleet doesn't go dead — it escalates through an autonomous behavior ladder. This is the money shot for the Havoc demo: "I jam comms, and the fleet keeps operating." Combined with GPS-denied, this shows dual-failure resilience.

```
Execute Audit 10 — Comms-Denied Autonomy for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 10.
READ THE BLOCKERS SECTION — especially Blocker 1 (commit Audit 9 first),
Blocker 3 (state dict injection pattern), and Blocker 8 (last command ref).

COMPLETED AUDITS: Audits 1-9 complete. Predictive intercept + auto threat
response working. Tests passing. Do NOT break them.

YOUR TASK: Add a COMMS DENIED mode where the operator can't send commands
but the fleet continues operating autonomously — and escalates through a
behavior ladder when threats appear with no human to approve.

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

GPS-denied simulates losing satellite navigation. But in contested
environments, the MORE likely failure is COMMUNICATIONS denial — the
operator can't reach the fleet at all. Jamming, distance, terrain.

The FleetCommand schema already has: comms_lost_behavior = "return_to_base"
This field is stored in fleet_manager.comms_lost_behavior but NEVER READ
or ACTED ON by any code path.

Currently if you "deny comms" there's no mechanism — the WebSocket just
keeps streaming, commands still work. There's no simulation of C2 link loss.

A defense CEO's first question after seeing the autonomous threat response:
"What happens if I jam the C2 link?" The answer MUST NOT be "it stops."

THE REAL PROBLEM IS DEEPER: When comms are denied AND a contact reaches
critical range, the intercept_recommended flag (from Audit 9) fires — but
there's no operator to click the button. The fleet needs an autonomous
escalation path that doesn't exist yet.

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

A) COMMS MODE STATE (add to fleet_manager.py __init__)

   self.comms_mode: str = "full"              # "full" or "denied"
   self.comms_denied_since: float | None = None  # time.time() when denied
   self.last_command: FleetCommand | None = None  # CRITICAL: store on dispatch
   self.autonomous_actions: list[str] = []    # log of what fleet did on its own

   In dispatch_command(), FIRST LINE: self.last_command = cmd
   This is needed so the fleet can reference its last orders during denial.

   Methods:
   def set_comms_mode(self, mode: str):
       if mode == "denied" and self.comms_mode != "denied":
           self.comms_denied_since = time.time()
           self.autonomous_actions = []
           # If IDLE, immediately execute comms_lost_behavior
           if not self._has_active_mission():
               self._execute_comms_fallback("idle_on_denial")
       elif mode == "full" and self.comms_mode == "full":
           return  # no-op
       elif mode == "full":
           duration = time.time() - (self.comms_denied_since or time.time())
           self.autonomous_actions.append(
               f"COMMS RESTORED after {duration:.0f}s"
           )
           self.comms_denied_since = None
       self.comms_mode = mode

   def _has_active_mission(self) -> bool:
       return any(v["status"] in (AssetStatus.EXECUTING, AssetStatus.RETURNING)
                  for v in self.vessels.values())

   When comms_mode == "denied":
   - POST /api/command and /api/command-direct → return 503 with
     {"success": false, "error": "COMMS DENIED — fleet operating autonomously",
      "comms_denied_since": <timestamp>, "autonomous_actions": [...]}
   - POST /api/return-to-base → also blocked
   - Contact spawn/remove STILL WORKS (sim control, not C2)
   - GPS mode changes STILL WORK (environmental, not C2)

B) AUTONOMOUS ESCALATION LADDER (modify step() via new method _handle_comms_denied)

   In step(), after threat checking, if comms_mode == "denied":
       self._handle_comms_denied(dt)

   def _handle_comms_denied(self, dt: float):
       """Autonomous behavior when C2 link is down."""
       if self.comms_mode != "denied":
           return
       elapsed = time.time() - (self.comms_denied_since or time.time())

       # LEVEL 1: Continue current mission (always)
       # The fleet keeps doing whatever it was doing — intercept replanning,
       # patrol, etc. This requires NO new code — it's the default.

       # LEVEL 2: Idle fleet executes standing orders
       if not self._has_active_mission():
           self._execute_comms_fallback("idle_during_denial")

       # LEVEL 3: Autonomous threat engagement after timeout
       # This is the critical escalation: with no operator to click
       # "INTERCEPT", the fleet decides on its own after waiting.
       AUTONOMOUS_ESCALATION_DELAY = 60.0  # seconds before auto-engage
       if (self.intercept_recommended
               and elapsed > AUTONOMOUS_ESCALATION_DELAY
               and self.active_mission != MissionType.INTERCEPT):
           self._auto_engage_threat()

   def _execute_comms_fallback(self, trigger: str):
       """Execute comms_lost_behavior standing orders."""
       behavior = self.comms_lost_behavior  # from last FleetCommand
       if behavior == "return_to_base":
           self.return_to_base()
           self.autonomous_actions.append(
               f"AUTO-RTB: {trigger}, standing orders = return_to_base"
           )
       elif behavior == "hold_position":
           # Stop all vessels in place
           for vid, v in self.vessels.items():
               if v["status"] == AssetStatus.IDLE:
                   continue
               v["status"] = AssetStatus.IDLE
               v["desired_speed"] = 0.0
           self.autonomous_actions.append(
               f"AUTO-HOLD: {trigger}, standing orders = hold_position"
           )
       # "continue_mission" = do nothing, wait for comms restore

   def _auto_engage_threat(self):
       """Fully autonomous intercept — no human in the loop."""
       target_id = self.recommended_target
       if not target_id or target_id not in self.contacts:
           return
       contact = self.contacts[target_id]

       # Build a minimal intercept command using the fleet's own state
       from src.schemas import AssetCommand, FleetCommand, Waypoint
       surface_cmds = []
       for vid in self.vessels:
           surface_cmds.append(AssetCommand(
               asset_id=vid, domain=DomainType.SURFACE,
               waypoints=[Waypoint(x=contact.x, y=contact.y)],
               speed=8.0,
           ))
       # Drone stays on TRACK (already auto-tasked by Audit 9)
       cmd = FleetCommand(
           mission_type=MissionType.INTERCEPT,
           assets=surface_cmds,
           formation=self.formation,
       )
       self.dispatch_command(cmd)
       self.autonomous_actions.append(
           f"AUTO-INTERCEPT: {target_id} at ({contact.x:.0f}, {contact.y:.0f}) "
           f"— comms denied {time.time() - (self.comms_denied_since or 0):.0f}s, "
           f"threat at critical range, no operator response"
       )

C) API ENDPOINT (add to routes.py)

   POST /api/comms-mode
   Body: { "mode": "full" | "denied" }

   class CommsModeRequest(BaseModel):
       mode: str  # "full" or "denied"

   Response: {
       "comms_mode": "full"|"denied",
       "autonomous_actions": [...],
       "denied_duration": 0.0
   }

   ALSO: Gate existing command endpoints behind comms check:
   In post_command() and post_command_direct():
     fm = request.app.state.commander.fleet_manager
     if fm.comms_mode == "denied":
         return {"success": False,
                 "error": "COMMS DENIED — fleet operating autonomously"}
   Same for post_return_to_base().

D) COMMS STATE IN FLEET STATE (modify get_fleet_state_dict())

   Structure under data["autonomy"] namespace:
   data["autonomy"] = {
       "comms_mode": self.comms_mode,
       "comms_denied_duration": elapsed_seconds or 0.0,
       "comms_lost_behavior": self.comms_lost_behavior,
       "autonomous_actions": self.autonomous_actions[-10:],  # last 10
       "autonomous_escalation": "engaged" if auto-intercepting else
                                "monitoring" if comms_denied else None,
   }

E) DASHBOARD — COMMS DENIED OVERLAY

   1. CommsDeniedToggle (add to existing GpsDeniedToggle or new component):
      - Button to toggle comms mode: POST /api/comms-mode
      - Colors: FULL=green, DENIED=pulsing red
      - Show alongside GPS toggle (both can be active simultaneously)

   2. When comms denied:
      - Red banner across top: "⛔ COMMS DENIED — AUTONOMOUS MODE"
      - Running timer: "02:34 denied"
      - CommandPanel input DISABLED with red overlay
      - RTB button DISABLED
      - MissionStatus shows: "AUTONOMOUS — executing last orders"
      - If autonomous_actions not empty, show them in MissionLog

   3. DUAL FAILURE state (GPS-denied + comms-denied):
      - Both indicators active (red comms + amber GPS)
      - MissionStatus: "DEGRADED — GPS DENIED + COMMS DENIED"
      - This is the ultimate resilience demo

   4. When comms restored:
      - Brief green flash "COMMS RESTORED after Xs"
      - All controls re-enabled
      - MissionLog shows summary of autonomous actions taken

────────────────────────────────────────────────────────────────────
COORDINATE WITH EXISTING CODE
────────────────────────────────────────────────────────────────────

- fleet_manager.py __init__ (line ~99): comms_lost_behavior is already stored
- fleet_manager.py _check_threats() (line ~349): already sets intercept_recommended
- fleet_manager.py step() (line ~260): add _handle_comms_denied() call AFTER
  the threat check block (line ~341)
- routes.py: add comms-mode endpoint and gate existing endpoints
- ws.py: already uses get_fleet_state_dict() — no changes needed if dict is updated

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT disconnect the WebSocket — operator can OBSERVE but not COMMAND
  (surveillance link vs C2 link are separate)
- Do NOT modify schemas.py
- Do NOT make comms denial affect GPS mode — they are INDEPENDENT failures
- Do NOT auto-engage instantly — the 60s delay is critical for realism
  and gives the operator time to restore comms before full autonomy kicks in
- Do NOT change dispatch_command() internals — just gate the API endpoints
  and add the autonomous escalation path
- Do NOT call _auto_engage_threat() every step — only when intercept_recommended
  transitions to True AND delay has elapsed. Use a flag to prevent re-triggering.

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

New file: tests/test_comms_denied.py

1. test_comms_denied_blocks_dispatch:
   Set comms denied → call fleet_manager.dispatch_command() via route
   → verify 503/error response

2. test_comms_denied_fleet_continues_mission:
   Start patrol → set comms denied → run 100 steps → verify fleet still
   EXECUTING and vessels have moved from initial positions

3. test_comms_denied_idle_triggers_rtb:
   Fleet idle → set comms denied → verify fleet status changes to RETURNING
   within 10 steps

4. test_comms_denied_idle_hold_position:
   Set comms_lost_behavior = "hold_position" → fleet idle → comms denied
   → verify fleet stays IDLE (does not move)

5. test_comms_denied_auto_engage_after_delay:
   Fleet idle → spawn contact at 1500m (critical range) → set comms denied
   → fast-forward past AUTONOMOUS_ESCALATION_DELAY → verify fleet
   dispatched to INTERCEPT autonomously

6. test_comms_denied_no_auto_engage_before_delay:
   Same setup as above but run fewer steps → verify fleet has NOT
   auto-engaged (still waiting for delay)

7. test_comms_restored_accepts_commands:
   Set comms denied → restore → dispatch command → verify accepted

8. test_comms_denied_contacts_still_work:
   Set comms denied → spawn contact → verify contact appears in fleet state

9. test_comms_denied_duration_tracks:
   Set comms denied → wait → verify comms_denied_duration in fleet state

10. test_dual_failure_gps_and_comms:
    Set GPS denied + comms denied → run 100 steps → verify fleet still
    operates (DR navigation + autonomous behavior both active)

11. test_comms_denied_autonomous_actions_logged:
    Trigger auto-RTB → verify autonomous_actions list is non-empty and
    contains the action description

12. test_comms_denied_stores_last_command:
    Dispatch command → verify fleet_manager.last_command is set

Run: .venv/bin/python -m pytest tests/ -v

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. fleet_manager.py — comms_mode state, set_comms_mode(), _handle_comms_denied(),
   _execute_comms_fallback(), _auto_engage_threat(), last_command storage
2. routes.py — POST /api/comms-mode endpoint + gate existing command endpoints
3. fleet_manager.py — comms state in get_fleet_state_dict() under "autonomy" key
4. Dashboard — comms toggle, disabled controls overlay, dual-failure display
5. 12 new tests
6. Full test suite — no regressions
7. Commit when done

DEMO STORY:
  Fleet executing intercept on bogey-1. Operator toggles COMMS DENIED.
  Red banner: "⛔ COMMS DENIED — AUTONOMOUS MODE." Timer starts.
  Command panel greys out. Fleet keeps pursuing. Drone keeps tracking.

  Now toggle GPS DENIED too. Both indicators red. Fleet navigating on
  dead reckoning AND operating without human orders. DR drift visible.

  bogey-2 spawned at 3000m. Threat detector fires. Drone auto-retasks
  to track bogey-2. After 60 seconds with no operator: fleet auto-dispatches
  intercept on bogey-2. MissionLog: "AUTO-INTERCEPT: bogey-2 — comms denied
  95s, threat at critical range, no operator response."

  Operator restores comms. Green flash. "COMMS RESTORED after 142s."
  Autonomous actions summary shown. Controls re-enabled.

  THE FLEET FOUGHT TWO ENGAGEMENTS WITH ZERO HUMAN INPUT UNDER DUAL FAILURE.
```

---

## AUDIT 11: Cross-Domain Kill Chain — Sensor-to-Effector Loop
**Goal**: The drone becomes the fleet's eyes. It detects, tracks, and locks onto contacts, then relays targeting data to surface vessels for intercept. This is JADC2 (Joint All-Domain Command & Control) in miniature — the single most impressive capability for a defense demo.

```
Execute Audit 11 — Cross-Domain Kill Chain for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 11.
READ THE BLOCKERS SECTION — especially Blocker 4 (kill chain uses threat_detector,
doesn't duplicate it), Blocker 7 (TRACK pattern needs orbit for sustained lock).

COMPLETED AUDITS: Audits 1-10 complete. Predictive intercept, auto threat
response, comms-denied autonomy all working. Tests passing.

YOUR TASK: Build the sensor-to-effector loop: drone sensor model → targeting
data relay → kill chain state machine → fleet intercepts using drone's data.

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

Currently the drone and surface vessels operate independently. They share
a map but not information:
- The drone doesn't "see" contacts — it flies patterns geometrically
- Surface vessels don't receive targeting data from the drone
- When the fleet intercepts, it uses OMNISCIENT contact position from the
  sim (fleet_manager.contacts dict) — not sensor data
- The drone auto-tracks from Audit 9, but that's just a waypoint update —
  there's no concept of the drone having a "sensor lock" or relaying data

The architectural gap: there is NO information flow between domains.
The drone and surface fleet are two independent systems that happen to
share a screen. A defense CEO would immediately ask: "Do they talk to
each other?" The answer is no.

WHAT WE ALREADY HAVE (from Audit 9):
- threat_detector.py: assess_threats() produces threat_level per contact
  (none/detected/warning/critical) based on range from FLEET CENTROID
- fleet_manager._check_threats(): runs every ~1s, auto-retasks drone to
  TRACK on warning/critical range
- DroneCoordinator.generate_track_waypoints(): produces a single point
  behind the target — NOT sustained tracking orbit

WHAT'S MISSING:
- Drone has no sensor model (detection range, FOV)
- No targeting data relay (drone → fleet_manager → fleet nav)
- No kill chain phases connecting detection → engagement
- DroneCoordinator TRACK creates one point, not an orbit — drone reaches
  it and stops, doesn't maintain continuous tracking coverage

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

A) DRONE SENSOR MODEL (new file: src/fleet/drone_sensor.py)

   Keep this SEPARATE from threat_detector.py. The fleet's detection
   (threat_detector, 8km range) is the fleet's organic sensors. The drone
   sensor is a DIFFERENT, more precise sensor at shorter range.

   DRONE_SENSOR_RANGE = 3000.0  # meters — high-res sensor, shorter range
   DRONE_SENSOR_FOV = 120.0     # degrees — forward-looking cone

   @dataclass
   class TargetingData:
       contact_id: str
       bearing: float        # radians from drone to contact
       range_m: float        # distance in meters
       contact_x: float      # estimated contact position (from drone's sensor)
       contact_y: float      # estimated contact position
       confidence: float     # 1.0 = perfect, degrades with range
       locked: bool          # True if drone is in TRACK + within range + in FOV

   def drone_detect_contacts(drone_x: float, drone_y: float,
                              drone_heading: float, contacts: dict,
                              sensor_range: float = DRONE_SENSOR_RANGE,
                              fov_deg: float = DRONE_SENSOR_FOV
                              ) -> list[TargetingData]:
       """Evaluate which contacts the drone can see."""
       results = []
       for cid, contact in contacts.items():
           dx = contact.x - drone_x
           dy = contact.y - drone_y
           dist = math.sqrt(dx*dx + dy*dy)
           if dist > sensor_range:
               continue
           bearing = math.atan2(dy, dx)
           # Check FOV: is bearing within fov_deg/2 of drone heading?
           angle_diff = abs((bearing - drone_heading + math.pi) % (2*math.pi) - math.pi)
           if math.degrees(angle_diff) > fov_deg / 2:
               continue
           confidence = max(0.3, 1.0 - (dist / sensor_range) * 0.7)
           results.append(TargetingData(
               contact_id=cid, bearing=bearing, range_m=dist,
               contact_x=contact.x, contact_y=contact.y,
               confidence=confidence, locked=False,
           ))
       return results

   IMPORTANT: confidence degrades with range. At 3km, confidence is 0.3.
   At 0m, confidence is 1.0. This matters for the decision trail (Audit 12).

B) KILL CHAIN STATE MACHINE (add to fleet_manager.py)

   The kill chain phases are DRIVEN BY existing systems, not parallel to them:

   self.kill_chain_phase: str | None = None
   self.kill_chain_target: str | None = None
   self.targeting_data: TargetingData | None = None

   Phase transitions in a new method _advance_kill_chain() called from step():

   PHASE: None → "DETECT"
     Trigger: threat_detector reports any contact at threat_level != "none"
     (This ALREADY HAPPENS in _check_threats from Audit 9)
     Action: set kill_chain_phase = "DETECT", log transition

   PHASE: "DETECT" → "TRACK"
     Trigger: drone has been auto-tasked to TRACK (Audit 9 does this on warning)
     Detection: drone_coordinator._current_pattern == DronePattern.TRACK
     Action: set kill_chain_phase = "TRACK", log transition

   PHASE: "TRACK" → "LOCK"
     Trigger: drone is within sensor range AND contact is in FOV
     Detection: call drone_detect_contacts() — if any result has locked=True
     Action: store targeting_data, set kill_chain_phase = "LOCK"
     CRITICAL: set targeting_data.locked = True when drone is in TRACK pattern
     AND within sensor range AND contact in FOV

   PHASE: "LOCK" → "ENGAGE"
     Trigger: operator clicks intercept button (Audit 9) OR auto-engage
     from comms-denied escalation (Audit 10)
     Detection: active_mission changes to INTERCEPT while lock is held
     Action: set kill_chain_phase = "ENGAGE"

   PHASE: "ENGAGE" → "CONVERGE"
     Trigger: any surface vessel within 1000m of contact
     Action: set kill_chain_phase = "CONVERGE"
     When any vessel within 200m: kill_chain_phase = None (complete)

   PHASE RESET: If contact is removed or goes out of range, reset to None.

   def _advance_kill_chain(self):
       """Progress kill chain based on current state."""
       if not self.contacts:
           self.kill_chain_phase = None
           self.kill_chain_target = None
           self.targeting_data = None
           return

       # Run drone sensor
       drone_heading_rad = math.radians(90 - self.drone.heading) if hasattr(self.drone, 'heading') else 0.0
       # Get drone heading in radians (math convention)
       detections = drone_detect_contacts(
           self.drone.x, self.drone.y, drone_heading_rad, self.contacts
       )

       # Update targeting data
       if detections:
           best = max(detections, key=lambda d: d.confidence)
           # Lock if drone is actively tracking this contact
           if (self.drone_coordinator._current_pattern == DronePattern.TRACK
                   and best.range_m < DRONE_SENSOR_RANGE):
               best.locked = True
           self.targeting_data = best
           self.kill_chain_target = best.contact_id
       else:
           self.targeting_data = None

       # Phase transitions
       if self.kill_chain_phase is None:
           if self.threat_assessments:
               real_threats = [t for t in self.threat_assessments
                               if t.threat_level != "none"]
               if real_threats:
                   self.kill_chain_phase = "DETECT"
                   self.kill_chain_target = real_threats[0].contact_id

       elif self.kill_chain_phase == "DETECT":
           if self.drone_coordinator._current_pattern == DronePattern.TRACK:
               self.kill_chain_phase = "TRACK"

       elif self.kill_chain_phase == "TRACK":
           if self.targeting_data and self.targeting_data.locked:
               self.kill_chain_phase = "LOCK"

       elif self.kill_chain_phase == "LOCK":
           if self.active_mission == MissionType.INTERCEPT:
               self.kill_chain_phase = "ENGAGE"

       elif self.kill_chain_phase == "ENGAGE":
           # Check if any vessel is within convergence range
           target = self.contacts.get(self.kill_chain_target)
           if target:
               for v in self.vessels.values():
                   dist = math.sqrt(
                       (v["state"][0] - target.x)**2 +
                       (v["state"][1] - target.y)**2
                   )
                   if dist < 1000.0:
                       self.kill_chain_phase = "CONVERGE"
                       break

       elif self.kill_chain_phase == "CONVERGE":
           target = self.contacts.get(self.kill_chain_target)
           if target:
               for v in self.vessels.values():
                   dist = math.sqrt(
                       (v["state"][0] - target.x)**2 +
                       (v["state"][1] - target.y)**2
                   )
                   if dist < 200.0:
                       self.kill_chain_phase = None  # Complete
                       break
           else:
               self.kill_chain_phase = None  # Target gone

C) DRONE TARGETING FEEDS INTERCEPT REPLAN (modify _replan_intercept)

   Currently _replan_intercept() reads contact position from the omniscient
   sim state (self.contacts[id].x, .y). When the drone has a targeting lock,
   use the DRONE'S targeting data instead:

   In _replan_intercept(), after finding the closest target:
     if self.targeting_data and self.targeting_data.locked:
         # Use drone's sensor data instead of omniscient sim data
         target_x = self.targeting_data.contact_x
         target_y = self.targeting_data.contact_y
         # (For now these are the same since relay is perfect,
         #  but the architecture separates them for future noise)

   This is architecturally important even though the values are identical
   today — it proves the fleet navigates via sensor data, not god-mode.

D) TRACK PATTERN FIX (modify DroneCoordinator)

   Current generate_track_waypoints() generates ONE point 200m behind target.
   Drone flies there and then has no waypoints left — it doesn't orbit.

   Fix: when drone is in TRACK and reaches its waypoint, regenerate the
   track waypoint based on the contact's CURRENT position. This already
   partially happens via the auto-retask in _check_threats(), but it only
   fires every 4 steps and only when threat level is warning/critical.

   Better approach: in fleet_manager.step(), after drone.step(dt), if
   drone is in TRACK pattern and contacts exist:
     contact = self.contacts.get(self.kill_chain_target)
     if contact:
         self.drone_coordinator.assign_pattern(
             DronePattern.TRACK,
             [Waypoint(x=contact.x, y=contact.y)],
             altitude=100.0,
         )
   Do this every THREAT_CHECK_INTERVAL steps (reuse the counter) to avoid
   per-step jitter. This keeps the drone continuously pursuing the contact.

E) KILL CHAIN DATA IN FLEET STATE (modify get_fleet_state_dict())

   Add to data["autonomy"] (same namespace as comms-denied):
   data["autonomy"]["kill_chain_phase"] = self.kill_chain_phase
   data["autonomy"]["kill_chain_target"] = self.kill_chain_target

   Add targeting data if available:
   if self.targeting_data:
       data["autonomy"]["targeting"] = {
           "contact_id": self.targeting_data.contact_id,
           "bearing_deg": (90 - math.degrees(self.targeting_data.bearing)) % 360,
           "range_m": self.targeting_data.range_m,
           "confidence": self.targeting_data.confidence,
           "locked": self.targeting_data.locked,
           "drone_x": self.drone.x,
           "drone_y": self.drone.y,
       }

F) DASHBOARD — KILL CHAIN VISUALIZATION

   1. FleetMap.jsx:
      - When targeting_data.locked: draw yellow line from drone to contact
        labeled "LOCK" with range display
      - When kill_chain_phase == "ENGAGE": draw red converging lines from
        each surface vessel to intercept point
      - Optional: semi-transparent sensor cone wedge from drone (nice for demo)

   2. MissionStatus.jsx:
      - Kill chain phase indicator with color progression:
        DETECT=yellow, TRACK=amber, LOCK=orange, ENGAGE=red, CONVERGE=pulsing red
      - Format: "KILL CHAIN: LOCK — bogey-1 via Eagle-1 (2.8km @ 042°)"
      - Show confidence percentage when locked

   3. MissionLog.jsx:
      - Log each phase transition: "KILL CHAIN → TRACK: Eagle-1 pursuing bogey-1"

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT add radar physics or wave propagation — range + FOV is enough
- Do NOT add sensor noise to the relay YET — perfect relay first
  (architecture supports noise later via confidence field)
- Do NOT modify schemas.py
- Do NOT duplicate threat_detector logic — kill chain phases are DRIVEN BY
  threat_detector outputs, not parallel to them
- Do NOT break manual intercept — kill chain enhances it, doesn't replace it.
  If operator manually dispatches intercept without a kill chain, it still works.
- Do NOT modify DroneCoordinator pattern generation signatures — add the
  continuous tracking update in fleet_manager.step()

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

New file: tests/test_kill_chain.py

1. test_drone_detects_contact_in_range:
   drone_detect_contacts with contact at 2000m → returns TargetingData

2. test_drone_no_detect_out_of_range:
   Contact at 5000m → empty list

3. test_drone_no_detect_outside_fov:
   Drone heading east (0 rad), contact due west (behind) → not detected

4. test_confidence_degrades_with_range:
   Contact at 500m → confidence > 0.8. Contact at 2800m → confidence < 0.5

5. test_kill_chain_detect_phase:
   Spawn contact at 6000m from fleet → run threat check → kill_chain_phase == "DETECT"

6. test_kill_chain_track_phase:
   Setup: contact at warning range, drone auto-tasked to TRACK
   → kill_chain_phase == "TRACK"

7. test_kill_chain_lock_phase:
   Setup: drone at (2000, 0), contact at (2500, 0), drone heading east in TRACK
   → drone_detect_contacts returns locked=True → kill_chain_phase == "LOCK"

8. test_kill_chain_engage_phase:
   Setup: lock achieved → dispatch intercept → kill_chain_phase == "ENGAGE"

9. test_kill_chain_full_progression:
   Integration: spawn contact at 9000m moving toward fleet. Run enough steps
   for all phases: DETECT → TRACK → LOCK. Dispatch intercept → ENGAGE.
   Run until vessel within 1000m → CONVERGE. Verify all transitions happened.

10. test_kill_chain_reset_on_contact_removal:
    Active kill chain → remove contact → kill_chain_phase == None

11. test_targeting_data_in_fleet_state:
    Drone has lock → get_fleet_state_dict() includes targeting data with
    bearing, range, confidence, locked=True

12. test_drone_continuous_tracking:
    Drone in TRACK, contact moving → after N steps, drone waypoints have
    been updated to follow contact (not stuck at original point)

Run: .venv/bin/python -m pytest tests/ -v

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. src/fleet/drone_sensor.py — TargetingData + drone_detect_contacts()
2. fleet_manager.py — kill chain state machine (_advance_kill_chain)
3. fleet_manager.py — _replan_intercept uses drone targeting when available
4. fleet_manager.py — continuous drone tracking update in step()
5. fleet_manager.py — kill chain + targeting in get_fleet_state_dict()
6. Dashboard — targeting lines, phase indicator, log entries
7. 12 new tests
8. Full test suite — no regressions
9. Commit when done

DEMO STORY:
  Fleet idle at base. Contact spawned at 9km heading southwest.
  threat_detector fires → "CONTACT DETECTED." Kill chain: DETECT.
  Contact closes to 5km. Drone auto-launches → TRACK. Cyan trail
  streaks toward contact. Drone closes to 3km → sensor detects contact
  → LOCK. Yellow targeting line from drone to contact. Dashboard shows:
  "KILL CHAIN: LOCK — bogey-1 via Eagle-1 (2.8km @ 042°, 72% confidence)"

  Operator clicks INTERCEPT. Kill chain → ENGAGE. Fleet dispatches to
  predicted intercept point using DRONE'S targeting data. Red convergence
  lines on map. Drone maintains overhead track, confidence climbing as
  range decreases. Fleet arrives within 1000m → CONVERGE.
  "INTERCEPT COMPLETE — full sensor-to-effector loop."

  NOW TOGGLE COMMS DENIED. Repeat with new contact. The entire kill chain
  plays out autonomously: DETECT → TRACK → LOCK → auto-ENGAGE (after 60s
  delay) → CONVERGE. Zero human input. Cross-domain. Under comms denial.
  THAT is the demo.
```

---

## AUDIT 12: Decision Audit Trail — The AI Explains Itself
**Goal**: Every autonomous decision gets a human-readable rationale showing WHAT was decided, WHY it was chosen, and WHAT alternatives were rejected. This is non-negotiable for defense — operators must trust the system, and review boards must be able to audit it. This is the difference between a toy and a weapon system.

```
Execute Audit 12 — Decision Audit Trail for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 12.

COMPLETED AUDITS: Audits 1-11 complete. Full kill chain working.
Tests passing. Do NOT break them.

YOUR TASK: Add explainable decision logging. Every autonomous action —
intercept prediction, asset allocation, threat assessment, auto-track,
comms fallback, kill chain transitions, replanning — gets logged with
a human-readable rationale. Stream decisions via WebSocket for real-time
dashboard display. Expose via REST for post-mission review.

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

The system now makes 7+ categories of autonomous decisions:
- Intercept point prediction (where to go)
- Asset allocation (who goes where)
- Threat assessment (how dangerous is this contact)
- Auto-drone retask (Eagle-1 to TRACK)
- Comms-denied fallback (RTB, hold, or auto-engage)
- Kill chain phase transitions (DETECT → TRACK → LOCK → ENGAGE)
- Intercept replanning (waypoint update when target moves)

When any of these happen, the operator sees "alpha → EXECUTING."
That's it. No WHY. No alternatives considered. No confidence level.
No reasoning chain.

A defense CEO will ask: "Why did it pick alpha over bravo?"
A review board will ask: "What was the system's confidence when it
auto-engaged under comms denial?"
A commander will ask: "Why did it replan to that position?"

If you can't answer these, the system is a black box. Black boxes
don't get fielded. Explainability IS the product for defense autonomy.

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

A) DECISION LOG DATA STRUCTURE (new: src/fleet/decision_log.py)

   from dataclasses import dataclass, field
   from collections import deque
   import time

   @dataclass
   class DecisionEntry:
       timestamp: float
       decision_type: str
       action_taken: str
       rationale: str
       confidence: float = 1.0
       assets_involved: list[str] = field(default_factory=list)
       alternatives: list[str] = field(default_factory=list)
       parent_id: str | None = None   # links to triggering decision

       @property
       def id(self) -> str:
           return f"{self.decision_type}_{self.timestamp:.3f}"

   Valid decision_types:
   - "intercept_solution"   — where to intercept
   - "asset_allocation"     — which asset goes where and why
   - "threat_assessment"    — contact evaluated
   - "auto_track"           — drone auto-retasked
   - "comms_fallback"       — autonomous action under comms denial
   - "auto_engage"          — fully autonomous intercept (comms denied)
   - "kill_chain_transition" — phase change in kill chain
   - "replan"               — intercept point updated
   - "formation_selection"  — why this formation for this mission

   class DecisionLog:
       def __init__(self, max_entries: int = 200):
           self._entries: deque[DecisionEntry] = deque(maxlen=max_entries)

       def log(self, decision_type: str, action: str, rationale: str,
               confidence: float = 1.0, assets: list[str] | None = None,
               alternatives: list[str] | None = None,
               parent_id: str | None = None) -> DecisionEntry:
           entry = DecisionEntry(
               timestamp=time.time(),
               decision_type=decision_type,
               action_taken=action,
               rationale=rationale,
               confidence=confidence,
               assets_involved=assets or [],
               alternatives=alternatives or [],
               parent_id=parent_id,
           )
           self._entries.append(entry)
           return entry

       def get_recent(self, n: int = 20) -> list[DecisionEntry]:
           return list(self._entries)[-n:]

       def get_by_type(self, dtype: str) -> list[DecisionEntry]:
           return [e for e in self._entries if e.decision_type == dtype]

       def to_dicts(self, n: int = 10) -> list[dict]:
           """Serialize recent entries for WebSocket/API."""
           return [
               {
                   "id": e.id,
                   "timestamp": e.timestamp,
                   "type": e.decision_type,
                   "action": e.action_taken,
                   "rationale": e.rationale,
                   "confidence": e.confidence,
                   "assets": e.assets_involved,
                   "alternatives": e.alternatives,
                   "parent_id": e.parent_id,
               }
               for e in list(self._entries)[-n:]
           ]

B) INSTRUMENT ALL DECISION POINTS

   Add self.decision_log = DecisionLog() to fleet_manager.__init__().

   1. INTERCEPT PREDICTION (dispatch_command, after compute_intercept_point):

      dist_to_target = math.sqrt(...)
      eta = dist_to_target / fleet_speed
      self.decision_log.log(
          "intercept_solution",
          f"Intercept point: ({pred_x:.0f}, {pred_y:.0f})",
          f"Target {target.contact_id} at ({target.x:.0f}, {target.y:.0f}) "
          f"heading {math.degrees(target.heading):.0f}° at {target.speed:.1f} m/s. "
          f"Fleet centroid ({cx:.0f}, {cy:.0f}). "
          f"Predicted intercept ({pred_x:.0f}, {pred_y:.0f}), "
          f"ETA {eta:.0f}s ({eta/60:.1f}min). "
          f"Lead distance: {math.sqrt((pred_x-target.x)**2+(pred_y-target.y)**2):.0f}m ahead of target.",
          confidence=min(1.0, fleet_speed / max(target.speed, 0.1)),
          assets=[ac.asset_id for ac in surface_cmds],
      )

   2. ASSET ALLOCATION (dispatch_command, per-asset):

      For each surface vessel dispatched:
      - Compute distance to intercept point
      - Compute heading offset from current heading to intercept bearing
      - Compute ETA
      - Log: "alpha dispatched: 2.1km to intercept, 15° heading offset,
        ETA 4m22s — closest vessel, most favorable heading."
      - For non-lead vessels in formation: "bravo dispatched: echelon
        offset 200m from alpha (formation lead)."

      Alternatives: for each vessel NOT chosen as lead (if applicable):
      "charlie rejected as lead: 3.8km (vs alpha 2.1km), 87° heading offset"

   3. THREAT ASSESSMENT (_check_threats, per threat):

      For each threat at warning or critical level:
      self.decision_log.log(
          "threat_assessment",
          f"{ta.contact_id}: {ta.threat_level.upper()} at {ta.distance:.0f}m",
          ta.reason,  # already human-readable from threat_detector
          confidence=1.0 - (ta.distance / 8000.0),
      )

   4. AUTO-DRONE RETASK (_check_threats, when drone is re-tasked):

      prev_pattern = self.drone_coordinator._current_pattern
      self.decision_log.log(
          "auto_track",
          f"Eagle-1 re-tasked: {prev_pattern} → TRACK {ta.contact_id}",
          f"Contact at {ta.distance:.0f}m ({ta.threat_level} range). "
          f"Fleet {'idle' if not active_intercept else 'not on intercept'} "
          f"— no mission conflict. Drone is fastest asset (15 m/s) "
          f"with aerial sensor advantage.",
          assets=["eagle-1"],
      )

   5. COMMS-DENIED ACTIONS (_execute_comms_fallback, _auto_engage_threat):

      self.decision_log.log(
          "comms_fallback",
          f"AUTO-RTB: standing orders = {self.comms_lost_behavior}",
          f"Comms denied for {elapsed:.0f}s. Fleet was idle. "
          f"Executing pre-briefed comms_lost_behavior: {self.comms_lost_behavior}. "
          f"No operator available to issue commands.",
          confidence=1.0,  # following explicit standing orders
      )

      For auto-engage:
      self.decision_log.log(
          "auto_engage",
          f"AUTO-INTERCEPT: {target_id}",
          f"Comms denied {elapsed:.0f}s. {target_id} at critical range "
          f"({dist:.0f}m). Escalation delay ({DELAY}s) exceeded. "
          f"No operator response. Autonomous engagement authorized by "
          f"timeout policy. Kill chain phase: {self.kill_chain_phase}.",
          confidence=0.7,  # lower confidence for autonomous decisions
          assets=list(self.vessels.keys()) + ["eagle-1"],
      )

   6. KILL CHAIN TRANSITIONS (_advance_kill_chain):

      On each phase change:
      self.decision_log.log(
          "kill_chain_transition",
          f"Kill chain: {old_phase} → {new_phase}",
          f"Target: {self.kill_chain_target}. "
          f"Trigger: {trigger_reason}. "
          f"Drone targeting: {'locked' if self.targeting_data and self.targeting_data.locked else 'searching'}.",
      )

   7. REPLAN (_replan_intercept, when waypoints actually update):

      self.decision_log.log(
          "replan",
          f"Intercept waypoints updated: shift {shift:.0f}m",
          f"Previous intercept ({cur_wp_x:.0f}, {cur_wp_y:.0f}) → "
          f"new ({pred_x:.0f}, {pred_y:.0f}). Target moved since last plan. "
          f"Shift exceeded {REPLAN_SHIFT_THRESHOLD}m threshold.",
          parent_id=last_intercept_decision_id,  # link to original
      )

C) DECISION LOG IN FLEET STATE (modify get_fleet_state_dict())

   Stream the last N decisions via WebSocket so dashboard updates in real-time:
   data["decisions"] = self.decision_log.to_dicts(n=10)

   This means every 250ms the dashboard receives the 10 most recent decisions.
   New decisions appear instantly. No polling needed.

D) DECISION LOG API ENDPOINT (add to routes.py)

   GET /api/decisions?limit=50&type=intercept_solution
   Returns decision entries for post-mission review.

   @router.get("/api/decisions")
   async def get_decisions(request: Request,
                           limit: int = Query(50),
                           type: str | None = Query(None)):
       fm = request.app.state.commander.fleet_manager
       if type:
           entries = fm.decision_log.get_by_type(type)[-limit:]
       else:
           entries = fm.decision_log.get_recent(limit)
       return {"decisions": [serialize(e) for e in entries]}

E) DASHBOARD — DECISION PANEL

   Replace or augment MissionLog.jsx with decision display:

   1. Each decision entry shows:
      - Timestamp (relative: "12s ago")
      - Decision type as colored badge:
        intercept=red, threat=amber, auto_track=cyan, comms=orange,
        kill_chain=purple, replan=blue, auto_engage=pulsing red
      - Action (bold, one line)
      - Rationale (expandable on click — starts collapsed)
      - Confidence bar (0-100%, color-coded: green >80%, amber 50-80%, red <50%)

   2. Alternatives section (expandable):
      "Considered: charlie (rejected: 3.8km, 87° off heading)"

   3. Decision chain visualization:
      When parent_id is set, show a subtle link: "↳ follows: intercept_solution_1234"
      This shows the reasoning chain: intercept_solution → asset_allocation → replan

   4. Auto-scroll to newest decision. Pause auto-scroll when user scrolls up.

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT use the existing SQLite mission_logger — that's for event replay,
  this is for real-time explainability. They serve different purposes.
- Do NOT log every step() tick — only log when a DECISION is made
- Do NOT modify schemas.py
- Do NOT make rationale computation expensive — it's string formatting
  of data you already computed for the decision itself
- Do NOT log decisions with empty rationales — every entry MUST have a
  non-trivial explanation. "Executed command" is NOT a rationale.
- Do NOT stream all 200 entries every tick — only the last 10 via WebSocket.
  REST endpoint serves the full history.

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

New file: tests/test_decision_log.py

1. test_decision_log_stores_entries:
   Log 3 decisions → get_recent(3) returns all 3 in order

2. test_decision_log_bounded_ring_buffer:
   Log 250 decisions → len(entries) == 200, oldest are dropped

3. test_decision_log_filter_by_type:
   Log mixed types → get_by_type("replan") returns only replans

4. test_decision_log_to_dicts:
   Log decisions → to_dicts(5) returns list of dicts with all fields

5. test_decision_log_parent_chain:
   Log parent, then child with parent_id → child.parent_id matches parent.id

6. test_intercept_dispatch_logs_solution:
   Dispatch intercept with contacts → decision_log has "intercept_solution"
   entry with non-empty rationale containing "ETA" and "intercept point"

7. test_intercept_dispatch_logs_allocation:
   Dispatch intercept → decision_log has "asset_allocation" entries for
   each surface vessel, each with distance and heading offset in rationale

8. test_threat_assessment_logs_decision:
   Contact at warning range → threat check → decision_log has
   "threat_assessment" entry with distance and threat level

9. test_auto_track_logs_decision:
   Drone auto-retasked → decision_log has "auto_track" entry explaining
   why (contact range, fleet idle status, pattern change)

10. test_replan_logs_shift:
    Intercept replan triggers → decision_log has "replan" entry with
    shift distance and old/new intercept points

11. test_decisions_in_fleet_state_dict:
    Log decisions → get_fleet_state_dict() includes "decisions" key
    with list of serialized entries

12. test_decision_api_endpoint:
    Log decisions → GET /api/decisions returns JSON list

Run: .venv/bin/python -m pytest tests/ -v

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. src/fleet/decision_log.py — DecisionEntry + DecisionLog classes
2. fleet_manager.py — DecisionLog instance + instrument ALL 7 decision points
3. fleet_manager.py — decisions in get_fleet_state_dict()
4. routes.py — GET /api/decisions endpoint
5. Dashboard — decision panel with rationale, confidence bars, type badges
6. 12 new tests
7. Full test suite — no regressions
8. Commit when done

DEMO STORY:
  Run the full kill chain demo. As the system operates, the decision panel
  fills with real-time reasoning:

  [THREAT] "bogey-1: WARNING at 4200m, closing 2.8 m/s" (85% confidence)
  [AUTO-TRACK] "Eagle-1 re-tasked: STATION → TRACK bogey-1 — contact at
    warning range, fleet idle, drone fastest asset" (90%)
  [KILL CHAIN] "Kill chain: DETECT → TRACK — Eagle-1 pursuing bogey-1"
  [KILL CHAIN] "Kill chain: TRACK → LOCK — Eagle-1 sensor lock, 2.1km, 88%"
  [INTERCEPT] "Intercept point: (2400, 1100) — target heading 225° at 1.5m/s,
    fleet centroid (500, 200), ETA 4m22s, lead 800m" (92%)
  [ALLOCATION] "alpha: 2.1km, 15° offset, ETA 4m22s — best candidate"
  [ALLOCATION] "bravo: echelon +200m from alpha"
  [ALLOCATION] "charlie: echelon +400m from alpha"
    ↳ "Rejected as lead: 3.8km, 87° heading offset"
  [REPLAN] "Waypoints shifted 180m — target moved since last plan"

  Toggle COMMS DENIED. Watch:
  [COMMS] "AUTO-RTB: comms denied 62s, fleet idle, standing orders = return_to_base" (100%)
  [AUTO-ENGAGE] "AUTO-INTERCEPT: bogey-2 — comms denied 95s, critical range,
    no operator response, timeout policy" (70%)

  The operator sees the AI THINKING. Every decision has a WHY.
  Every autonomous action has a confidence level. Every choice shows
  what was considered and rejected. THIS is what gets you hired at Havoc.
```

---

## AUDIT 13: Mission-Specific Behaviors — Every Mission Looks Different
**Goal**: The 6 mission types currently all do the same thing: go to waypoint, stop. A demo that shows "patrol" and "search" looking identical is a demo that shows you didn't build real mission behaviors. Each mission type must produce visually distinct, tactically correct fleet behavior on the map.

```
Execute Audit 13 — Mission-Specific Behaviors for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 13.
READ THE BLOCKERS SECTION — especially Blocker 5 (ESCORT contact designation).

COMPLETED AUDITS: Audits 1-12 complete. Full autonomous C2 system working.
Tests passing. Do NOT break them.

NOTE: This audit has NO dependency on Audits 10-12. It could be executed
right after Audit 9 for quick visual wins. The mission behaviors are
foundation-level and make every other demo look better.

YOUR TASK: Make each of the 6 mission types produce distinct fleet behavior.
The changes are in fleet_manager.py dispatch_command() and step() ONLY.
Extract mission behavior into a _mission_specific_step() method to keep
step() clean (see Blocker 2).

────────────────────────────────────────────────────────────────────
THE PROBLEM
────────────────────────────────────────────────────────────────────

Right now, ALL mission types do the EXACT same thing:
1. Receive waypoints
2. Navigate to waypoints in straight lines
3. Reach last waypoint → go IDLE

PATROL = go to point, stop.
SEARCH = go to point, stop.
ESCORT = go to point, stop (doesn't follow anything).
LOITER = go to point, stop (doesn't orbit).
AERIAL_RECON = go to point, stop (drone does nothing special).

The mission_type field is stored in fleet_manager.active_mission but
COMPLETELY IGNORED during step() execution. It's cosmetic.

The waypoint completion logic (step(), lines 286-292) goes IDLE after
the last waypoint for ALL missions. That's the single line to change
for PATROL and LOITER — add mission-specific behavior where the vessel
currently goes IDLE.

────────────────────────────────────────────────────────────────────
WHAT TO BUILD
────────────────────────────────────────────────────────────────────

Extract a new method: _mission_specific_step() called from step() AFTER
the current waypoint completion check (line 286). This method handles
what to do when a vessel reaches its last waypoint based on mission type.

A) PATROL — Continuous Loop

   CURRENT: reach last waypoint → IDLE
   NEW: reach last waypoint → reset i_wpt to 1, continue EXECUTING

   In step(), when i_wpt >= len(wpts_x) AND mission == PATROL:
     v["i_wpt"] = 1  # loop back to first real waypoint (0 is start pos)
     # DON'T set IDLE — stay EXECUTING
     continue  # skip the IDLE block

   The vessel's waypoint list already contains the full route from dispatch.
   Resetting i_wpt creates an infinite loop through the waypoints.
   The trail on the dashboard will show the repeating patrol pattern.

   Drone: dispatch with ORBIT pattern around the patrol centroid.
   In dispatch_command(), when PATROL:
     centroid_x = mean of all waypoint x values
     centroid_y = mean of all waypoint y values
     drone_coordinator.assign_pattern(ORBIT, [centroid], altitude=100)

B) SEARCH — Zigzag Lawnmower Pattern

   CURRENT: go to single waypoint, stop
   NEW: generate a lawnmower search pattern from the target area

   In dispatch_command(), when mission == SEARCH:
     For each surface vessel, replace its single waypoint with a zigzag:

     def _generate_search_pattern(center_x, center_y, width=500.0,
                                   height=500.0, legs=6, offset=0.0):
         """Generate zigzag waypoints for a lawnmower search."""
         wps = []
         leg_spacing = height / legs
         half_w = width / 2
         for i in range(legs):
             y = center_y - height/2 + i * leg_spacing + offset
             if i % 2 == 0:
                 wps.append(Waypoint(x=center_x - half_w, y=y))
                 wps.append(Waypoint(x=center_x + half_w, y=y))
             else:
                 wps.append(Waypoint(x=center_x + half_w, y=y))
                 wps.append(Waypoint(x=center_x - half_w, y=y))
         return wps

     Give each vessel a parallel track with lateral offset based on vessel
     index * spacing_meters. This spreads the search across the area.

     After reaching the last zigzag waypoint: LOOP (same as patrol).
     This creates continuous search until RTB.

     Drone: SWEEP pattern over the same area.

C) ESCORT — Follow a Contact

   CURRENT: go to waypoint, stop
   NEW: continuously track a contact, maintaining formation offset

   ESCORT semantics: operator picks escort by dispatching the ESCORT mission.
   The fleet attaches to the CLOSEST CONTACT at dispatch time (same convention
   as INTERCEPT). If no contacts exist, fall back to normal waypoint behavior.

   In dispatch_command(), when mission == ESCORT AND contacts exist:
     Store: self._escort_target_id = closest_contact.contact_id
     Initial waypoints still go to the contact's current position

   In step() (_mission_specific_step), when mission == ESCORT:
     contact = self.contacts.get(self._escort_target_id)
     if not contact:
         return  # target gone — hold position
     # Recompute waypoints to track contact's current position
     for vid, v in self.vessels.items():
         if v["status"] != AssetStatus.EXECUTING:
             continue
         # Simple: update last waypoint to contact's current position
         # (formation offsets applied during dispatch still hold)
         v["waypoints_x"][-1] = contact.x * METERS_TO_NMI
         v["waypoints_y"][-1] = contact.y * METERS_TO_NMI

   This runs every step, keeping the fleet's destination locked to the
   contact. The formation offsets (echelon, column, etc.) from dispatch
   create a protective screen around the escort target.

   Drone: TRACK pattern on the escort target.
   Self._escort_target_id: str | None = None (add to __init__)

   EDGE CASE: if escort target contact is removed mid-mission, fleet
   holds position (stop updating waypoints, let vessels reach last known
   position and go IDLE normally).

D) LOITER — Station-Keeping Orbit

   CURRENT: reach waypoint, stop, IDLE
   NEW: reach waypoint, generate small circular orbit, loop continuously

   In step() (_mission_specific_step), when mission == LOITER AND
   vessel reaches last waypoint (i_wpt >= len(wpts_x)):
     Generate 8 orbit points in a 150m radius circle around the loiter point:
     loiter_x = wpts_x[-1] / METERS_TO_NMI  # convert back to meters
     loiter_y = wpts_y[-1] / METERS_TO_NMI
     orbit_wps_x = [loiter_x * METERS_TO_NMI]  # start pos
     orbit_wps_y = [loiter_y * METERS_TO_NMI]
     for i in range(8):
         angle = i * (2 * math.pi / 8)
         ox = (loiter_x + 150 * math.cos(angle)) * METERS_TO_NMI
         oy = (loiter_y + 150 * math.sin(angle)) * METERS_TO_NMI
         orbit_wps_x.append(ox)
         orbit_wps_y.append(oy)
     v["waypoints_x"] = orbit_wps_x
     v["waypoints_y"] = orbit_wps_y
     v["i_wpt"] = 1
     # DON'T set IDLE — stay EXECUTING

   Use a flag v["_loiter_orbit_generated"] = True to avoid regenerating
   every step. Reset on new dispatch.

   Drone: ORBIT pattern at the loiter point (already exists).

   The result: vessels arrive at the loiter point, then begin circling.
   On the dashboard, this looks like a holding pattern — visually distinct
   from a waypoint stop.

E) AERIAL_RECON — Drone Does the Work

   CURRENT: same as everything else
   NEW: drone sweeps a wide area, surface vessels hold nearby

   In dispatch_command(), when mission == AERIAL_RECON:
     Drone: SWEEP pattern over a 1000m x 1000m area centered on the
     commanded waypoint. Use the 2-waypoint convention for SWEEP:
       sw_corner = Waypoint(x=center_x - 500, y=center_y - 500)
       ne_corner = Waypoint(x=center_x + 500, y=center_y + 500)
       drone_coordinator.assign_pattern(SWEEP, [sw_corner, ne_corner], altitude=150)

     Surface vessels: navigate to a holding point 500m south of the recon
     area center (security position), then LOITER (orbit).
     Set a flag so step() treats them as LOITER once they arrive.

   This shows proper domain delegation: air does recon, surface provides
   security. It's the only mission where the drone has primary.

F) INTERCEPT — No Changes
   Already enhanced by Audit 8 (predictive intercept + replanning).
   Do NOT touch intercept logic.

────────────────────────────────────────────────────────────────────
IMPLEMENTATION STRUCTURE
────────────────────────────────────────────────────────────────────

Add to fleet_manager.py:

1. In __init__:
   self._escort_target_id: str | None = None

2. In dispatch_command():
   After existing formation handling, add mission-specific dispatch:
   if cmd.mission_type == MissionType.SEARCH:
       # Replace waypoints with zigzag pattern
   if cmd.mission_type == MissionType.ESCORT and self.contacts:
       # Store escort target
   if cmd.mission_type == MissionType.AERIAL_RECON:
       # Override drone pattern to SWEEP, surface to hold

3. In step(), replace the IDLE block (lines 286-292) with:
   if i_wpt >= len(wpts_x):
       if self.active_mission == MissionType.PATROL or \
          self.active_mission == MissionType.SEARCH:
           v["i_wpt"] = 1  # loop
           # continue with navigation using reset i_wpt
       elif self.active_mission == MissionType.LOITER:
           if not v.get("_loiter_orbit"):
               self._generate_loiter_orbit(vid, v, wpts_x, wpts_y)
           else:
               v["i_wpt"] = 1  # loop the orbit
       else:
           v["status"] = AssetStatus.IDLE  # default: stop
           ...

4. Add _mission_specific_step() called from step() for ESCORT:
   if self.active_mission == MissionType.ESCORT:
       self._update_escort_positions()

────────────────────────────────────────────────────────────────────
DASHBOARD CHANGES
────────────────────────────────────────────────────────────────────

Minimal dashboard changes needed — the map already renders trails:
- PATROL: trail shows repeating loop (automatic from looping waypoints)
- SEARCH: trail shows zigzag pattern (automatic from zigzag waypoints)
- LOITER: trail shows circular orbit (automatic from orbit waypoints)
- ESCORT: trail follows the contact (automatic from continuous update)

MissionStatus.jsx: add mission type color coding:
  PATROL=green, SEARCH=blue, ESCORT=cyan, LOITER=amber,
  AERIAL_RECON=purple, INTERCEPT=red

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT modify schemas.py
- Do NOT add new mission types — use the existing 6
- Do NOT make behaviors complex — simple geometric patterns are fine
- Do NOT break intercept (Audit 8) or threat response (Audit 9)
- Do NOT change formation offset logic — layer mission behaviors ON TOP
- Do NOT add per-step escort waypoint update without a counter — use
  THREAT_CHECK_INTERVAL or similar to avoid jitter (update every ~1s)
- Do NOT modify the vessel dict structure — use existing fields.
  For the loiter orbit flag, use v.get("_loiter_orbit", False) pattern.

────────────────────────────────────────────────────────────────────
TEST PLAN
────────────────────────────────────────────────────────────────────

New file: tests/test_mission_behaviors.py

1. test_patrol_loops_back:
   Dispatch PATROL with 2 waypoints. Run enough steps for vessel to reach
   last waypoint. Verify i_wpt resets to 1 (not going IDLE). Run more
   steps — verify vessel moves BACK toward first waypoint.
   Verify status remains EXECUTING throughout.

2. test_patrol_multiple_loops:
   Run 3 full patrol loops. Verify i_wpt resets each time. Vessel never
   goes IDLE.

3. test_search_generates_zigzag_waypoints:
   Dispatch SEARCH to (500, 500). Verify generated waypoints form a
   zigzag: alternating x values across center, monotonically increasing y.
   Verify at least 8 waypoints generated (legs * 2).

4. test_search_loops_after_completion:
   Run search until all zigzag waypoints reached. Verify i_wpt resets
   (continuous search, same as patrol loop).

5. test_loiter_orbits_after_arrival:
   Dispatch LOITER to (300, 300). Run until arrival. Verify vessel does
   NOT go IDLE. Run 200 more steps. Verify vessel position stays within
   200m of (300, 300) — it's orbiting, not drifting away.

6. test_loiter_orbit_generated_once:
   Reach loiter point. Verify orbit waypoints are generated. Run more
   steps. Verify waypoints are NOT regenerated (flag prevents it).

7. test_escort_follows_contact:
   Spawn contact at (2000, 0) moving east at 2 m/s. Dispatch ESCORT.
   Run 200 steps (50s). Verify fleet centroid has moved EAST (tracking
   the contact). Verify fleet is within 500m of contact.

8. test_escort_holds_when_contact_removed:
   Escort active → remove contact → run 100 steps → verify fleet holds
   position (doesn't crash or error).

9. test_aerial_recon_drone_sweeps:
   Dispatch AERIAL_RECON to (1000, 1000). Verify drone has SWEEP pattern.
   Verify drone coordinator was given a large area (corners ~500m from center).
   Verify surface vessels have waypoints near (but south of) recon area.

10. test_aerial_recon_surface_loiters:
    Dispatch AERIAL_RECON. Run until surface vessels arrive. Verify they
    enter LOITER orbit (not IDLE) — they're providing security.

11. test_intercept_unchanged:
    Run existing intercept tests. Verify no regressions.

12. test_mission_type_in_fleet_state:
    Dispatch each mission type. Verify active_mission field in
    get_fleet_state() matches.

Run: .venv/bin/python -m pytest tests/ -v

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

1. fleet_manager.py — mission-specific logic in dispatch_command() and step()
2. Patrol loops, search zigzags, loiter orbits, escort tracking, recon sweeps
3. Each behavior extracted into clean helper methods
4. Dashboard mission type color coding
5. 12 new tests
6. Full test suite — no regressions
7. Commit when done

DEMO STORY:
  Rapid-fire mission showcase, each visually distinct on the map:

  "All vessels patrol sector in column"
  → Fleet loops through waypoints in column formation. Trail shows
    repeating rectangular pattern. Drone orbits overhead.

  "Search the area around 800 400"
  → Fleet splits into parallel zigzag tracks. Lawnmower pattern visible
    in trails. Drone sweeps the same area from above.

  "Loiter at 500 500"
  → Fleet arrives, then begins tight circular orbit. Dashboard shows
    station-keeping pattern. Drone orbits above.

  "Escort the contact" (with bogey-1 moving east)
  → Fleet forms up around the contact and shadows it. Formation moves
    WITH the contact. On the map: the red contact marker has a blue
    escort screen around it, all moving together.

  "Aerial recon of sector north"
  → Drone streaks out to the recon area, begins wide sweep. Surface
    vessels hold position nearby in loiter orbits. Domain delegation:
    air does the work, surface provides security.

  THEN hit intercept — predictive convergence on a new contact.

  Six missions, six distinct patterns. The fleet looks INTELLIGENT.
  That's the video that gets you hired.
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
