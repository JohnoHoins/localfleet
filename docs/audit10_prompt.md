Execute Audit 10 — Comms-Denied Autonomy for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 10
(Comms-Denied Autonomous Behavior).

COMPLETED AUDITS: Audits 1-9 complete. Predictive intercept + auto threat
response working. 147+ tests passing. Do NOT break them.

YOUR TASK: Add a COMMS DENIED mode where the operator can't send commands but
the fleet continues operating autonomously. The comms_lost_behavior field
already exists in FleetCommand ("return_to_base") but is never triggered —
wire it up. Block command endpoints when denied. Fleet continues last mission
or falls back to standing orders after a timeout.

See the full AUDIT 10 specification in localfleet_audit_plan.md for:
- Comms mode state and command gating
- Autonomous behavior rules (continue mission, idle→RTB, timeout fallback)
- POST /api/comms-mode endpoint
- Dashboard comms-denied overlay (disabled controls, timer, status)
- Complete test plan (8 tests)
- What NOT to do
