# Audit Pipeline

## Quick Start

Open a **new terminal** and run:

```bash
cd /Users/johno/Desktop/localfleet
./docs/audit_pipeline/run_audit.sh next
```

This auto-detects the next pending audit, runs pre-flight tests, and launches
Claude Code with the full prompt.

## Manual Run

If you prefer to run audits manually:

```bash
cd /Users/johno/Desktop/localfleet

# Open a new Claude Code session
claude

# Then tell it:
# "Execute Audit 11. Read and follow docs/audit_pipeline/run_step2_audit11.md"
```

## Or pipe directly:

```bash
cd /Users/johno/Desktop/localfleet
echo "Execute Audit 11 for LocalFleet. Read CLAUDE.md first, then follow every step in docs/audit_pipeline/run_step2_audit11.md. Run tests, commit, update STATUS.json." | claude
```

## Pipeline Status

Check `STATUS.json` for current progress:

```bash
cat docs/audit_pipeline/STATUS.json | python3 -m json.tool
```

## File Map

| File | Purpose |
|------|---------|
| STATUS.json | Machine-readable progress tracker |
| ORCHESTRATOR.md | How the pipeline works |
| run_audit.sh | Auto-launcher for next audit |
| run_step0_commit_audit9.md | Step 0: Commit Audit 9 (DONE) |
| run_step1_audit10.md | Step 1: Comms-Denied Autonomy (DONE) |
| run_step2_audit11.md | Step 2: Cross-Domain Kill Chain |
| run_step3_audit12.md | Step 3: Decision Audit Trail |
| run_step4_audit13.md | Step 4: Mission-Specific Behaviors |

## What Each Prompt Contains

Every step file is **fully self-contained** — a fresh Claude session can
execute it with zero prior context. Each includes:

- Pre-flight checks (verify previous audit committed, tests pass)
- Exact file paths and line numbers to read
- Complete code snippets to add/modify
- Full test file to create
- Dashboard changes
- Commit message (pre-written)
- Post-flight verification (test count, build check)
- STATUS.json update instructions
