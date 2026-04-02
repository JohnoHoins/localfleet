Execute Audit 13 — Mission-Specific Behaviors for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 13
AND the CRITICAL BLOCKERS section (especially Blockers 2 and 5).

COMPLETED AUDITS: Audits 1-12 complete (or: all prior audits complete).
Tests passing. Do NOT break them.

NOTE: This audit has NO dependency on Audits 10-12. It can run right after
Audit 9 for quick visual wins.

PRE-FLIGHT CHECK:
- Read fleet_manager.step() lines 281-292 — the waypoint completion logic
  that goes IDLE. This is the main code you're modifying.
- Read fleet_manager.dispatch_command() — you'll add mission-specific waypoint
  generation here (SEARCH zigzag, AERIAL_RECON drone SWEEP).
- Read src/fleet/drone_coordinator.py — you'll use assign_pattern() for
  ORBIT (patrol/loiter) and SWEEP (search/recon).
- Check that self.active_mission is set in dispatch_command() (line ~130).

YOUR TASK: Make each of the 6 mission types produce visually distinct behavior.
PATROL loops, SEARCH zigzags, ESCORT follows contacts, LOITER orbits,
AERIAL_RECON delegates to drone. INTERCEPT unchanged.

KEY CHANGES:
- step() waypoint completion block: instead of always going IDLE, check
  mission type. PATROL/SEARCH → reset i_wpt to 1 (loop). LOITER → generate
  orbit waypoints. Default → IDLE.
- dispatch_command(): SEARCH generates zigzag waypoints. ESCORT stores target.
  AERIAL_RECON overrides drone to SWEEP and surface to hold+loiter.
- New _mission_specific_step() for ESCORT continuous tracking.
- Extract all mission logic into helper methods (Blocker 2).
- 12 tests (up from 6).

See the full AUDIT 13 specification in localfleet_audit_plan.md for:
- Implementation details for each mission type
- _generate_search_pattern() helper
- ESCORT contact tracking via closest-contact convention
- LOITER orbit generation with single-generation flag
- AERIAL_RECON domain delegation
- Dashboard mission type color coding
- Complete test plan (12 tests)
- What NOT to do
