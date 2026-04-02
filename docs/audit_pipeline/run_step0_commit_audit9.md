# STEP 0: Commit Audit 9 — Autonomous Threat Response

## OBJECTIVE
Audit 9 code is COMPLETE but UNCOMMITTED. Your job:
1. Run the full test suite to verify everything passes
2. Verify the dashboard builds
3. Commit all Audit 9 work
4. Update STATUS.json

## PRE-FLIGHT

Run these commands:
```bash
cd /Users/johno/Desktop/localfleet
.venv/bin/python -m pytest tests/ -v
```
Expected: 152+ tests passing, 0 failures.

```bash
cd /Users/johno/Desktop/localfleet/dashboard && pnpm build 2>&1 | tail -5
```
Expected: "built in Xs" with no errors.

If tests fail, FIX THEM before committing. Read the failing test and the
relevant source file. The issue is likely in threat_detector.py or
fleet_manager.py's _check_threats() method.

## FILES TO COMMIT

These are the Audit 9 deliverables (verify they exist):

**New files (untracked):**
- `src/fleet/threat_detector.py` — ThreatAssessment + assess_threats()
- `tests/test_threat_detector.py` — 10 threat detection tests

**Modified files (unstaged):**
- `src/fleet/fleet_manager.py` — _check_threats(), threat state, get_fleet_state_dict()
- `src/api/ws.py` — uses get_fleet_state_dict() for WebSocket streaming
- `dashboard/src/App.jsx` — threat data handling
- `dashboard/src/components/ContactPanel.jsx` — intercept button
- `dashboard/src/components/FleetMap.jsx` — threat-colored markers
- `dashboard/src/components/MissionLog.jsx` — threat log entries
- `dashboard/src/components/MissionStatus.jsx` — threat alerts

Also commit the updated docs:
- `docs/audit9_prompt.md`

## COMMIT

```bash
cd /Users/johno/Desktop/localfleet
git add src/fleet/threat_detector.py tests/test_threat_detector.py
git add src/fleet/fleet_manager.py src/api/ws.py
git add dashboard/src/App.jsx
git add dashboard/src/components/ContactPanel.jsx
git add dashboard/src/components/FleetMap.jsx
git add dashboard/src/components/MissionLog.jsx
git add dashboard/src/components/MissionStatus.jsx
git add docs/audit9_prompt.md
```

Commit message:
```
feat: autonomous threat response — detect, track, recommend (Audit 9)

Adds threat detection engine that evaluates contacts by range and closing
rate. Auto-retasks drone to TRACK on warning range (5km). Recommends
intercept to operator at critical range (2km). Dashboard shows threat-
colored contacts, alerts, and intercept recommendation button.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

## POST-FLIGHT

1. Verify clean commit: `git log --oneline -1`
2. Verify no leftover changes: `git status`
   (audit_pipeline/ files and docs/ updates will show as untracked — that's fine)
3. Update STATUS.json: set audit 9 status to "done", add commit hash

## UPDATE STATUS.JSON

Read `/Users/johno/Desktop/localfleet/docs/audit_pipeline/STATUS.json`
and update the audit "9" entry:
- "status": "done"
- "commit": "<the commit hash>"

Write the updated file.
