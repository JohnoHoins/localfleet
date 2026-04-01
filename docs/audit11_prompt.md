Execute Audit 11 — Cross-Domain Kill Chain for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 11
(Cross-Domain Kill Chain — Drone Hands Off to Fleet).

COMPLETED AUDITS: Audits 1-10 complete. Predictive intercept, auto threat
response, comms-denied autonomy all working. 147+ tests passing.

YOUR TASK: Make the drone provide targeting data to surface vessels, creating
a sensor-to-effector loop. Add a drone sensor model (range + FOV detection),
targeting data relay, and a 5-phase kill chain state machine
(DETECT → TRACK → LOCK → ENGAGE → CONVERGE). Fleet replanning uses the
drone's sensor data instead of omniscient contact positions.

See the full AUDIT 11 specification in localfleet_audit_plan.md for:
- Drone sensor model (3km range, 120° FOV)
- Targeting data relay from drone to fleet
- Kill chain phase state machine
- Dashboard visualization (targeting lines, phase display)
- Complete test plan (7 tests)
- What NOT to do
