# Master Prompt: GitHub Publication & System Monitor Dashboard

## CONTEXT

LocalFleet is a multi-domain autonomous fleet simulation with local LLM command & control.
It's being published on GitHub as a portfolio piece targeting defense tech companies.
The project runs air-gapped on Mac Studio M3 Ultra 256GB. Everything is local.

**Current state**: All 222 tests passing. Demo script verified. Fast parser + LLM fallback
working. Background sim loop, speed control, reset endpoint, drone transit fix — all done.

**This prompt covers two major deliverables**:
1. GitHub-ready sanitization and formatting
2. A "System Monitor" dashboard — a second window showing live under-the-hood internals

Read `CLAUDE.md` first. Read all files before modifying.

---

## PART 1: GITHUB SANITIZATION

### 1A. Sanitize Personal References

Replace personal names and paths throughout `docs/` files. **Do NOT modify source code files
under `src/` or `dashboard/src/` — they are already clean.**

Files to sanitize (replace "Johno" with "the operator" or remove, replace `/Users/johno/...`
with relative paths):
- `docs/demo_prep_prompt.md` — replace "Johno" with "the operator" throughout
- `docs/demo_final_script.md` — check for any personal references
- `docs/STEP11_VOICE_TEST_GUIDE.md` — replace absolute paths with relative
- `docs/audit_pipeline/README.md` — replace absolute paths with relative
- `docs/audit_pipeline/run_step0_commit_audit9.md` — replace absolute paths with relative
- `docs/simulation_analysis_prompt.md` — replace "Johno" with "the operator"
- `data/sim_full_analysis.md` — replace "Johno" references
- `data/sim_v2_observer_notes.md` — replace "Johno" with "operator" throughout
- `start_localfleet.command` — uses `$(dirname "$0")` already, should be clean

**Do NOT touch**:
- `.claude/` directory (it's gitignored)
- `docs/reference/` files (these are historical dumps, leave them or gitignore them)
- Any source code under `src/` or `dashboard/`
- `CLAUDE.md` (project instructions for Claude Code, fine to keep)

### 1B. Add/Update .gitignore

Ensure these are gitignored:
```
.claude/
docs/reference/all_source_code.txt
docs/reference/src_code.txt
docs/reference/dashboard_code.txt
docs/reference/tests_code.txt
docs/reference/config_files.txt
docs/reference/file_list.txt
docs/reference/project_tree.txt
docs/reference/memory_dump.txt
data/sim_runs/
data/*.csv
__pycache__/
*.pyc
.venv/
node_modules/
dist/
.env
*.sqlite
*.db
.DS_Store
```

### 1C. Create README.md

Create a compelling `README.md` at the project root. This is the first thing defense tech
recruiters and engineers will see. Structure:

```markdown
# LocalFleet — Edge-Native Autonomous Fleet C2

> Multi-domain autonomous fleet simulation with local LLM command & control.
> Voice/text → 72B language model → structured commands → simulated fleet.
> Everything runs air-gapped on Apple Silicon. No cloud. No API calls.

[Screenshot/GIF placeholder — add after recording demo]

## What This Demonstrates

- **Natural Language C2**: Voice and text commands parsed by a 72B parameter LLM
  running locally. Two-tier parsing: fast deterministic parser (<1ms) for structured
  commands, LLM fallback for ambiguous natural language.
- **Multi-Domain Coordination**: 3 surface vessels + 1 aerial drone operating
  together. Formation holding, mission-specific behaviors, cross-domain sensor fusion.
- **Kill Chain Automation**: Autonomous detect → track → lock → engage pipeline.
  Drone provides targeting data, fleet converges on predicted intercept point.
- **Degraded Operations**: Comms-denied autonomy with configurable standing orders,
  60-second escalation to autonomous engagement. GPS-denied dead reckoning with
  smooth position blending on restore.
- **Explainable Autonomy**: Every autonomous decision logged with rationale,
  confidence score, and audit trail. Full decision transparency.

## Architecture

[Include the architecture diagram from CLAUDE.md]

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, WebSocket (4Hz) |
| Frontend | React 18, Vite, Leaflet.js, Tailwind CSS |
| Physics | CORALL-based Nomoto model (surface), waypoint follower (drone) |
| LLM | Ollama + Qwen 2.5 72B (local inference) |
| Voice | mlx-whisper (Apple Silicon optimized) |
| Data | Pydantic schemas, SQLite mission logging |

## Quick Start

```bash
# Prerequisites: Python 3.11+, Node.js 18+, Ollama, pnpm
ollama pull qwen2.5:72b

# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.api.server:app --host 127.0.0.1 --port 8000

# Dashboard (separate terminal)
cd dashboard && pnpm install && pnpm dev

# Open http://localhost:5173
```

Or double-click `start_localfleet.command` to launch everything.

## Key Features

### Two-Tier Command Parsing
[Explain fast parser + LLM, with examples]

### Autonomous Threat Response
[Explain kill chain, auto-engage, escalation]

### Degraded Mode Operations
[Explain comms-denied, GPS-denied, standing orders]

### System Monitor
[Explain the under-the-hood dashboard — see Part 2]

## Hardware Requirements

- Apple Silicon Mac (M1 Ultra / M2 Ultra / M3 Ultra recommended)
- 64GB+ unified memory (128GB+ for 72B model at full speed)
- Ollama installed with qwen2.5:72b model pulled

Tested on Mac Studio M3 Ultra with 256GB unified memory.

## Tests

```bash
.venv/bin/python -m pytest tests/ -v  # 222 tests
```

## License

MIT
```

Make the README compelling but honest. No buzzwords without substance.
Use the actual test count (222) and real response times (15-21s LLM, <1ms fast parser).

### 1D. Create LICENSE

Add an MIT LICENSE file at the project root.

### 1E. Clean Up Unnecessary Files

Check for and remove (or gitignore) any files that shouldn't be in a public repo:
- Any `.env` files
- Any credential files
- Any personal notes not relevant to the project
- Excessively large data files

---

## PART 2: SYSTEM MONITOR DASHBOARD ("Under the Hood")

This is a **second browser window** that opens alongside the main fleet map. It shows
the live internals of the system — what's happening under the hood in real time.
Think of it as a "glass cockpit" for the simulation engine.

### 2A. Backend: Add a `/monitor/ws` WebSocket endpoint

Create a new file `src/api/monitor_ws.py` that streams system telemetry at 2Hz.

The monitor WebSocket should broadcast a JSON payload every 500ms containing:

```json
{
  "timestamp": 1234567890.123,
  "sim": {
    "tick_count": 12345,
    "time_scale": 4,
    "dt": 0.25,
    "assets_executing": 3,
    "assets_idle": 1
  },
  "command": {
    "last_text": "All vessels patrol to 2000 0 in echelon",
    "parse_method": "fast",       // "fast" or "llm"
    "parse_time_ms": 0.4,         // or 17234 for LLM
    "mission_type": "patrol",
    "shadow_status": "pending"    // "pending", "agree", "mismatch", "disabled"
  },
  "threats": {
    "contact_count": 2,
    "critical": 1,
    "warning": 1,
    "intercept_recommended": true,
    "kill_chain_phase": "TRACK",
    "auto_engage_countdown": 45.2  // seconds remaining, null if not applicable
  },
  "comms": {
    "mode": "denied",
    "denied_duration": 23.5,
    "standing_orders": "continue_mission",
    "autonomous_actions": ["AUTO-HOLD: comms_denied_standing_order"],
    "fallback_executed": true
  },
  "gps": {
    "mode": "full",
    "dr_drift_meters": 0.0,
    "blending": false
  },
  "decisions": [
    {
      "time": "14:23:05",
      "type": "threat_assessment",
      "action": "bogey-1: CRITICAL 890m",
      "confidence": 0.89
    }
  ],
  "performance": {
    "ws_clients": 2,
    "step_time_us": 450,    // microseconds per sim step
    "ollama_loaded": true,
    "ollama_model": "qwen2.5:72b"
  }
}
```

**Implementation**:
- Add a new `create_monitor_router()` in `src/api/monitor_ws.py`
- The monitor reads from `fleet_manager` state (same as the main WS, but different data)
- Track `parse_method` and `parse_time_ms` by storing last command metadata on the commander
- Track `step_time_us` by timing `commander.step()` in the background loop
- Mount it in `server.py` alongside the existing routers
- The monitor WS endpoint should be at `/monitor/ws`

### 2B. Frontend: System Monitor Page

Create `dashboard/src/monitor.html` and `dashboard/src/MonitorApp.jsx` — a separate
React entry point that renders the system monitor.

**Layout**: Dark terminal aesthetic, monospace font, 4-panel grid:

```
┌─────────────────────────┬─────────────────────────┐
│   COMMAND PARSER        │   THREAT ENGINE         │
│                         │                         │
│ > "patrol to 2000..."   │ Contacts: 2             │
│ Method: FAST (0.4ms)    │ CRITICAL: bogey-1 890m  │
│ Mission: patrol         │ Kill Chain: TRACK       │
│ Formation: echelon      │ Auto-engage: 45s        │
│ Shadow: ✓ agree         │ Drone: tracking bogey-1 │
│                         │                         │
├─────────────────────────┼─────────────────────────┤
│   SIMULATION ENGINE     │   DECISION LOG          │
│                         │                         │
│ Tick: 12345  Speed: 4x  │ 14:23:05 [THREAT]       │
│ Assets: 3 exec / 1 idle │   bogey-1 CRITICAL 890m │
│ Comms: DENIED (23s)     │   conf: 0.89            │
│ GPS: FULL               │ 14:23:04 [AUTO_TRACK]   │
│ Standing: continue      │   Eagle-1 → bogey-1     │
│ Step: 450μs             │ 14:23:02 [KILL_CHAIN]   │
│ Ollama: loaded (72B)    │   DETECT → TRACK        │
│ WS clients: 2           │                         │
└─────────────────────────┴─────────────────────────┘
```

**Design principles**:
- Dark background (#0a0e17), green/cyan/amber terminal colors
- Monospace font throughout (SF Mono, Fira Code, or system monospace)
- Values that change should flash briefly (CSS animation, 200ms highlight)
- CRITICAL threats pulse red
- Fast parse results show in green, LLM results show in amber
- Decision log scrolls automatically, newest at top, last 20 entries
- Auto-engage countdown shows as a progress bar when active
- Kill chain phase shows as a pipeline: DETECT → TRACK → LOCK → ENGAGE with
  the active phase highlighted

**Vite configuration**: Add a second entry point in `vite.config.js`:
```js
build: {
  rollupOptions: {
    input: {
      main: 'index.html',
      monitor: 'monitor.html',
    }
  }
}
```

The monitor page should be accessible at `http://localhost:5173/monitor.html`.

### 2C. Update the Launcher

Modify `start_localfleet.command` to open BOTH windows:
```bash
open http://localhost:5173                    # Main dashboard
open http://localhost:5173/monitor.html       # System monitor
```

The idea is: main dashboard on the primary monitor, system monitor on a second monitor
(or side-by-side). For the demo video, this gives a "mission control" feel.

### 2D. Store Command Metadata for Monitor

In `fleet_commander.py`, after each command (fast or LLM), store metadata that the
monitor can read:

```python
self.last_parse_info = {
    "text": request.text,
    "method": "fast",  # or "llm"
    "time_ms": elapsed_ms,
    "mission": command.mission_type.value,
    "formation": command.formation.value,
    "shadow_status": "pending",  # updated by shadow thread
}
```

The shadow verification thread should update `shadow_status` to "agree" or "mismatch"
when it completes.

---

## PART 3: IMPRESSIVE FIXES & POLISH

These are small changes that make the system feel production-grade when people browse
the GitHub repo or watch the demo.

### 3A. Add Command Response Indicator to Dashboard

In the main dashboard's `CommandPanel`, after a command is sent, show:
- Parse method badge: green "FAST" or amber "LLM" with response time
- This tells the viewer which parsing tier handled the command

### 3B. Add Formation Visualization to Map

In `FleetMap.jsx`, draw thin lines connecting formation members to show the formation
geometry. For echelon: diagonal lines. For column: straight line through all vessels.
Lines should be subtle (semi-transparent cyan, 1px).

### 3C. Add Intercept Prediction Line

When the fleet is on an intercept mission and a contact exists, draw a dashed line
from the fleet centroid to the predicted intercept point. This makes the predictive
navigation visible on the map.

### 3D. Add Contact Heading Indicator

For each contact on the map, draw a small heading line (30px, red, from the contact
marker in the direction of movement). This shows which way threats are moving.

### 3E. Add Threat Range Rings

When a contact is at WARNING or CRITICAL range, draw a semi-transparent circle on the
map at 2000m (critical boundary) centered on the fleet centroid. This visualizes the
threat zones.

### 3F. Command History Panel

Add a small collapsible panel in the dashboard sidebar that shows the last 5 commands
with their parse method and time. Format:
```
> "patrol to 2000 0 in echelon"     FAST  0.4ms
> "all assets search area..."        FAST  0.3ms
> "complex ambiguous command..."     LLM   17.2s
```

---

## EXECUTION ORDER

1. **Read all files first** — understand the codebase before changing anything
2. **Part 1** — GitHub sanitization (docs cleanup, README, LICENSE, .gitignore)
3. **Part 2A** — Monitor WebSocket backend
4. **Part 2D** — Command metadata storage
5. **Part 2B** — Monitor frontend (React app)
6. **Part 2C** — Update launcher
7. **Part 3A-F** — Dashboard polish (map visuals, command panel badges)
8. **Run all 222 tests** — must still pass
9. **Commit everything**

## RULES

- **SCHEMAS ARE GOD** — do not modify `src/schemas.py`
- **Test after each major change** — run `pytest tests/ -v`
- **Don't break existing functionality** — the main dashboard must still work perfectly
- **Keep it clean** — no unnecessary abstractions, no over-engineering
- **Two files max per sub-task** — but multiple sub-tasks are OK across sessions
