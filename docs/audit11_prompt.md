Execute Audit 11 — Cross-Domain Kill Chain for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 11
AND the CRITICAL BLOCKERS section (especially Blockers 4 and 7).

COMPLETED AUDITS: Audits 1-10 complete. Predictive intercept, auto threat
response, comms-denied autonomy all working. Tests passing.

PRE-FLIGHT CHECK:
- Read src/fleet/threat_detector.py — your kill chain phases are DRIVEN BY
  its threat levels, not parallel to them (Blocker 4).
- Read src/fleet/drone_coordinator.py — TRACK pattern currently generates ONE
  point behind the target. You need to add continuous tracking updates (Blocker 7).
- Read fleet_manager._check_threats() — this is where drone auto-retask happens.
  Your TRACK→LOCK transition hooks in here.

YOUR TASK: Build the sensor-to-effector loop. New drone sensor model (3km range,
120° FOV) → targeting data relay → 5-phase kill chain state machine
(DETECT → TRACK → LOCK → ENGAGE → CONVERGE). Fleet intercept replanning
uses the drone's sensor data instead of omniscient sim data.

KEY ADDITIONS vs original spec:
- Kill chain phases MAP to threat_detector output (no duplication)
- TargetingData includes confidence field that degrades with range
- Drone TRACK gets continuous position updates (not single-point)
- _advance_kill_chain() is a clean state machine driven by existing systems
- _replan_intercept() prefers drone targeting data when locked
- 12 tests (up from 7), including confidence, full progression, and reset

See the full AUDIT 11 specification in localfleet_audit_plan.md for:
- src/fleet/drone_sensor.py — TargetingData + drone_detect_contacts()
- Kill chain state machine with phase transition rules
- Drone targeting → intercept replan integration
- Continuous drone tracking fix
- Dashboard kill chain visualization
- Complete test plan (12 tests)
- What NOT to do
