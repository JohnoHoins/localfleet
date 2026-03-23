# LOCALFLEET — MASTER BUILD PROMPT v2.0
## Paste this ENTIRE document into a fresh Claude session with maximum context

---

# WHO I AM

I'm John, a finance/economics student at Roger Williams University in Rhode Island. I have ZERO coding experience. I run a 70-person hockey camp business. I'm building a portfolio project to get hired at HavocAI, a defense-tech company 20 minutes from my school that builds collaborative autonomous systems for the US military. I have a Mac Studio M3 Ultra with 256GB RAM — one of the most powerful personal computers on Earth for running AI locally.

# WHAT I'M BUILDING

**LocalFleet** — a local-first, multi-domain LLM command & control system for autonomous fleet simulation. I speak or type a natural language command. A local 70B-parameter AI (running on my machine via Ollama, no internet) interprets it. Simulated surface vessels AND a drone on a map start moving in coordinated patterns. Everything runs air-gapped — zero data leaves my machine. This mirrors HavocAI's "Havoc Orchestrator" and "Havoc Control" products, and directly aligns with their December 2025 GPS-denied air-sea demo in Portugal and their March 2026 acquisitions of Mavrik (drones) and Teleo (ground autonomy).

# WHY MULTI-DOMAIN

HavocAI is no longer just a maritime company. On March 11, 2026 they acquired a drone company (Mavrik) and a ground vehicle autonomy company (Teleo). Their biggest demo was air+sea coordination without GPS. My project demonstrates surface vessels + a drone, commanded through natural language, through one interface. This shows I understand where they're GOING, not where they were.

# MY HARDWARE

- Mac Studio M3 Ultra, 256GB unified memory
- Can run 70B+ parameter LLMs locally at 10-20 tokens/second
- macOS, Apple Silicon native

# SHIP DATE: July 5, 2026

---

# TECHNOLOGY STACK

| Layer | Technology | Purpose |
|-------|-----------|---------|
| LLM | Ollama + Qwen 2.5 72B | Local AI inference, structured JSON output |
| Maritime Sim | CORALL (Queen's University Belfast, MIT license) | Vessel dynamics, COLREGS, CPA/TCPA risk |
| Drone Sim | Custom drone_dynamics.py (~50 lines) | Simple 2D+altitude waypoint follower |
| Backend | Python 3.11 + FastAPI + WebSocket | API server, real-time state streaming at 4Hz |
| Frontend | React 18 + Leaflet.js + Tailwind CSS | Dark military C2 dashboard with live map |
| Voice | mlx-whisper (Apple Silicon optimized) | Local speech-to-text |
| Data | Pydantic schemas + SQLite | Type validation + mission logging |
| GPS-Denied | Custom gps_denied.py (~30 lines) | Position noise + degraded update rate |

---

# ABSOLUTE RULES — NEVER VIOLATE THESE

## Rule 1: SCHEMAS ARE GOD
Every single module in this project imports its data types from ONE file: `src/schemas.py`. If a module creates or expects data that doesn't match the schemas, THE MODULE IS WRONG. Never modify the schemas to fit broken code. Fix the code.

## Rule 2: ONE FILE PER SESSION
Each Claude Code session works on ONE module (two maximum). Never "build the whole backend." Small, specific, testable units.

## Rule 3: TEST BEFORE MOVING ON
After writing a file, RUN IT in the same session. Don't move to the next module with broken code behind you.

## Rule 4: NEVER REFACTOR WORKING CODE
If a module works, don't let any AI session "improve" or "refactor" it later. It will break things guessing at code it can't fully see. Working code is sacred.

## Rule 5: BUILD BOTTOM-UP ONLY
Follow the exact build order below. Each module depends only on modules built before it. Never skip ahead.

## Rule 6: SCOPE IS LOCKED
- 3 surface vessels (alpha, bravo, charlie) + 1 drone (eagle-1) = 4 assets total
- 5 mission types: patrol, search, escort, loiter, aerial_recon
- 1 LLM model in demo (Qwen 72B or Llama 3 70B — whichever works better)
- Dashboard does 6 things: map, asset cards, command input, event log, risk display, GPS-denied toggle
- Drone model is SIMPLE: position, altitude, heading, speed, waypoint following. No aerodynamics.
- GPS-denied is COSMETIC: random noise on positions, reduced update rate, visual indicators.

## Rule 7: COMMIT EVERY DAY
Even a README typo. Green squares = momentum.

---

# THE COMPLETE DATA CONTRACTS — src/schemas.py

This is the ENTIRE source of truth. Create this file FIRST, before any other code. Paste it into every Claude Code session.

```python
"""
LocalFleet Data Contracts v2.0 — Multi-Domain
THE source of truth for all modules.
Every module imports from this file. DO NOT define data structures elsewhere.

v2.0 Changes:
- Added DomainType enum (SURFACE, AIR)
- Asset-generic naming (AssetCommand, AssetState)
- Altitude field for air domain
- GPS-denied degradation fields
- DronePattern enum for aerial behaviors
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime


# ============================================================
# ENUMS — Shared across all modules
# ============================================================

class DomainType(str, Enum):
    """Which domain this asset operates in."""
    SURFACE = "surface"    # Vessels — uses CORALL dynamics
    AIR = "air"            # Drones — uses drone_dynamics.py

class MissionType(str, Enum):
    """The 5 mission types LocalFleet supports. No more."""
    PATROL = "patrol"
    SEARCH = "search"
    ESCORT = "escort"
    LOITER = "loiter"
    AERIAL_RECON = "aerial_recon"

class FormationType(str, Enum):
    """How surface vessels arrange relative to each other."""
    ECHELON = "echelon"
    LINE_ABREAST = "line"
    COLUMN = "column"
    SPREAD = "spread"
    INDEPENDENT = "independent"

class DronePattern(str, Enum):
    """How a drone operates over an area."""
    ORBIT = "orbit"
    SWEEP = "sweep"
    TRACK = "track"
    STATION = "station"

class AssetStatus(str, Enum):
    """Current operational state of any asset."""
    IDLE = "idle"
    EXECUTING = "executing"
    AVOIDING = "avoiding"       # COLREGS avoidance (surface only)
    RETURNING = "returning"
    ERROR = "error"

class GpsMode(str, Enum):
    """GPS availability state."""
    FULL = "full"
    DEGRADED = "degraded"


# ============================================================
# COMMANDS — What the operator sends IN
# ============================================================

class Waypoint(BaseModel):
    """A point in 2D space (meters, local frame)."""
    x: float
    y: float

class AssetCommand(BaseModel):
    """
    Command for a single asset (surface OR air).
    The domain field determines which dynamics engine processes it.
    """
    asset_id: str               # "alpha", "bravo", "charlie", "eagle-1"
    domain: DomainType          # SURFACE or AIR
    waypoints: List[Waypoint]
    speed: float = 5.0          # m/s (surface ~5, drone ~15)
    altitude: Optional[float] = None  # meters — only for AIR domain
    behavior: str = "waypoint"  # "waypoint", "loiter", "search", "orbit", "sweep", "track"
    drone_pattern: Optional[DronePattern] = None  # Only for AIR domain

class FleetCommand(BaseModel):
    """
    THE central command object. The LLM produces this from natural
    language input. Every module that processes commands accepts this.
    Now supports BOTH surface and air assets in a single command.
    """
    mission_type: MissionType
    assets: List[AssetCommand]  # Can contain mixed SURFACE + AIR
    formation: FormationType = FormationType.INDEPENDENT
    spacing_meters: float = 200.0
    colregs_compliance: bool = True
    comms_lost_behavior: str = "return_to_base"
    raw_text: Optional[str] = None


# ============================================================
# STATE — What the simulation sends OUT
# ============================================================

class AssetState(BaseModel):
    """
    Current state of one asset (surface or air).
    Sent via WebSocket to the React dashboard every tick.
    """
    asset_id: str
    domain: DomainType
    x: float
    y: float
    heading: float              # Degrees, 0 = North
    speed: float
    altitude: Optional[float] = None
    status: AssetStatus
    mission_type: Optional[MissionType] = None
    current_waypoint_index: int = 0
    total_waypoints: int = 0
    risk_level: float = 0.0
    cpa: Optional[float] = None
    tcpa: Optional[float] = None
    drone_pattern: Optional[DronePattern] = None
    gps_mode: GpsMode = GpsMode.FULL
    position_accuracy: float = 1.0

class FleetState(BaseModel):
    """
    State of the entire fleet. Sent via WebSocket every tick (4Hz).
    The React dashboard receives this exact JSON shape.
    """
    timestamp: float
    assets: List[AssetState]
    active_mission: Optional[MissionType] = None
    formation: FormationType = FormationType.INDEPENDENT
    gps_mode: GpsMode = GpsMode.FULL


# ============================================================
# EVENTS — What gets logged
# ============================================================

class MissionEvent(BaseModel):
    """A logged event for mission replay."""
    timestamp: float
    event_type: str             # "command", "state", "decision", "risk", "gps_change"
    asset_id: Optional[str] = None
    domain: Optional[DomainType] = None
    data: dict
    created_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# API — Request/Response shapes for FastAPI endpoints
# ============================================================

class CommandRequest(BaseModel):
    """POST /api/command — what the dashboard sends."""
    text: str
    source: str = "text"

class CommandResponse(BaseModel):
    """POST /api/command — what the server responds with."""
    success: bool
    fleet_command: Optional[FleetCommand] = None
    error: Optional[str] = None
    llm_response_time_ms: Optional[float] = None

class GpsDeniedRequest(BaseModel):
    """POST /api/gps-mode — toggle GPS degradation."""
    mode: GpsMode
    noise_meters: float = 25.0
    update_rate_hz: float = 1.0
```

---

# DATA FLOW — How Everything Connects

```
USER (voice or text)
    │
    ▼
CommandRequest { text: "Alpha and Bravo patrol harbor, Eagle aerial recon" }
    │
    ▼
[Fleet Commander] ── calls Ollama with FleetCommand.model_json_schema() ──▶ FleetCommand
    │
    ▼
FleetCommand {
  mission_type: "patrol",
  assets: [
    { asset_id: "alpha", domain: "surface", waypoints: [...], speed: 5.0 },
    { asset_id: "bravo", domain: "surface", waypoints: [...], speed: 5.0 },
    { asset_id: "eagle-1", domain: "air", waypoints: [...], altitude: 100, drone_pattern: "sweep" }
  ],
  formation: "echelon"
}
    │
    ▼
[Fleet Manager] ── routes by domain:
    ├── SURFACE assets → CORALL dynamics instances (vessel_dynamics.py, controller.py)
    └── AIR assets → DroneAgent instance (drone_dynamics.py)
    │
    ▼
[Each tick (dt=0.25s)]:
    ├── CORALL steps vessel physics + COLREGS avoidance
    ├── DroneAgent steps toward waypoint at altitude
    └── If GPS-denied: gps_denied.py adds noise to all positions
    │
    ▼
FleetState { timestamp: 12.5, assets: [AssetState, AssetState, ...], gps_mode: "full" }
    │
    ▼
[WebSocket at 4Hz] ── sends JSON to React dashboard
    │
    ▼
Dashboard renders vessels (ship icon) + drone (plane icon) on dark Leaflet map
```

---

# SYSTEM ARCHITECTURE DIAGRAM

```
┌──────────────────────────────────────────────────────────────────┐
│                      OPERATOR INTERFACE                          │
│  ┌──────────┐  ┌───────────┐  ┌───────────────────────────┐    │
│  │  Voice   │  │  Text     │  │     React Dashboard       │    │
│  │ (Whisper)│  │  (CLI)    │  │  (Leaflet + D3)           │    │
│  └────┬─────┘  └─────┬─────┘  │  Ship icons = surface     │    │
│       └───────────┬───┘        │  Plane icons = air        │    │
│              ┌────▼──────┐     │  GPS-denied toggle        │    │
│              │ LOCAL LLM │◄────┘                           │    │
│              │ Ollama    │  (feedback)                     │    │
│              │ Qwen 72B  │                                 │    │
│              └────┬──────┘                                 │    │
│              ┌────▼─────────────────────┐                  │    │
│              │ Fleet Commander          │                  │    │
│              │ NL → AssetCommand[]      │                  │    │
│              │ Routes surface + air     │                  │    │
│              └────┬─────────────────────┘                  │    │
├───────────────────┼────────────────────────────────────────┤    │
│            FLEET COORDINATION LAYER                         │    │
│  ┌────────────────▼──────────────────────────────────┐     │    │
│  │ Fleet Manager                                      │     │    │
│  │ • Asset registry (vessels + drone)                 │     │    │
│  │ • Domain-aware state tracking                      │     │    │
│  │ • Surface formations (echelon/line/spread/column)  │     │    │
│  │ • Cross-domain task allocation                     │     │    │
│  │ • GPS-denied degradation engine                    │     │    │
│  └──┬──────────┬──────────┬──────────┬───────────────┘     │    │
├─────┼──────────┼──────────┼──────────┼─────────────────────┤    │
│  SURFACE       SURFACE    SURFACE    AIR                    │    │
│  ┌──▼─────┐┌──▼─────┐┌──▼─────┐ ┌──▼──────────────┐      │    │
│  │ alpha  ││ bravo  ││charlie │ │ eagle-1          │      │    │
│  │CORALL  ││CORALL  ││CORALL  │ │ drone_dynamics   │      │    │
│  │dynamics││dynamics││dynamics│ │ 2D + altitude     │      │    │
│  │colregs ││colregs ││colregs │ │ waypoint follow   │      │    │
│  └────────┘└────────┘└────────┘ └───────────────────┘      │    │
│                                                             │    │
│  ┌─────────────────────────────────────────────────┐       │    │
│  │ GPS-Denied Engine: noise + reduced update rate   │       │    │
│  └─────────────────────────────────────────────────┘       │    │
│  ┌─────────────────────────────────────────────────┐       │    │
│  │ WebSocket Server (FastAPI) → streams at 4Hz      │       │    │
│  └─────────────────────────────────────────────────┘       │    │
└─────────────────────────────────────────────────────────────┘
```

---

# COMPLETE FILE STRUCTURE

```
localfleet/
├── .venv/                          # Virtual environment (gitignored)
├── .gitignore
├── README.md
├── pyproject.toml
├── Makefile
│
├── corall-upstream/                # CORALL clone (gitignored, reference only)
│
├── src/
│   ├── __init__.py
│   ├── schemas.py                  # THE source of truth — ALL data types
│   │
│   ├── core/                       # FROM CORALL (adapted for multi-asset)
│   │   ├── __init__.py
│   │   ├── simulation.py           # Main sim loop — surface + air
│   │   └── integration.py          # Numerical integration (unchanged)
│   │
│   ├── dynamics/                   # FROM CORALL + drone extension
│   │   ├── __init__.py
│   │   ├── vessel_dynamics.py      # FROM CORALL (unchanged)
│   │   ├── controller.py           # FROM CORALL (unchanged)
│   │   ├── actuator_modeling.py    # FROM CORALL (unchanged)
│   │   └── drone_dynamics.py       # YOUR NEW: simple 2D+altitude model
│   │
│   ├── navigation/                 # FROM CORALL (unchanged)
│   │   ├── __init__.py
│   │   ├── planning.py
│   │   ├── obstacle_sim.py
│   │   └── reactive_avoidance.py
│   │
│   ├── risk_assessment/            # FROM CORALL (unchanged)
│   │   ├── __init__.py
│   │   ├── cpa_calculations.py
│   │   └── risk_calculations.py
│   │
│   ├── decision_making/            # FROM CORALL (adapted)
│   │   ├── __init__.py
│   │   ├── decision_making.py      # FROM CORALL baseline
│   │   └── decision_llm_local.py   # YOUR NEW: Ollama integration
│   │
│   ├── fleet/                      # YOUR NEW: Multi-domain coordination
│   │   ├── __init__.py
│   │   ├── fleet_manager.py        # Asset registry, state, dispatch
│   │   ├── fleet_commander.py      # NL → multi-domain commands
│   │   ├── formations.py           # Surface formations
│   │   ├── task_allocator.py       # Cross-domain assignment
│   │   └── drone_coordinator.py    # Drone orbit/sweep/track patterns
│   │
│   ├── llm/                        # YOUR NEW: Local LLM interface
│   │   ├── __init__.py
│   │   ├── ollama_client.py        # Ollama HTTP client
│   │   ├── prompts.py              # System + user prompt templates
│   │   └── parser.py               # LLM output → FleetCommand
│   │
│   ├── voice/                      # YOUR NEW: Speech input
│   │   ├── __init__.py
│   │   └── whisper_local.py        # mlx-whisper integration
│   │
│   ├── api/                        # YOUR NEW: Backend API
│   │   ├── __init__.py
│   │   ├── server.py               # FastAPI app
│   │   ├── routes.py               # REST endpoints
│   │   └── ws.py                   # WebSocket handler
│   │
│   ├── logging/                    # YOUR NEW: Mission logging
│   │   ├── __init__.py
│   │   ├── mission_logger.py       # SQLite logging
│   │   └── replay.py               # Replay from logs
│   │
│   └── utils/
│       ├── __init__.py
│       ├── imazu_cases.py          # FROM CORALL (unchanged)
│       ├── config.py               # Global config
│       └── gps_denied.py           # YOUR NEW: GPS degradation
│
├── dashboard/                      # YOUR NEW: React frontend
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── components/
│   │   │   ├── FleetMap.jsx        # Leaflet map — vessels + drone
│   │   │   ├── CommandPanel.jsx    # Text/voice input
│   │   │   ├── AssetCard.jsx       # Domain-aware status cards
│   │   │   ├── MissionLog.jsx      # Live event log
│   │   │   ├── RiskIndicator.jsx   # CPA/TCPA gauges
│   │   │   └── GpsDeniedToggle.jsx # GPS mode switch
│   │   ├── hooks/
│   │   │   └── useWebSocket.js
│   │   └── styles/
│   │       └── global.css
│   └── public/
│       ├── vessel-icon.svg
│       └── drone-icon.svg
│
├── data/
│   ├── logs/                       # SQLite files (gitignored)
│   └── scenarios/
│       ├── harbor_patrol.json
│       ├── escort_formation.json
│       ├── search_pattern.json
│       └── air_sea_recon.json
│
├── scripts/
│   ├── run_demo.sh
│   ├── record_demo.sh
│   └── setup_env.sh
│
├── tests/
│   ├── test_schemas.py
│   ├── test_ollama_client.py
│   ├── test_fleet_manager.py
│   ├── test_drone_dynamics.py
│   ├── test_parser.py
│   ├── test_gps_denied.py
│   └── test_simulation.py
│
└── docs/
    ├── ARCHITECTURE.md
    ├── CORALL_CHANGES.md
    └── DEMO_SCRIPT.md
```

---

# EXACT BUILD ORDER — Non-Negotiable Dependency Chain

Build ONLY in this order. Each step depends on steps above it. If a step breaks, STOP and fix it before continuing.

## STEP 0: src/schemas.py
- **Write by hand** (copy from the Data Contracts section above)
- No dependencies. No AI needed. Just type definitions.
- Test: `python -c "from src.schemas import FleetCommand, AssetState, DomainType; print('Schemas OK')"`

## STEP 1: CORALL modules
- Copy from corall-upstream/ into your src/ structure
- Don't modify any CORALL code
- Test: Run CORALL baseline `cd corall-upstream && python main.py --case_number 1 --no_animation --llm 0`

## STEP 2: src/dynamics/drone_dynamics.py
- Depends on: schemas.py ONLY
- Simple DroneAgent class: x, y, altitude, heading, speed, step(dt), set_waypoints(), get_state()
- ~50-80 lines. If longer, you're over-engineering.
- Test: `python -c "from src.dynamics.drone_dynamics import DroneAgent; print('Drone OK')"`

## STEP 3: src/utils/gps_denied.py
- Depends on: schemas.py ONLY
- Two functions: degrade_position() and should_update()
- ~30 lines. Uses random.gauss().
- Test: `python -c "from src.utils.gps_denied import degrade_position; print('GPS OK')"`

## STEP 4: src/llm/ollama_client.py
- Depends on: schemas.py + Ollama running
- Function: parse_fleet_command(text) → FleetCommand
- Uses: `from ollama import chat` + `FleetCommand.model_json_schema()` as format param
- Test: parse "patrol the harbor with Alpha, Eagle recon from altitude" → valid FleetCommand with mixed domains

## STEP 5: src/fleet/fleet_manager.py
- Depends on: schemas.py + CORALL dynamics + drone_dynamics + gps_denied
- Creates 3 surface vessels + 1 drone
- Routes commands by domain (SURFACE → CORALL, AIR → DroneAgent)
- get_fleet_state() returns FleetState with ALL assets
- Test: `python -c "from src.fleet.fleet_manager import FleetManager; print('Fleet OK')"`

## STEP 6: src/fleet/fleet_commander.py
- Depends on: schemas.py + ollama_client
- Bridges natural language → fleet_manager
- Test: NL text → FleetCommand → fleet_manager dispatches to correct domains

## STEP 7: src/fleet/drone_coordinator.py
- Depends on: schemas.py + drone_dynamics
- Orbit, sweep, track patterns
- Test: Give drone orbit pattern, verify it circles

## STEP 8: src/fleet/formations.py + task_allocator.py
- Depends on: schemas.py
- Surface-only formations
- Test: 3 vessels in echelon maintain spacing

## STEP 9: src/api/server.py + ws.py + routes.py
- Depends on: schemas.py + fleet_manager
- FastAPI with WebSocket streaming FleetState at 4Hz
- Endpoints: POST /command, GET /assets, POST /gps-mode
- Test: `curl -X POST localhost:8000/api/command -d '{"text":"patrol harbor"}' -H "Content-Type: application/json"`

## STEP 10: dashboard/
- Depends on: WebSocket sending FleetState JSON
- React + Leaflet + Tailwind
- Different icons for surface vs air
- GPS-denied toggle with visual uncertainty indicators
- Dark C2 theme: background #0b0f19
- Dark map: `filter: brightness(0.6) invert(1) contrast(3) hue-rotate(200deg) saturate(0.3) brightness(0.7)`

## STEP 11: src/voice/whisper_local.py
- Depends on: fleet_commander
- mlx-whisper speech-to-text → feed into command pipeline
- Test: speak → text → FleetCommand → assets move

## STEP 12: src/logging/mission_logger.py + replay.py
- Depends on: schemas.py
- SQLite logging of all events
- Replay from logs

---

# DAY 1 SETUP — Exact Terminal Commands

Open Terminal on your Mac. Type each command. Wait for each to finish before the next.

```bash
# 1. Install Xcode command line tools
xcode-select --install
# Click Install on popup. Wait 5-10 min.

# 2. Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# Enter Mac password when prompted (chars won't show). Follow instructions at end.

# 3. Install tools
brew install python@3.11
brew install node
brew install ollama

# 4. Start Ollama and download model
ollama serve
# Open NEW terminal tab (Cmd+T):
ollama pull qwen2.5:72b
# This is ~40GB. Wait 10-20 min.

# 5. Create project
mkdir -p ~/Projects/localfleet
cd ~/Projects/localfleet

# 6. Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
# You should see (.venv) in your prompt now

# 7. Install Python libraries
pip install numpy scipy matplotlib
pip install fastapi uvicorn websockets
pip install pydantic httpx aiosqlite
pip install ollama instructor
pip install mlx-whisper
pip install openai anthropic  # Needed for CORALL transition

# 8. Install frontend tools
npm install -g pnpm

# 9. Clone CORALL
git clone https://github.com/Klins101/CORALL.git corall-upstream
cd corall-upstream
python main.py --case_number 1 --no_animation --llm 0
# Should run without errors
cd ..

# 10. Create ALL directories
mkdir -p src/core src/dynamics src/navigation src/risk_assessment
mkdir -p src/decision_making src/fleet src/llm src/voice src/api
mkdir -p src/logging src/utils
mkdir -p dashboard/src/components dashboard/src/hooks dashboard/src/styles
mkdir -p dashboard/public
mkdir -p data/logs data/scenarios tests docs scripts

# 11. Create __init__.py files
touch src/__init__.py src/core/__init__.py src/dynamics/__init__.py
touch src/navigation/__init__.py src/risk_assessment/__init__.py
touch src/decision_making/__init__.py src/fleet/__init__.py
touch src/llm/__init__.py src/voice/__init__.py src/api/__init__.py
touch src/logging/__init__.py src/utils/__init__.py

# 12. Create .gitignore
cat > .gitignore << 'EOF'
.venv/
__pycache__/
*.pyc
.DS_Store
node_modules/
dist/
*.egg-info/
.env
corall-upstream/
data/logs/*.db
dashboard/build/
dashboard/dist/
EOF

# 13. NOW create src/schemas.py — paste the ENTIRE schemas from this document

# 14. Initialize git
git init
git branch -m main
git add -A
git commit -m "init: multi-domain project structure with schemas"

# 15. Install Claude Code
npm install -g @anthropic-ai/claude-code

# 16. Verify EVERYTHING works
python --version                    # 3.11+
ollama list                         # shows qwen2.5:72b
node --version                      # 18+ or 20+
git status                          # clean
python -c "import numpy; print('numpy OK')"
python -c "import fastapi; print('FastAPI OK')"
python -c "import pydantic; print('Pydantic OK')"
python -c "import ollama; print('Ollama pkg OK')"
python -c "from src.schemas import FleetCommand, AssetState, DomainType; print('Schemas OK')"
curl http://localhost:11434/api/tags  # Ollama responds
```

**If ANY of step 16 fails, STOP. Fix it before writing code.**

---

# DAILY WORKFLOW

Every day you work on this project:

```bash
# 1. Open Terminal
cd ~/Projects/localfleet
source .venv/bin/activate

# 2. Make sure Ollama is running
ollama serve  # skip if already running

# 3. Open new tab (Cmd+T) for work

# 4. Start Claude Code for today's module
claude

# 5. Paste session context (schemas + what you're working on today)

# 6. Build ONE module. Test it. Verify imports.

# 7. When done:
git add -A
git commit -m "feat: description of what you built"
git push
```

---

# CLAUDE CODE SESSION TEMPLATE — Paste At Start Of Every Session

```
I'm building LocalFleet — a local-first, multi-domain LLM command & control
system. It runs on a Mac Studio M3 Ultra with 256GB RAM, air-gapped, using
Ollama for local LLM inference.

KEY: This is MULTI-DOMAIN. It commands surface vessels (CORALL dynamics) AND
a simulated drone (simple 2D+altitude model) through one natural language interface.
It has a GPS-denied degradation mode.

Forked from CORALL (github.com/Klins101/CORALL) for vessel dynamics/COLREGS/risk.
Adding: local LLM, multi-domain fleet coordination, React dashboard, voice, GPS-denied.

ALL data types are in src/schemas.py. Every module imports from schemas.py ONLY.

Critical types:
- DomainType: SURFACE or AIR
- AssetCommand: command for one asset, includes domain, waypoints, altitude (air), drone_pattern (air)
- FleetCommand: THE central object. LLM produces this. List[AssetCommand] with mixed domains.
- AssetState: current state, includes domain, altitude (air), gps_mode, position_accuracy
- FleetState: all assets + timestamp + gps_mode. Sent via WebSocket at 4Hz.

Available assets: alpha (surface), bravo (surface), charlie (surface), eagle-1 (air)

[PASTE FULL src/schemas.py HERE]

Today I'm working on: [SPECIFIC FILE]
[DESCRIBE EXACTLY WHAT THIS MODULE SHOULD DO, WHAT INPUTS IT TAKES, WHAT OUTPUTS IT PRODUCES]
```

---

# VERIFICATION COMMANDS — Run After Each Module

```bash
# Import check
python -c "from src.MODULE.FILE import CLASS_OR_FUNCTION; print('OK')"

# Multi-domain schema check
python -c "
from src.schemas import *
cmd = FleetCommand(
    mission_type=MissionType.PATROL,
    assets=[
        AssetCommand(asset_id='alpha', domain=DomainType.SURFACE,
                     waypoints=[Waypoint(x=100, y=200)], speed=5.0),
        AssetCommand(asset_id='eagle-1', domain=DomainType.AIR,
                     waypoints=[Waypoint(x=300, y=400)], speed=15.0,
                     altitude=100.0, drone_pattern=DronePattern.SWEEP)
    ],
    formation=FormationType.ECHELON
)
print(cmd.model_dump_json(indent=2))
print('Multi-domain FleetCommand OK')
"

# Round-trip check
python -c "
from src.schemas import *
state = FleetState(timestamp=1.0, gps_mode=GpsMode.FULL, assets=[
    AssetState(asset_id='alpha', domain=DomainType.SURFACE,
               x=100, y=200, heading=45, speed=5, status=AssetStatus.IDLE),
    AssetState(asset_id='eagle-1', domain=DomainType.AIR,
               x=300, y=400, heading=90, speed=15, altitude=100,
               status=AssetStatus.EXECUTING, drone_pattern=DronePattern.ORBIT)
])
json_str = state.model_dump_json()
recovered = FleetState.model_validate_json(json_str)
assert recovered == state
print('Round-trip OK')
"

# Run all tests
python -m pytest tests/ -v
```

---

# WHEN STUCK

- **Under 30 min:** Read error carefully. Google exact error message. Ask Claude Code — paste error + file.
- **30 min to 2 hours:** Step away. Come back fresh. Start NEW Claude Code session with schemas pasted.
- **Over 2 hours on ONE thing:** SKIP IT. Move to next module. Mark with TODO. Come back later.
- **4-hour rule:** If stuck 4 hours, it's not worth it right now. Forward motion always.

---

# KEY OPEN-SOURCE REFERENCES

| Component | Source | What You Take |
|-----------|--------|--------------|
| Vessel physics | github.com/Klins101/CORALL | dynamics/, risk_assessment/, navigation/, decision_making/ |
| LLM structured output | github.com/ollama/ollama | ollama Python package + format parameter |
| Dashboard reference | github.com/josna-14/Maritime_Vessel_Tracking | Study MapComponent.jsx, ShipCard.jsx patterns |
| Dark map CSS | CSS filter trick | `filter: brightness(0.6) invert(1) contrast(3) hue-rotate(200deg) saturate(0.3) brightness(0.7)` |
| WebSocket pattern | github.com/ustropo/websocket-example | FastAPI WS → React useEffect pattern |
| Backup physics | github.com/MoMagDii/uuv_python_simulator | Only if CORALL has issues |

---

# THE DEMO THAT WINS

The 3-minute video that makes Paul Lwin (HavocAI CEO, ex-Navy pilot, JHU CS, Yale MBA) stop scrolling:

1. **Open:** Dark C2 dashboard. Map centered on a harbor. Four asset cards on the side — three ships, one drone. All idle.
2. **Voice command:** "Establish maritime surveillance pattern in the harbor with Alpha and Bravo in echelon. Deploy Eagle for aerial reconnaissance along the northern shore."
3. **Watch:** Two vessels begin coordinated patrol in echelon formation. Drone icon lifts off and begins sweep pattern at altitude. Event log scrolls.
4. **Second command:** "Contact detected bearing zero-four-five. Alpha intercept. Eagle, track the contact from altitude."
5. **Watch:** Alpha breaks formation, heads to intercept. Eagle shifts from sweep to track pattern, following the contact.
6. **Toggle GPS-Denied:** Click the toggle. Position indicators get fuzzy — pulsing uncertainty circles appear around each asset. Update rate visibly slows. Assets keep operating.
7. **Voice:** "Comms degraded. All assets switch to autonomous patrol."
8. **Watch:** Assets smoothly transition to independent patrol patterns despite degraded positioning.
9. **Close:** Cut to black. Text overlay: "LocalFleet — Multi-Domain Collaborative Autonomy. 100% Local. Zero Internet. Built on M3 Ultra."

**That demo mirrors HavocAI's Portugal demonstration, addresses their multi-domain pivot, and runs on consumer hardware. It's impossible to ignore.**

---

# END OF MASTER PROMPT
# You now have everything needed to build this project from zero.
# Start with Day 1 Setup. Build bottom-up. Test every step. Ship by July 5.
