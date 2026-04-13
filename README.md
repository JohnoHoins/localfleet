# LocalFleet — Edge-Native Autonomous Fleet C2

> Multi-domain autonomous fleet simulation with local LLM command & control.
> Voice and text commands are parsed by a 72B parameter language model running locally.
> Everything runs air-gapped on Apple Silicon. No cloud. No API calls.

## What This Demonstrates

- **Natural Language C2**: Voice and text commands parsed by a 72B parameter LLM
  running locally via Ollama. Natural language in, structured `FleetCommand` JSON out.
  No regex hacks or keyword matching — the model understands intent. Parse time is
  15–21s warm, because the model is doing real work.
- **Multi-Domain Coordination**: 3 surface vessels + 1 aerial drone operating
  together. Formation holding, mission-specific behaviors, cross-domain sensor fusion.
- **Kill Chain Automation**: Autonomous detect, track, lock, engage pipeline.
  Drone provides targeting data, fleet converges on predicted intercept point using
  iterative proportional navigation.
- **Degraded Operations**: Comms-denied autonomy with configurable standing orders
  (hold position, continue mission, return to base) and 60-second escalation to
  autonomous engagement. GPS-denied dead reckoning with smooth 5-second position
  blending on restore.
- **Explainable Autonomy**: Every autonomous decision logged with rationale,
  confidence score, and full audit trail. Decision transparency is a first-class
  feature, not an afterthought.

## Architecture

```
User (voice/text) --> FleetCommander --> Ollama (72B) --> FleetCommand (JSON)
                                                              |
                                                         FleetManager
                                                        /            \
                                            CORALL dynamics      DroneAgent
                                            (surface vessels)      (drone)
                                                        \            /
                                                    FleetState --> WebSocket --> React Dashboard
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, WebSocket (4Hz state streaming) |
| Frontend | React 18, Vite, Leaflet.js, Tailwind CSS |
| Physics | CORALL-based Nomoto model (surface), waypoint follower (drone) |
| LLM | Ollama + Qwen 2.5 72B (local inference, ~15–21s parse) |
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

Or double-click `start_localfleet.command` to launch everything (Ollama + backend + dashboard + browser).

## Key Features

### LLM Command Parsing

All commands are parsed by a 72B parameter language model running entirely on-device.
Natural language like *"send alpha and bravo to patrol around 2000 1000 in echelon
at 5 meters per second"* is converted to structured `FleetCommand` JSON with mission
type, asset assignments, waypoints, formation, speed, and standing orders.

The LLM handles ambiguity, voice transcription artifacts, military phrasing, and
conversational commands that rigid parsers can't. Response time is 15–21s warm —
honest latency that shows the model is doing real inference, not pattern matching.

### Autonomous Threat Response

The threat detector continuously evaluates contacts by range and closing rate:
- **8km**: detected (logged)
- **5km**: warning (drone auto-retasks to TRACK)
- **2km**: critical (intercept recommended to operator)

The kill chain progresses through DETECT, TRACK, LOCK, ENGAGE phases. Under
comms denial, after a configurable 60-second escalation delay, the fleet
autonomously engages the highest-priority threat — logged with full rationale.

### Degraded Mode Operations

**Comms-denied**: Three standing order modes (hold position, continue mission,
return to base). Each fires exactly once on comms loss — no action spam. One-shot
guard resets when comms are restored.

**GPS-denied**: Dead reckoning with 0.5% drift per step. Physics and land avoidance
always use true position (vessels don't run aground from DR error). GPS restore
blends smoothly over 5 seconds — no position snap.

### System Monitor

A second dashboard window (`/monitor.html`) shows live system internals:
command parser state and LLM response times, threat engine status, kill chain
phase, simulation performance, and a scrolling decision audit log. Dark terminal
aesthetic designed for a second monitor during demos.

## Hardware Requirements

- Apple Silicon Mac (M1 Ultra / M2 Ultra / M3 Ultra recommended)
- 64GB+ unified memory (128GB+ for 72B model at full speed)
- Ollama installed with `qwen2.5:72b` model pulled

## Tests

```bash
.venv/bin/python -m pytest tests/ -v  # 249 tests
```

## License

MIT
