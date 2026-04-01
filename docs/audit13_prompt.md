Execute Audit 13 — Mission-Specific Behaviors for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 13
(Mission-Specific Behaviors — Make Each Mission Type Matter).

COMPLETED AUDITS: Audits 1-12 complete. Full autonomous C2 system working.
147+ tests passing. Do NOT break them.

YOUR TASK: Make each of the 6 mission types produce visually distinct behavior.
Currently ALL missions just follow waypoints. Fix so:
- PATROL: loops back to first waypoint (continuous circuit)
- SEARCH: generates zigzag lawnmower pattern from center point
- ESCORT: maintains formation offset relative to a moving contact
- LOITER: orbits in a small circle after reaching the waypoint
- AERIAL_RECON: drone sweeps wide area, surface vessels hold position
- INTERCEPT: already enhanced (no changes)

See the full AUDIT 13 specification in localfleet_audit_plan.md for:
- Implementation details for each mission type
- Minimal changes to dispatch_command() and step()
- Dashboard considerations
- Complete test plan (6 tests)
- What NOT to do
