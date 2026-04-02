Execute Audit 10 — Comms-Denied Autonomy for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 10
AND the CRITICAL BLOCKERS section (especially Blockers 1, 3, and 8).

COMPLETED AUDITS: Audits 1-9 complete. Predictive intercept + auto threat
response working. Tests passing. Do NOT break them.

PRE-FLIGHT CHECK:
- Verify Audit 9 is committed (threat_detector.py, fleet_manager changes, dashboard).
  If not, commit it first. Run full test suite before starting.
- Verify fleet_manager._check_threats() sets intercept_recommended (you'll need it).
- Verify get_fleet_state_dict() injects threat data (you'll extend this pattern).

YOUR TASK: Add COMMS DENIED mode. When the C2 link goes down, the fleet
continues on last orders. If idle, it executes standing orders (RTB / hold).
If a threat reaches critical range with no operator, the fleet auto-engages
after a 60-second delay. This is fully autonomous operation under comms denial.

KEY ADDITIONS vs original spec:
- Store self.last_command on fleet_manager for comms-denied reference
- Autonomous escalation ladder: continue → fallback → auto-engage
- Dual failure support: GPS-denied + comms-denied simultaneously
- autonomous_actions log for post-denial review
- 12 tests (up from 8), including dual-failure and escalation tests

See the full AUDIT 10 specification in localfleet_audit_plan.md for:
- Comms mode state and set_comms_mode() method
- _handle_comms_denied() autonomous behavior in step()
- _execute_comms_fallback() and _auto_engage_threat() methods
- POST /api/comms-mode endpoint + command endpoint gating
- Dashboard comms-denied overlay with dual-failure display
- Complete test plan (12 tests)
- What NOT to do
