# LocalFleet Audit Pipeline — Orchestration Guide

## How This Works

Each audit is a self-contained agent prompt in `docs/audit_pipeline/`.
The orchestrator (you) launches agents sequentially. Each agent:

1. Reads its prompt file for full context
2. Reads current STATUS.json to verify prerequisites
3. Does the work (backend code + tests + dashboard)
4. Runs the full test suite
5. Commits with a descriptive message
6. Updates STATUS.json with commit hash and test count
7. Returns a summary

## Pipeline Order

```
STEP 0: Commit Audit 9 (uncommitted work)
   └→ run_step0_commit_audit9.md
   └→ Verify: 152+ tests pass, clean git status

STEP 1: Audit 10 — Comms-Denied Autonomy
   └→ run_step1_audit10.md
   └→ Verify: 164+ tests pass, POST /api/comms-mode works

STEP 2: Audit 11 — Cross-Domain Kill Chain
   └→ run_step2_audit11.md
   └→ Verify: 176+ tests pass, drone sensor + kill chain phases

STEP 3: Audit 12 — Decision Audit Trail
   └→ run_step3_audit12.md
   └→ Verify: 188+ tests pass, GET /api/decisions works

STEP 4: Audit 13 — Mission-Specific Behaviors
   └→ run_step4_audit13.md
   └→ Verify: 200+ tests pass, all 6 mission types distinct
```

## Launching an Agent

Use this pattern for each step:

```
Agent(
  subagent_type="general-purpose",
  prompt=<contents of run_stepN_auditNN.md>,
  description="Execute Audit NN"
)
```

After the agent returns:
1. Read STATUS.json — verify it was updated
2. Run: `.venv/bin/python -m pytest tests/ -v` — verify tests pass
3. Run: `git log --oneline -3` — verify commit was made
4. If all green → launch next step
5. If tests fail → diagnose before continuing

## Context Retrieval Strategy

Each agent prompt includes:
- **EXACT FILE PATHS** and line numbers for every file it needs to read
- **CODE SNIPPETS** showing what exists and what to add
- **SCHEMAS** — key types from src/schemas.py (inline, not "go read it")
- **EXISTING METHOD SIGNATURES** — so the agent doesn't have to explore
- **TEST PATTERNS** — examples of how existing tests are structured
- **COMMIT MESSAGE** — pre-written, agent just runs it

This eliminates the exploration phase. The agent starts coding immediately.

## Recovery

If an agent fails mid-audit:
- Check git status for partial changes
- Read STATUS.json for last known good state
- Re-launch the same step with additional context about what failed
- Never skip an audit — the dependency chain is strict (except 13)

## Dashboard Build Verification

After each audit that touches dashboard files:
```bash
cd dashboard && pnpm build 2>&1 | tail -5
```
Must show "built in Xs" with no errors.
