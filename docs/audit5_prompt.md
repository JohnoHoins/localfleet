Execute Audit 5 — Dashboard Functional C2 Operations Center for the LocalFleet project.

Read CLAUDE.md first. Then read docs/localfleet_audit_plan.md — focus on AUDIT 5
(Dashboard — Functional C2 Operations Center).

COMPLETED AUDITS (all backend work is done — do NOT touch backend files unless
adding a small coastline API endpoint):
- Audit 1: Navigation circling fixed
- Audit 6: Heading wrapping, speed scaling, yaw noise, pure pursuit
- Audit 7: LLM command hardening, waypoint clamping, timeout, retry
- Audit 2: Cape Cod land avoidance polygon in land_check.py
- Audit 4: INTERCEPT mission type, Contact model, FleetState.contacts,
  spawn/remove/step contacts, REST endpoints at /api/contacts
- Audit 3: GPS-denied dead reckoning — DENIED mode, DeadReckoningState,
  navigation uses DR position, drift accumulates. GpsMode: FULL/DEGRADED/DENIED
- 147 backend tests passing. Do NOT break them.

YOUR TASK: Build a functional C2 dashboard. The operator should be able to run
the entire intercept demo from the browser — spawn targets, issue commands,
watch convergence, hit RTB, toggle GPS denied — without any CLI.

────────────────────────────────────────────────────────────────────
CURRENT DASHBOARD STATE
────────────────────────────────────────────────────────────────────

The dashboard is React 19 + Vite + Tailwind CSS + Leaflet. All components work.

Files:
- dashboard/src/App.jsx — 70/30 layout, useWebSocket hook, trail accumulation
- dashboard/src/components/FleetMap.jsx — Leaflet map, vessel/drone markers, trails
- dashboard/src/components/AssetCard.jsx — per-asset status cards
- dashboard/src/components/CommandPanel.jsx — NL text input + voice
- dashboard/src/components/VoiceButton.jsx — Web Audio recording
- dashboard/src/components/GpsDeniedToggle.jsx — FULL ↔ DEGRADED toggle only
- dashboard/src/components/MissionLog.jsx — event log
- dashboard/src/hooks/useWebSocket.js — WebSocket client
- dashboard/src/styles/global.css — dark theme, JetBrains Mono, Leaflet CSS

WebSocket data (FleetState at 4Hz):
  { timestamp, assets: [AssetState], active_mission, formation, gps_mode,
    contacts: [Contact] }  ← contacts EXIST but dashboard IGNORES them

Backend API endpoints already available:
  POST /api/command           — NL text → LLM → dispatch
  POST /api/voice-command     — audio → Whisper → LLM → dispatch
  POST /api/return-to-base    — recall all assets
  POST /api/gps-mode          — set mode {mode: "full"/"degraded"/"denied"}
  GET  /api/contacts          — list contacts
  POST /api/contacts          — spawn {contact_id, x, y, heading, speed, domain}
  DELETE /api/contacts/{id}   — remove contact
  GET  /api/assets            — FleetState via REST
  GET  /api/mission           — active mission + last command

────────────────────────────────────────────────────────────────────
WHAT TO BUILD — IN PRIORITY ORDER
────────────────────────────────────────────────────────────────────

READ ALL EXISTING DASHBOARD FILES BEFORE CODING. Understand the patterns,
styling conventions, and data flow. Match existing code style exactly.

A) CONTACT MARKERS ON MAP (modify FleetMap.jsx) — CRITICAL
   fleetState.contacts[] is streaming but invisible on the map.
   - Add a `contacts` prop to FleetMap (passed from App.jsx)
   - Red (#ef4444) triangle/diamond markers for each contact
   - Rotate marker by heading (contacts use radians math convention —
     convert to degrees same as vessels: (90 - degrees(heading)) % 360)
   - Popup: contact_id, speed, heading (nautical degrees)
   - Contact trails: red dashed polylines (same trail system as vessels)
   - In App.jsx: pass fleetState.contacts to FleetMap, accumulate
     contact trails alongside asset trails

B) RTB BUTTON (create RTBButton.jsx, wire into App.jsx)
   - Red-tinted button labeled "RTB" or "RETURN TO BASE"
   - On click: POST /api/return-to-base
   - Brief loading/confirm state
   - Place in sidebar — this is a critical fleet-wide control
   - Simple, prominent, hard to miss

C) CONTACT SPAWN PANEL (create ContactPanel.jsx, wire into App.jsx)
   - Compact panel for demo setup
   - Inputs: contact_id (default "bogey-1"), x, y, heading (degrees — convert
     to radians before POST: heading_rad = heading_deg * Math.PI / 180, then
     convert from nautical to math: math_rad = (90 - heading_deg) * Math.PI / 180),
     speed (default 3.0)
   - "SPAWN" button → POST /api/contacts with converted heading
   - List active contacts (from fleetState.contacts) with REMOVE button each
   - REMOVE → DELETE /api/contacts/{contact_id}

D) 3-STATE GPS TOGGLE (modify GpsDeniedToggle.jsx)
   - Currently toggles FULL ↔ DEGRADED only
   - Change to cycle: FULL → DEGRADED → DENIED → FULL
   - Colors: FULL=green, DEGRADED=amber (#f59e0b), DENIED=red (#ef4444)
   - When DENIED: show "DR DRIFT: Xm" using position_accuracy from any
     surface asset (it's the accumulated dead reckoning drift)
   - POST /api/gps-mode with {mode: "full"/"degraded"/"denied"}

E) MISSION STATUS BAR (create MissionStatus.jsx, wire into App.jsx)
   - Compact bar at top of sidebar
   - Shows: active_mission type (or "STANDBY"), formation type
   - Asset status counts: "3 EXECUTING / 1 IDLE" (computed from assets array)
   - GPS mode with color dot
   - Contact count if any: "1 CONTACT TRACKED"

F) FLEET-TO-CONTACT INFO (in FleetMap.jsx or MissionStatus.jsx)
   - When contacts exist, compute client-side:
     - Distance from fleet centroid to first contact:
       sqrt((cx - avg_vx)² + (cy - avg_vy)²)
     - Bearing: atan2(cx - avg_vx, cy - avg_vy) * 180/PI, nautical
   - Display in MissionStatus: "TARGET: bogey-1 — 1.2km @ 045°"
   - Optional: thin dotted line on map from fleet centroid to contact

G) COASTLINE OVERLAY (modify FleetMap.jsx) — NICE TO HAVE
   The Cape Cod polygon is defined in src/navigation/land_check.py as
   CAPE_COD_POLYGON_LATLNG. You can either:
   - Copy the lat/lng coordinates directly into FleetMap.jsx as a const
   - Or add GET /api/coastline to src/api/routes.py that returns the polygon
   Render as semi-transparent Leaflet polygon (reddish-brown fill, low opacity)
   This shows the operator where land avoidance is active.

H) SCENARIO PRESETS (create ScenarioPanel.jsx) — NICE TO HAVE
   One-click demo scenarios using existing API calls:
   - "INTERCEPT": spawn contact at (2000,1000) heading west → command
     "All assets intercept contact at 2000 1000 in echelon"
   - "PATROL": command "All vessels patrol to 1500 800 in column"
   - Each is just a sequence of fetch() calls
   - 2-3 buttons max, compact

────────────────────────────────────────────────────────────────────
COORDINATE & STYLING REFERENCE
────────────────────────────────────────────────────────────────────

Coordinate conversion (already in FleetMap.jsx):
  const ORIGIN_LAT = 42.0, ORIGIN_LNG = -70.0;
  const metersToLatLng = (x, y) => [
    ORIGIN_LAT + y / 111320,
    ORIGIN_LNG + x / 82000
  ];

Contact heading: stored in radians, math convention (0=East, CCW+).
  Nautical display: (90 - degrees(heading)) % 360
  Marker rotation: same as vessel markers in FleetMap.jsx

Existing marker creation: createAssetIcon(asset) in FleetMap.jsx builds
SVG divIcon. Follow the same pattern for contacts but red + different shape.

Trail system (App.jsx): useRef { asset_id: [[x,y], ...] }, max 200 pts,
2m minimum movement. Add contact trails the same way.

Dark theme classes: bg-[#0b0f19], text-gray-300, border-gray-700/50
Accent: blue=#3b82f6 (surface), cyan=#06b6d4 (air), red=#ef4444 (contacts/threat),
amber=#f59e0b (warnings)

Sidebar order (proposed):
  MissionStatus (new, compact)
  AssetCards (existing)
  ContactPanel (new, compact)
  CommandPanel (existing)
  RTBButton (new) + GPS toggle (modified)
  ScenarioPanel (new, optional)
  MissionLog (existing, bottom)

────────────────────────────────────────────────────────────────────
WHAT NOT TO DO
────────────────────────────────────────────────────────────────────

- Do NOT modify any Python backend files except optionally adding a
  GET /api/coastline endpoint in src/api/routes.py
- Do NOT change schemas.py or any simulation code
- Do NOT add formation lines between vessels (formations are dispatch-only)
- Do NOT add click-on-map waypoint editing
- Do NOT over-engineer — these are simple React components calling fetch()
- Do NOT use any new npm packages — work with React + Leaflet + Tailwind only

────────────────────────────────────────────────────────────────────
DELIVERABLES
────────────────────────────────────────────────────────────────────

  1. Contact markers visible and moving on map with red trails
  2. RTB button works (POST /api/return-to-base)
  3. Contact spawn/remove panel works
  4. GPS toggle cycles FULL → DEGRADED → DENIED with correct API calls
  5. Mission status bar shows active mission + asset counts + GPS mode
  6. Fleet-to-contact distance/bearing displayed somewhere visible
  7. Coastline overlay (if time permits)
  8. Scenario presets (if time permits)
  9. Run Python test suite to confirm no regressions:
     .venv/bin/python -m pytest tests/ -v (expect 147 passing)
  10. Verify dashboard builds: cd dashboard && pnpm build
  11. Commit when done.

EXISTING TEST COUNT: 147 tests passing.
