Execute Audit 9 — Autonomous Threat Response for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 9
(Autonomous Threat Response — Auto-Detect and Propose).

COMPLETED AUDITS: Audits 1-8 complete. Predictive intercept working.
152 backend tests passing. Do NOT break them.

YOUR TASK: Build a threat detection engine that evaluates contacts by range
and closing rate. When a contact enters warning range (5km), auto-retask the
drone to TRACK it. When critical range (2km), recommend intercept to the
operator via the dashboard. The drone auto-responds; surface vessels wait for
operator approval. This is human-on-the-loop autonomy.

See the full AUDIT 9 specification in localfleet_audit_plan.md for:
- ThreatAssessment data structure and assess_threats() function
- Detection range thresholds (8km/5km/2km)
- Auto-drone retask logic
- Dashboard threat overlay (range rings, color-coded markers, intercept button)
- Complete test plan (10 tests)
- What NOT to do
