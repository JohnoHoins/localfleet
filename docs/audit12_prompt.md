Execute Audit 12 — Decision Audit Trail for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 12
(Decision Audit Trail — Explainable Autonomy).

COMPLETED AUDITS: Audits 1-11 complete. Full kill chain working.
147+ tests passing. Do NOT break them.

YOUR TASK: Add explainable decision logging. Every autonomous action (intercept
prediction, asset allocation, threat assessment, auto-track, comms fallback,
replan) gets a human-readable rationale. Create a DecisionLog with entries
showing WHAT was decided, WHY, and what alternatives were considered. Expose
via API and display in the dashboard.

See the full AUDIT 12 specification in localfleet_audit_plan.md for:
- DecisionEntry and DecisionLog data structures
- All 6 decision instrumentation points
- GET /api/decisions endpoint
- Dashboard decision panel design
- Complete test plan (6 tests)
- What NOT to do
