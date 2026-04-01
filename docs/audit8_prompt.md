Execute Audit 8 — Predictive Intercept for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 8
(Predictive Intercept — Lead the Target).

COMPLETED AUDITS (all previous work is done — do NOT touch unless specified):
- Audits 1-7 + Audit 5: Navigation, land avoidance, GPS-denied DR, intercept
  mission, contact tracking, LLM hardening, full C2 dashboard.
- 147 backend tests passing. Do NOT break them.
- POST /api/command-direct endpoint exists — accepts structured FleetCommand
  JSON directly, bypassing the LLM. Use this for testing.

YOUR TASK: Make the intercept mission predict where a moving contact will be
when the fleet arrives, and dispatch to THAT point instead of the contact's
current position. Add continuous replanning every ~10s so the intercept
point tracks the target. Show the predicted intercept point on the dashboard.

See the full AUDIT 8 specification in localfleet_audit_plan.md for:
- Intercept point computation (iterative proportional navigation)
- Integration into dispatch_command() and step()
- Dashboard intercept geometry visualization
- Complete test plan (5 tests)
- Coordinate conventions and what NOT to do
