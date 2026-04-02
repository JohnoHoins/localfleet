Execute Audit 12 — Decision Audit Trail for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 12
AND the CRITICAL BLOCKERS section.

COMPLETED AUDITS: Audits 1-11 complete. Full kill chain working.
Tests passing. Do NOT break them.

PRE-FLIGHT CHECK:
- Read ALL decision points you'll instrument:
  fleet_manager.dispatch_command() (intercept solution + asset allocation)
  fleet_manager._replan_intercept() (replan)
  fleet_manager._check_threats() (threat assessment + auto-track)
  fleet_manager._handle_comms_denied() (comms fallback + auto-engage)
  fleet_manager._advance_kill_chain() (kill chain transitions)
- Read fleet_manager.get_fleet_state_dict() — you'll add data["decisions"]

YOUR TASK: Add explainable decision logging. Create DecisionLog with
DecisionEntry dataclass. Instrument ALL 7+ decision points with human-readable
rationales. Stream last 10 decisions via WebSocket. Expose full history via REST.
Add confidence scores and decision chain linking (parent → child).

KEY ADDITIONS vs original spec:
- Confidence field based on sensor quality/GPS mode/range
- Parent-child decision linking via parent_id
- WebSocket streaming (data["decisions"] in get_fleet_state_dict)
- to_dicts() serialization for both WebSocket and REST
- 12 tests (up from 6), including chain linking, API, and per-type tests

See the full AUDIT 12 specification in localfleet_audit_plan.md for:
- src/fleet/decision_log.py — DecisionEntry + DecisionLog classes
- All 7 instrumentation points with example rationale strings
- get_fleet_state_dict() streaming integration
- GET /api/decisions endpoint
- Dashboard decision panel design
- Complete test plan (12 tests)
- What NOT to do
