#!/bin/bash
# ──────────────────────────────────────────────────────────
# Run a specific audit in a NEW Claude Code terminal session
#
# Usage:
#   ./docs/audit_pipeline/run_audit.sh 11
#   ./docs/audit_pipeline/run_audit.sh next    (auto-picks next pending)
# ──────────────────────────────────────────────────────────

set -e
cd "$(dirname "$0")/../.."  # project root

STATUS_FILE="docs/audit_pipeline/STATUS.json"
PIPELINE_DIR="docs/audit_pipeline"

# Determine which audit to run
AUDIT_NUM="$1"

if [ -z "$AUDIT_NUM" ] || [ "$AUDIT_NUM" = "next" ]; then
    AUDIT_NUM=$(python3 -c "
import json
with open('$STATUS_FILE') as f:
    data = json.load(f)
order = ['10', '11', '12', '13']
for a in order:
    if data['audits'][a]['status'] == 'pending':
        print(a)
        break
" 2>/dev/null)
fi

if [ -z "$AUDIT_NUM" ]; then
    echo "✅ All audits complete! Nothing left to run."
    exit 0
fi

# Map audit number to step file
declare -A STEP_MAP
STEP_MAP[10]="run_step1_audit10.md"
STEP_MAP[11]="run_step2_audit11.md"
STEP_MAP[12]="run_step3_audit12.md"
STEP_MAP[13]="run_step4_audit13.md"

PROMPT_FILE="${PIPELINE_DIR}/${STEP_MAP[$AUDIT_NUM]}"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "❌ No prompt file for audit $AUDIT_NUM"
    exit 1
fi

AUDIT_NAME=$(python3 -c "
import json
with open('$STATUS_FILE') as f:
    data = json.load(f)
print(data['audits']['$AUDIT_NUM']['name'])
")

# Pre-flight: verify tests pass
echo "╔══════════════════════════════════════════════════════╗"
echo "║  AUDIT $AUDIT_NUM: $AUDIT_NAME"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Pre-flight: running test suite...                  ║"
echo "╚══════════════════════════════════════════════════════╝"

TEST_RESULT=$(.venv/bin/python -m pytest tests/ -q 2>&1 | tail -1)
echo "  Tests: $TEST_RESULT"
echo ""

if echo "$TEST_RESULT" | grep -q "failed"; then
    echo "❌ Tests failing — fix before running audit $AUDIT_NUM"
    exit 1
fi

# Build the full prompt with project context header
FULL_PROMPT="Execute Audit $AUDIT_NUM for the LocalFleet project at $(pwd).

Read CLAUDE.md first for project rules (especially: never modify schemas.py, test before committing).

Then read and follow the step-by-step instructions in: $(pwd)/$PROMPT_FILE

That file contains EVERYTHING needed: exact code to write, where to add it, tests, commit message, and post-flight verification.

After completing the work:
1. Run: .venv/bin/python -m pytest tests/ -v (ALL must pass)
2. Run: cd dashboard && pnpm build (must succeed)
3. Commit with the message specified in the prompt file
4. Update docs/audit_pipeline/STATUS.json — set audit $AUDIT_NUM status to 'done' and add commit hash
5. Do NOT stage docs/audit_pipeline/ or docs/localfleet_audit_plan.md in the commit

Report: test count, commit hash, any issues."

echo "Launching Claude Code for Audit $AUDIT_NUM..."
echo "─────────────────────────────────────────────"

# Open new macOS Terminal window with claude
osascript -e "
tell application \"Terminal\"
    activate
    do script \"cd $(pwd) && echo '$FULL_PROMPT' | claude\"
end tell
" 2>/dev/null || {
    # Fallback: just print the command to run
    echo ""
    echo "Run this in a new terminal:"
    echo ""
    echo "  cd $(pwd)"
    echo "  claude"
    echo ""
    echo "Then paste this prompt:"
    echo "────────────────────────────────────────"
    echo "$FULL_PROMPT"
    echo "────────────────────────────────────────"
}
