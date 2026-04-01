# LOCALFLEET — Session Kickoff Prompts
## Copy the terminal command, then paste the prompt into the Claude session

---

## PHASE 1, SESSION 1: UNCLASSIFIED Banner + Header Bar + Map Origin + Dark Tiles
**Tasks: P1.1, P1.2, P1.3, P1.4**

### Terminal Command:
```bash
cd ~/Projects/localfleet && source .venv/bin/activate && claude
```

### Prompt:
```
I'm building LocalFleet — a multi-domain C2 system for autonomous fleet simulation. We're in the POLISH phase now. The core system is fully built and working (102 tests passing). I need you to make the dashboard look like a real military C2 system.

BEFORE YOU WRITE ANY CODE, read these files to understand the project state and rules:
1. docs/LOCALFLEET_POLISH_PLAN.md — the full polish plan with exact specs for every task
2. docs/LOCALFLEET_MASTER_PROMPT.md — original build context and absolute rules
3. src/schemas.py — THE source of truth. NEVER modify this file.
4. dashboard/src/App.jsx — current layout
5. dashboard/src/components/FleetMap.jsx — current map component
6. dashboard/src/styles/global.css — current styles

ABSOLUTE RULES:
- NEVER modify src/schemas.py
- All 102 existing tests must stay green after changes
- Don't refactor working code — only add to it or create new files
- Don't break the WebSocket contract (FleetState JSON shape)

YOUR TASKS THIS SESSION (do them in order):

1. **P1.1 — UNCLASSIFIED Banner:** Add a thin green classification banner at the very bottom of the screen in App.jsx. Text: "UNCLASSIFIED // FOUO". Dark green background, green text, centered, 10px font, wide letter-spacing. See the polish plan for exact styling.

2. **P1.2 — Header Bar Upgrade:** Create a new `dashboard/src/components/HeaderBar.jsx` component. Replace the inline header in App.jsx. It needs:
   - Left: LOCALFLEET title + C2 DASHBOARD subtitle (keep existing style)
   - Center: Zulu clock (UTC, updates every second, format "14:32:07Z") + Mission elapsed timer (starts when first command sent, format "T+00:03:42")
   - Right: GPS mode indicator (green "GPS: FULL" or flashing amber "GPS: DENIED"), connection dot, asset count
   - The mission timer needs state in App.jsx — add a missionStartTime state that gets set when a command succeeds. Pass it as a prop.

3. **P1.3 — Map Origin Newport RI:** In FleetMap.jsx, change ORIGIN_LAT to 41.4925 and ORIGIN_LNG to -71.3270 (Newport Harbor, near Naval War College). Keep M_PER_DEG_LNG as-is (82000 is close enough for 41.5°N).

4. **P1.4 — CartoDB Dark Tiles:** In FleetMap.jsx, change the TileLayer URL to "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png". Remove the className="dark-map-tiles" from the TileLayer. In global.css, remove the .dark-map-tiles filter rule.

After making all changes, run the existing test suite to verify nothing is broken:
.venv/bin/python -m pytest --tb=short -q

Then tell me to start the dev servers so I can visually verify.
```

---

## PHASE 1, SESSION 2: RTB Button + Mission Log Echo + Mission Status + Processing Animation
**Tasks: P1.5, P1.6, P1.7, P1.8**

### Terminal Command:
```bash
cd ~/Projects/localfleet && source .venv/bin/activate && claude
```

### Prompt:
```
I'm building LocalFleet — a multi-domain C2 system. We're in the POLISH phase. The core system works (102 tests passing). Last session I upgraded the header, map tiles, map origin, and added an UNCLASSIFIED banner.

BEFORE YOU WRITE ANY CODE, read these files:
1. docs/LOCALFLEET_POLISH_PLAN.md — full polish plan with exact specs (read tasks P1.5, P1.6, P1.7, P1.8)
2. src/schemas.py — NEVER modify
3. dashboard/src/App.jsx — current layout (was modified last session)
4. dashboard/src/components/CommandPanel.jsx — command input panel
5. dashboard/src/components/MissionLog.jsx — live event log
6. src/api/routes.py — existing REST endpoints (has POST /return-to-base)

ABSOLUTE RULES:
- NEVER modify src/schemas.py
- All existing tests must stay green
- Don't break the WebSocket contract

YOUR TASKS THIS SESSION (do them in order):

1. **P1.5 — RTB Button:** Create `dashboard/src/components/RTBButton.jsx`. Red emergency-style button that calls POST /api/return-to-base. Mount in App.jsx sidebar between GpsDeniedToggle and MissionLog. See polish plan for exact styling.

2. **P1.6 — Mission Log Echo Command Text:** When a command is sent successfully, the natural language text should appear in MissionLog as: > "the command text here". Implementation: add lastCommandText state to App.jsx, pass a setter callback to CommandPanel (called on success), pass the value to MissionLog (displayed when it changes).

3. **P1.7 — Mission/Formation Status Badge:** Create `dashboard/src/components/MissionStatus.jsx`. Shows current mission type and formation as colored badges. Data comes from fleetState.active_mission and fleetState.formation. Mount in sidebar above asset cards. Show "STANDBY" in gray when no mission active.

4. **P1.8 — Processing Animation:** In CommandPanel.jsx, replace the "..." on the SEND button with a processing state that shows "PROCESSING..." with elapsed time counting up (update every 100ms). Disable input during processing.

After all changes, run: .venv/bin/python -m pytest --tb=short -q
Then tell me to verify visually.
```

---

## PHASE 2, SESSION 3: GPS-Denied Visual Overhaul
**Tasks: P2.1**

### Terminal Command:
```bash
cd ~/Projects/localfleet && source .venv/bin/activate && claude
```

### Prompt:
```
I'm building LocalFleet — a multi-domain C2 system. We're in POLISH phase. Phase 1 (dashboard UI) is complete. Now I need the GPS-denied toggle to be visually dramatic.

BEFORE YOU WRITE ANY CODE, read these files:
1. docs/LOCALFLEET_POLISH_PLAN.md — read task P2.1 carefully (all 4 parts)
2. src/schemas.py — NEVER modify
3. src/fleet/fleet_manager.py — GPS mode handling in get_fleet_state() and set_gps_mode()
4. src/utils/gps_denied.py — degrade_position() and should_update() functions
5. dashboard/src/components/FleetMap.jsx — GPS uncertainty circles
6. dashboard/src/components/GpsDeniedToggle.jsx — toggle component
7. dashboard/src/App.jsx — for adding vignette overlay
8. dashboard/src/styles/global.css — pulse animation
9. tests/test_gps_denied.py — existing GPS tests

ABSOLUTE RULES:
- NEVER modify src/schemas.py
- All existing tests must stay green
- Don't break the WebSocket contract

YOUR TASKS THIS SESSION (4 parts of P2.1):

**Part A — Increase noise + ring size:**
- In GpsDeniedToggle.jsx, change noise_meters from 25.0 to 50.0 in the POST body
- In FleetMap.jsx, change the Circle radius from position_accuracy to position_accuracy * 3

**Part B — Amber screen vignette:**
- In App.jsx, when fleetState.gps_mode === 'degraded', render an overlay div covering the entire screen with pointer-events:none, a CSS box-shadow inset creating an amber vignette at the edges: box-shadow: inset 0 0 150px rgba(245, 158, 11, 0.08)

**Part C — Activate rate limiter (BACKEND):**
This is the most important part. In fleet_manager.py:
- Add self._last_noisy_positions = {} in __init__
- In get_fleet_state(), when GPS is DEGRADED: for each asset, call should_update(asset_id, 1.0). If True, compute new noisy position via degrade_position() and store in _last_noisy_positions. If False, use the cached noisy position from _last_noisy_positions. This creates visible 1Hz position stutter.
- Import should_update from src.utils.gps_denied

**Part D — Verify pulse animation:**
- Check if the CSS class gps-uncertainty-ring actually animates on Leaflet Circle elements. If it doesn't work (Leaflet renders Circles as SVG paths and the CSS animation may not apply), implement an alternative: use React state to toggle circle opacity between 0.15 and 0.05 on a 2-second interval.

After all changes, run: .venv/bin/python -m pytest --tb=short -q
Verify test_gps_denied.py still passes. If you modified fleet_manager.py, also verify test_fleet_manager.py passes.
Then tell me to test visually.
```

---

## PHASE 3, SESSION 4: Maintained Formations + Vessel Wakes
**Tasks: P3.1, P3.2**

### Terminal Command:
```bash
cd ~/Projects/localfleet && source .venv/bin/activate && claude
```

### Prompt:
```
I'm building LocalFleet — a multi-domain C2 system. We're in POLISH phase. Phases 1-2 complete (dashboard UI + GPS-denied). Now I need formations to look like real coordinated movement.

BEFORE YOU WRITE ANY CODE, read these files:
1. docs/LOCALFLEET_POLISH_PLAN.md — read tasks P3.1 and P3.2 carefully
2. src/schemas.py — NEVER modify
3. src/fleet/fleet_manager.py — dispatch_command() and step() methods
4. src/fleet/formations.py — apply_formation() and compute_formation_offsets()
5. tests/test_formations.py — 14 existing formation tests
6. tests/test_wiring.py — 8 existing wiring tests
7. tests/test_fleet_manager.py — 5 existing fleet manager tests
8. dashboard/src/components/FleetMap.jsx — for vessel wakes

ABSOLUTE RULES:
- NEVER modify src/schemas.py
- All 102 existing tests must stay green
- Don't break formation geometry (test_formations.py tests the math)

YOUR TASKS THIS SESSION:

**P3.1 — Maintained Formations During Movement:**
Currently formations are computed once at dispatch as waypoint adjustments. Vessels navigate independently to offset positions. I need followers to maintain formation relative to the leader DURING movement.

Implementation in fleet_manager.py:
- Add formation state tracking in __init__: _formation_leader, _formation_members, _formation_type, _formation_spacing
- In dispatch_command(): when formation is not INDEPENDENT and >= 2 surface vessels, store the leader ID, member IDs, formation type, and spacing
- In step(): when formation is active and leader is EXECUTING, each tick:
  - Get leader's current position and heading
  - Compute follower target positions using apply_formation() with leader's CURRENT state
  - Update each follower's waypoints to navigate toward their formation position
  - Convert formation positions to nautical miles for CORALL (same as dispatch_command does)
- When leader goes IDLE, followers navigate to their final formation positions and go IDLE
- When RTB or new command is dispatched, clear formation tracking

BE CAREFUL: This is the trickiest task. Followers chasing a moving leader can oscillate. Use the formation position as the SINGLE waypoint (replace their waypoint list entirely each tick). Set follower desired_speed slightly higher than leader speed so they can catch up.

FALLBACK: If this causes test failures or oscillation that you can't fix cleanly, revert the step() changes and instead just increase the default formation spacing from 200m to 350m in fleet_manager.py dispatch_command(). This makes the static waypoint-adjusted formations more visually distinct.

**P3.2 — Vessel Heading Wakes:**
In FleetMap.jsx, for each surface asset with speed > 0.5, render a short Polyline (50m) extending opposite the heading direction. Color: #3b82f6, weight: 3, opacity: 0.4. See polish plan for the math.

After all changes, run: .venv/bin/python -m pytest --tb=short -q
EVERY existing test must pass. If any test breaks, fix it or revert the breaking change.
```

---

## PHASE 4, SESSION 5: Simulated Contact
**Tasks: P4.1**

### Terminal Command:
```bash
cd ~/Projects/localfleet && source .venv/bin/activate && claude
```

### Prompt:
```
I'm building LocalFleet — a multi-domain C2 system. We're in POLISH phase. Phases 1-3 complete. Now I need a simulated hostile contact that moves on the map so the demo can show intercept/track scenarios.

BEFORE YOU WRITE ANY CODE, read these files:
1. docs/LOCALFLEET_POLISH_PLAN.md — read task P4.1 carefully
2. src/schemas.py — NEVER modify. The contact will NOT use AssetState or FleetState schemas. It's an extension.
3. src/fleet/fleet_manager.py — where contacts will be managed
4. src/dynamics/drone_dynamics.py — similar waypoint-following logic to reuse
5. src/api/ws.py — WebSocket handler that sends state JSON
6. src/api/routes.py — where new endpoint goes
7. dashboard/src/components/FleetMap.jsx — where contact marker will render

ABSOLUTE RULES:
- NEVER modify src/schemas.py
- All existing tests must stay green
- Don't add contacts to FleetState schema — extend the WebSocket JSON dict AFTER model_dump()

YOUR TASKS THIS SESSION:

1. Create `src/simulation/__init__.py` (empty)

2. Create `src/simulation/contact.py`:
   - Contact class with: contact_id (str), x, y, heading, speed (default 3.0 m/s), waypoints (List of dicts with x,y), current_wp_index, active (bool)
   - set_waypoints(waypoints): set waypoints and activate
   - step(dt): move toward current waypoint (same math as DroneAgent._step_waypoint), advance index when within 5m, deactivate when waypoints exhausted
   - get_state() -> dict: returns {"contact_id": ..., "x": ..., "y": ..., "heading": ..., "speed": ..., "active": ...}

3. Modify `src/fleet/fleet_manager.py`:
   - Import Contact
   - Add self.contacts: Dict[str, Contact] = {} in __init__
   - Add spawn_contact(contact_id, waypoints, speed=3.0) method: creates Contact, adds to dict
   - Add remove_contact(contact_id) method
   - In step(): step all active contacts
   - Add get_contacts_state() -> list: returns [contact.get_state() for each active contact]

4. Modify `src/api/ws.py`:
   - After state.model_dump(), add contacts to the dict: state_dict["contacts"] = commander.fleet_manager.get_contacts_state()
   - Send state_dict instead of state.model_dump()

5. Modify `src/api/routes.py`:
   - Add POST /api/spawn-contact endpoint: accepts JSON {"contact_id": "contact-1", "waypoints": [{"x": ..., "y": ...}, ...], "speed": 3.0}
   - Add POST /api/remove-contact endpoint: accepts {"contact_id": "contact-1"}

6. Modify `dashboard/src/components/FleetMap.jsx`:
   - Accept contacts from the WebSocket data (parent passes it down)
   - Render each active contact as a red diamond marker with label
   - Create a red icon variant in createIcon() or a separate createContactIcon()

7. Modify `dashboard/src/App.jsx`:
   - Extract contacts from fleetState WebSocket data and pass to FleetMap

8. Create `tests/test_contact.py`:
   - Test Contact movement along waypoints
   - Test spawn and step via FleetManager
   - Test deactivation when waypoints exhausted

After all changes: .venv/bin/python -m pytest --tb=short -q (all tests including new ones must pass)
```

---

## PHASE 4, SESSION 6: Continuous Track Pattern
**Tasks: P4.2**

### Terminal Command:
```bash
cd ~/Projects/localfleet && source .venv/bin/activate && claude
```

### Prompt:
```
I'm building LocalFleet — a multi-domain C2 system. We're in POLISH phase. Last session I added simulated contacts. Now I need the drone's track pattern to continuously follow a moving target instead of flying to a static point.

BEFORE YOU WRITE ANY CODE, read these files:
1. docs/LOCALFLEET_POLISH_PLAN.md — read task P4.2
2. src/schemas.py — NEVER modify
3. src/dynamics/drone_dynamics.py — DroneAgent class, _step_waypoint and orbit methods
4. src/fleet/drone_coordinator.py — assign_pattern() for TRACK
5. src/fleet/fleet_manager.py — step() loop and contact management
6. tests/test_drone_dynamics.py — 6 existing tests
7. tests/test_drone_coordinator.py — 14 existing tests

ABSOLUTE RULES:
- NEVER modify src/schemas.py
- All existing tests must stay green

YOUR TASKS THIS SESSION:

1. Modify `src/dynamics/drone_dynamics.py`:
   - Add fields: track_target_x: float | None = None, track_target_y: float | None = None, track_offset: float = 50.0
   - Add method update_track_target(x, y): sets track_target_x/y, recalculates waypoint[0] to be offset from target position (offset behind: x - offset, y - offset). If currently in TRACK pattern and IDLE (reached old target), set status back to EXECUTING.
   - In step(): when pattern is TRACK and track target exists, after moving toward waypoint, don't go IDLE when reaching it — stay EXECUTING and keep following.

2. Modify `src/fleet/drone_coordinator.py`:
   - In assign_pattern() for TRACK: store a track_target_id (the asset_id or contact_id being tracked) on the coordinator
   - Add method get_track_target_id() -> str | None

3. Modify `src/fleet/fleet_manager.py`:
   - In step(): after stepping the drone, if drone is in TRACK pattern and coordinator has a track_target_id:
     - Look up the target's current position (check contacts first, then vessels)
     - Call drone.update_track_target(target_x, target_y)

4. Add tests to test_drone_dynamics.py or new test file:
   - Test: set track pattern, update target 10 times with moving positions, verify drone follows
   - Test: existing track behavior (static target) still works

After all changes: .venv/bin/python -m pytest --tb=short -q
```

---

# NOTES FOR FUTURE SESSIONS

For Phases 5-8, follow the same pattern:
1. Terminal: `cd ~/Projects/localfleet && source .venv/bin/activate && claude`
2. Tell the AI to read `docs/LOCALFLEET_POLISH_PLAN.md` for the specific task specs
3. Tell it to read `src/schemas.py` and the specific files being modified
4. List the absolute rules
5. Give the specific tasks with implementation details from the polish plan
6. Always end with running the test suite

Each session should tackle 1-3 related tasks. Keep sessions focused. Test before moving on.
