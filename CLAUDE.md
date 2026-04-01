# LocalFleet — Claude Code Context

## What This Is
Multi-domain (surface + air) autonomous fleet simulation with local LLM command & control.
Natural language → Ollama LLM → structured commands → simulated vessels + drone on a map.
Everything runs air-gapped on Mac Studio M3 Ultra 256GB.

## Tech Stack
- **Backend**: Python 3.11 / FastAPI / WebSocket (4Hz state streaming)
- **Frontend**: React 18 / Vite / Leaflet.js / Tailwind CSS
- **Physics**: CORALL-based Nomoto model (surface), simple waypoint follower (drone)
- **LLM**: Ollama + Qwen 2.5 72B for NL→JSON command parsing
- **Voice**: mlx-whisper (Apple Silicon)
- **Data**: Pydantic schemas + SQLite mission logging

## Architecture
```
User (voice/text) → FleetCommander → Ollama → FleetCommand (JSON)
                                                    ↓
                                              FleetManager
                                             ↙           ↘
                                   CORALL dynamics    DroneAgent
                                   (surface vessels)    (drone)
                                             ↘           ↙
                                           FleetState → WebSocket → React Dashboard
```

## Key Files by Subsystem
| Subsystem | Files |
|-----------|-------|
| Schemas (source of truth) | `src/schemas.py` |
| Navigation | `src/navigation/planning.py`, `src/navigation/reactive_avoidance.py`, `src/navigation/land_check.py` |
| Dynamics | `src/dynamics/vessel_dynamics.py`, `src/dynamics/controller.py`, `src/dynamics/drone_dynamics.py` |
| Fleet | `src/fleet/fleet_manager.py`, `src/fleet/fleet_commander.py`, `src/fleet/formations.py` |
| Drone coordination | `src/fleet/drone_coordinator.py` |
| LLM | `src/llm/ollama_client.py` |
| Decision making | `src/decision_making/decision_making.py` |
| GPS-denied | `src/utils/gps_denied.py` |
| API server | `src/api/server.py` |
| Dashboard | `dashboard/src/components/FleetMap.jsx`, `dashboard/src/App.jsx` |
| Mission logging | `src/logging/mission_logger.py` |

## Assets (scope locked)
- 3 surface vessels: alpha, bravo, charlie
- 1 drone: eagle-1
- 5 mission types: patrol, search, escort, loiter, aerial_recon

## Absolute Rules
1. **SCHEMAS ARE GOD** — All types from `src/schemas.py`. Never modify schemas. Fix the module.
2. **ONE FILE per session** (two max). Small, specific, testable.
3. **TEST BEFORE MOVING ON** — Run tests in the same session.
4. **NEVER REFACTOR WORKING CODE** — If it works, don't "improve" it.
5. **BUILD BOTTOM-UP** — Follow dependency order.
6. **SCOPE IS LOCKED** — 4 assets, 5 mission types, no feature creep.

## Running
```bash
# Tests
.venv/bin/python -m pytest tests/ -v

# Single test file
.venv/bin/python -m pytest tests/test_fleet_manager.py -v

# API server
.venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000

# Dashboard (separate terminal)
cd dashboard && pnpm dev
```

## Units & Conventions
- **Vessel state**: `[x, y, psi, r, b, u]` — x,y in meters, psi in radians (math convention: 0=East, CCW+)
- **Waypoints in navigation**: Stored in nautical miles (÷1852) for CORALL compatibility
- **Display heading**: Converted to nautical (0=North) via `(90 - degrees(psi)) % 360`
- **Simulation tick**: dt=0.25s, WebSocket at 4Hz
- **Coordinate origin**: ORIGIN_LAT=42.0, ORIGIN_LNG=-70.0 (off Cape Cod). Defined in `dashboard/src/components/FleetMap.jsx` and `src/navigation/land_check.py`
- **Land avoidance**: `land_check.py` has simplified Cape Cod polygon (~500m accuracy). `land_repulsion_heading()` is called in `fleet_manager.py step()` after `planning()` and before the PID controller. Returns heading correction in radians. Extensible via `LAND_POLYGONS` list.

## Reference Files
Context dumps used during project creation are in `docs/reference/`:
- `all_source_code.txt`, `src_code.txt`, `dashboard_code.txt`, `tests_code.txt`
- `config_files.txt`, `file_list.txt`, `project_tree.txt`, `memory_dump.txt`
