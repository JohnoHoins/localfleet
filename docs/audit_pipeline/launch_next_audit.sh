#!/bin/bash
# ──────────────────────────────────────────────────────────
# LocalFleet Audit Pipeline Launcher
# Reads STATUS.json, finds the next pending audit, and
# launches a fresh Claude Code session with the full prompt.
# ──────────────────────────────────────────────────────────

set -e
cd "$(dirname "$0")/../.."  # project root

STATUS_FILE="docs/audit_pipeline/STATUS.json"
PIPELINE_DIR="docs/audit_pipeline"

# Find next pending audit
NEXT_AUDIT=$(python3 -c "
import json
with open('$STATUS_FILE') as f:
    data = json.load(f)
order = ['10', '11', '12', '13']
for a in order:
    if data['audits'][a]['status'] == 'pending':
        print(a)
        break
" 2>/dev/null)

if [ -z "$NEXT_AUDIT" ]; then
    echo "✅ ALL AUDITS COMPLETE"
    echo ""
    python3 -c "
import json
with open('$STATUS_FILE') as f:
    data = json.load(f)
for k, v in data['audits'].items():
    status = v['status']
    commit = v.get('commit', '—')
    print(f'  Audit {k}: {v[\"name\"]:40s} {status:10s} {commit}')
"
    exit 0
fi

# Map audit number to step file
declare -A STEP_MAP
STEP_MAP[10]="run_step1_audit10.md"
STEP_MAP[11]="run_step2_audit11.md"
STEP_MAP[12]="run_step3_audit12.md"
STEP_MAP[13]="run_step4_audit13.md"

PROMPT_FILE="${PIPELINE_DIR}/${STEP_MAP[$NEXT_AUDIT]}"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "❌ Prompt file not found: $PROMPT_FILE"
    exit 1
fi

echo "╔══════════════════════════════════════════════════════╗"
echo "║  LOCALFLEET AUDIT PIPELINE                          ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Next: Audit $NEXT_AUDIT — $(python3 -c "
import json
with open('$STATUS_FILE') as f:
    data = json.load(f)
print(data['audits']['$NEXT_AUDIT']['name'])
")"
echo "║  Prompt: $PROMPT_FILE"
echo "║  Tests baseline: $(python3 -c "
import json
with open('$STATUS_FILE') as f:
    data = json.load(f)
# Sum tests from completed audits
total = data['test_baseline']
for k, v in data['audits'].items():
    if v['status'] == 'done':
        total += v.get('tests_added', 0)
print(total)
") passing"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Launching Claude Code in new terminal..."
echo ""

# Launch claude with the prompt file contents
# --print forces non-interactive output; omit for interactive session
cat "$PROMPT_FILE"
echo ""
echo "─────────────────────────────────────────────"
echo "👆 Copy everything above and paste into a new Claude Code session,"
echo "   or run:"
echo ""
echo "   claude --print < $PROMPT_FILE"
echo ""
echo "   Or for interactive mode:"
echo ""
echo "   claude"
echo "   (then paste the prompt)"
echo ""
