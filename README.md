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
| Frontend | React 19, Vite 8, Leaflet.js, Tailwind CSS |
| Physics | CORALL-based Nomoto model (surface), waypoint follower (drone) |
| LLM | Ollama + Qwen 2.5 72B (local inference, ~15–21s parse) |
| Voice | mlx-whisper (Apple Silicon optimized) |
| Data | Pydantic schemas, SQLite mission logging |

## Quick Start

Prerequisites:

- macOS on Apple Silicon (see [Hardware Requirements](#hardware-requirements))
- Python 3.10+ (3.11+ recommended). The `python3` that ships with macOS is 3.9,
  which is too old; install a newer one, e.g. `brew install python@3.12`
- Node.js 20.19+ or 22.12+ (required by Vite 8) and pnpm 9+
- [Ollama](https://ollama.com) 0.5+ (needed for structured JSON output)
- ffmpeg, for voice input only: `brew install ffmpeg`

```bash
ollama pull qwen2.5:72b    # ~47 GB download

# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # mlx-whisper (voice) installs on Apple Silicon only
uvicorn src.api.server:app --host 127.0.0.1 --port 8000

# Dashboard (separate terminal)
cd dashboard && pnpm install && pnpm dev

# Open http://localhost:5173
```

After this one-time setup (`.venv` and `dashboard/node_modules` must exist), you
can instead double-click `start_localfleet.command` in the LocalFleet folder. It
starts Ollama if needed, checks that the model is pulled, stops a backend or
dashboard left over from a previous run, starts both, loads the model into
memory, and opens the dashboard and system monitor. Each step that fails is
reported with `[!!]` and the reason, and `LOCALFLEET READY` is printed only when
every step succeeded. Ctrl+C, or closing the window, stops the backend and
dashboard. Loading the 72B model from disk can take a few minutes on the
first start.

### Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `LOCALFLEET_MODEL` | `qwen2.5:72b` | Ollama model used to parse commands (the launcher preloads the same one) |
| `LOCALFLEET_LLM_TIMEOUT` | see `src/llm/ollama_client.py` | Seconds the backend waits for one command parse before reporting a timeout. Raise it on slower machines. |
| `LOCALFLEET_KEEP_ALIVE` | `60m` | How long Ollama keeps the model in memory after the launcher preloads it (a duration such as `2h`, or `-1` for forever) |

Ollama unloads a model that has been idle for its keep-alive period, and the
next command then waits for the model to load again.

### Voice Input

Voice commands are transcribed on-device by mlx-whisper (Apple Silicon only),
which uses the `ffmpeg` binary to read audio (`brew install ffmpeg`). The first
voice command downloads the Whisper model (`mlx-community/whisper-large-v3-turbo`,
about 1.6 GB) from Hugging Face; after that, transcription runs offline. In the
COMMAND panel, click **MIC**, speak, then click **STOP**; the transcript is parsed
like a typed command. Browsers only allow the microphone on `localhost` or
HTTPS. See [docs/STEP11_VOICE_TEST_GUIDE.md](docs/STEP11_VOICE_TEST_GUIDE.md) for
a walkthrough.

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

The kill chain progresses through DETECT, TRACK, LOCK, ENGAGE phases, then
CONVERGE as the fleet closes. Reaching the target is logged once and the fleet
shadows it; the chain never restarts on a target it already intercepted. Under
comms denial, after a configurable 60-second escalation delay
(`LOCALFLEET_ESCALATION_SECONDS`, sim-time), the fleet autonomously engages the
highest-priority threat — logged with full rationale.

### Degraded Mode Operations

**Comms-denied**: Three standing order modes (hold position, continue mission,
return to base). Each fires exactly once on comms loss — no action spam. One-shot
guard resets when comms are restored.

**GPS-denied**: Dead reckoning from measured speed and course, with 0.5% of
distance run added as drift each step. Physics and land avoidance always use
true position (vessels don't run aground from DR error). GPS restore blends the
DR error out over 5 seconds — no position snap on the map or in navigation.

### System Monitor

A second dashboard window (`/monitor.html`) shows live system internals:
command parser state and LLM response times, threat engine status, kill chain
phase, simulation performance, and a scrolling decision audit log. Dark terminal
aesthetic designed for a second monitor during demos.

## Hardware Requirements

- Apple Silicon Mac (M1 Ultra / M2 Ultra / M3 Ultra recommended)
- 64GB+ unified memory (128GB+ for 72B model at full speed)
- About 50 GB of free disk for the `qwen2.5:72b` model (47 GB)
- Ollama installed with `qwen2.5:72b` model pulled

## Tests

```bash
.venv/bin/python -m pytest tests/ -v  # 266 tests (2 need a running Ollama)
```

## Simulation Scripts

`scripts/` holds headless drivers that exercise a running backend through its
REST and WebSocket APIs. Their extra dependencies (`requests`,
`websocket-client`) are included in `requirements.txt`.

```bash
# With the backend running on :8000 (the LLM is not needed)
.venv/bin/python scripts/run_simulation_v2.py      # 21 isolated tests, ~45-60 min
.venv/bin/python scripts/analyze_simulation_v2.py  # per-test report + CSVs
```

Each v2 test starts from a fresh fleet (`POST /api/reset`). Both runners accept
`--base-url` (default `http://localhost:8000`). Raw captures are written to
`data/*.jsonl`, and the analyzers write their reports and CSVs to
`data/sim_runs/`, so the reference reports committed in `data/` are not
overwritten. `run_simulation.py` and `analyze_simulation.py` are the original
single-scenario versions.

## License

MIT
