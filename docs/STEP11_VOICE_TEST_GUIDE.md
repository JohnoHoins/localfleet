# Step 11 — Voice Input Integration Test Guide

## Fleet Starting Positions

```
       y (meters)
       ^
       |
  200 -|
       |
  100 -|
       |                 eagle-1 (drone)
    0 -+--- alpha -------- bravo -------- charlie ---> x (meters)
       0       100       200       300       400
       |
 -100 -|               eagle-1 (200, -100, alt 100m)
```

| Asset   | Domain  | Position (x, y)  | Notes                         |
|---------|---------|-------------------|-------------------------------|
| alpha   | surface | (0, 0)            | West flank vessel             |
| bravo   | surface | (200, 0)          | Center vessel                 |
| charlie | surface | (400, 0)          | East flank vessel             |
| eagle-1 | air     | (200, -100) 100m  | Drone, south of center, 100m alt |

Coordinate system: meters, local frame. x = east, y = north. Waypoint range: 0–2000m.


---

## Terminal Setup

You need **three terminals** running simultaneously.

### Terminal 1 — Ollama (LLM inference)

```bash
ollama serve
```

> If already running, skip. Verify with: `ollama list` (should show `qwen2.5:72b`).

### Terminal 2 — FastAPI Backend

```bash
cd /Users/johno/Projects/localfleet
uvicorn src.api.server:app --reload --port 8000
```

> Wait until you see: `Uvicorn running on http://0.0.0.0:8000`

### Terminal 3 — React Dashboard

```bash
cd /Users/johno/Projects/localfleet/dashboard
pnpm dev --port 5173
```

> Wait until you see: `Local: http://localhost:5173/`

### Open the Dashboard

Open **http://localhost:5173** in Chrome/Safari (must be localhost for mic access).


---

## How to Use Voice Commands

1. Find the **MIC** button to the right of the SEND button in the COMMAND panel
2. **Press and hold** the MIC button (mouse or touch)
3. Speak your command clearly
4. **Release** the button when done speaking
5. The button shows **REC** (pulsing red) while recording, then **...** while processing
6. Result appears below the input — same area as text command results

> First use: your browser will ask for microphone permission. Click **Allow**.


---

## Voice Command Examples

These are ordered from simple to complex. Speak them naturally — the LLM parses intent, not exact syntax.

### 1. Basic Single-Asset Movement

Move one vessel to a specific area.

> **"Send Alpha to waypoint 500, 500"**

What happens: Alpha leaves (0,0), heads northeast to (500, 500). Other assets stay put.

> **"Move Bravo north to position 200, 800"**

What happens: Bravo heads due north from (200, 0) to (200, 800).

### 2. Multi-Asset Surface Patrol

Task multiple vessels with a formation.

> **"Alpha and Bravo patrol the northern sector in echelon formation"**

What happens: Alpha and Bravo get waypoints in the northern area (~y 600+), arranged in echelon (diagonal offset). Mission type: PATROL.

> **"All surface vessels patrol from west to east in column formation"**

What happens: Alpha, Bravo, Charlie get eastward waypoints in column (single-file). Good for showing formation geometry.

### 3. Drone Commands

Eagle-1 is your only air asset. It supports orbit, sweep, and track patterns.

> **"Eagle-1 orbit over position 300, 400 at 150 meters altitude"**

What happens: Drone flies to (300, 400) area, enters circular orbit at 150m. Drone pattern: ORBIT.

> **"Send the drone to sweep the eastern sector at 80 meters"**

What happens: Eagle-1 flies east (~x 800+), performs a zigzag sweep pattern at 80m altitude. Drone pattern: SWEEP.

> **"Eagle-1 track Bravo's position"**

What happens: Drone moves to Bravo's area and follows. Drone pattern: TRACK.

### 4. Multi-Domain Combined Operations

These command both surface and air assets in one order — the core demo.

> **"Alpha and Bravo patrol the harbor at waypoints 600, 200 and 800, 400 in echelon. Eagle-1 orbit overhead at 120 meters."**

What happens: Surface vessels head to patrol waypoints in echelon formation. Drone orbits above the patrol area. Mission type: PATROL. This is the money shot for the portfolio demo.

> **"All vessels search the area around 1000, 1000 in line abreast formation. Drone sweep the same area at 80 meters."**

What happens: Three vessels spread out in a line and advance toward (1000, 1000). Drone performs a sweep pattern over the search area. Mission type: SEARCH.

> **"Escort formation: Charlie take point at 500, 600, Bravo follow at 500, 400, Alpha trail at 500, 200. Eagle-1 orbit the convoy at 150 meters."**

What happens: Three vessels form a column moving north. Drone orbits above the convoy. Mission type: ESCORT.

### 5. Loiter / Hold Position

> **"All assets loiter at current positions"**

What happens: Surface vessels hold in spread formation. Drone enters station-keeping mode. Mission type: LOITER.

> **"Bravo and Charlie hold position at 300, 300 in spread formation"**

What happens: Two vessels move to the area and spread out, holding position.

### 6. Aerial Reconnaissance

Drone-primary mission — surface vessels stand by.

> **"Eagle-1 conduct aerial recon of the southern area, sweep from 0, negative 500 to 400, negative 500 at 100 meters"**

What happens: Drone sweeps the southern sector. Surface vessels remain idle/independent. Mission type: AERIAL_RECON.

### 7. GPS-Denied Scenario

Use the GPS toggle in the dashboard (separate from voice), then issue commands.

> Toggle GPS to **DEGRADED** via the dashboard toggle, then:
>
> **"Alpha and Bravo patrol waypoints 500, 300 and 700, 500"**

What happens: Assets move but positions on the map jitter with 25m noise. Uncertainty rings appear around icons. Demonstrates degraded navigation.


---

## Quick Reference — What the LLM Knows

| Category     | Valid Values                                        |
|-------------|-----------------------------------------------------|
| Surface IDs  | `alpha`, `bravo`, `charlie`                         |
| Air IDs      | `eagle-1`                                           |
| Missions     | `patrol`, `search`, `escort`, `loiter`, `aerial_recon` |
| Formations   | `echelon`, `line` (abreast), `column`, `spread`, `independent` |
| Drone patterns | `orbit`, `sweep`, `track`, `station`              |
| Surface speed | 3–8 m/s (default 5)                                |
| Drone speed  | 10–20 m/s (default 15)                              |
| Drone altitude | 50–200m                                           |
| Waypoint range | 0–2000 meters (x and y)                           |

### Lingo Tips

- You don't need exact syntax. Speak naturally: "send", "move", "patrol", "search the area"
- Name assets by ID: "Alpha", "Bravo", "Charlie", "Eagle-1" or "the drone"
- Use cardinal directions: "north", "east", "the southern sector"
- Specify coordinates when you want precision: "waypoint 500, 300"
- Mention formations explicitly: "in echelon", "line abreast", "in column"
- For the drone, mention altitude: "at 120 meters", "80 meter altitude"
- For drone behavior, use pattern words: "orbit over", "sweep the area", "track Bravo"


---

## Verification Checklist

After each voice command, confirm:

- [ ] MIC button showed pulsing red **REC** state while held
- [ ] Result panel shows **OK** with LLM response time
- [ ] Parsed FleetCommand JSON appears (expand to inspect mission_type, assets, formation)
- [ ] Assets start moving on the Leaflet map
- [ ] Drone icon (cyan) vs vessel icons (blue) behave according to their domain
- [ ] WebSocket is streaming updates (positions update smoothly at ~4Hz)

### If Something Goes Wrong

| Symptom | Fix |
|---------|-----|
| MIC button stays disabled | Click it once first to trigger permission prompt. Check browser mic settings. |
| "REC" but no result | Check Terminal 2 for errors. Audio format may need conversion — try shorter commands. |
| Result shows error | Check Terminal 1 — Ollama may not be running or model not loaded. Run `ollama run qwen2.5:72b` to preload. |
| Assets don't move | Check that WebSocket is connected (no red disconnect indicators). Check Terminal 2 logs for dispatch. |
| Transcription is wrong | Speak slower, closer to mic. Short military-style phrases work best. |


---

## 10 Voice Commands for Full Test Coverage

Run these in order for a complete demo walkthrough:

| # | Say This | Tests |
|---|----------|-------|
| 1 | "Send Alpha to waypoint 600, 400" | Single vessel movement |
| 2 | "Move Bravo north to 200, 800" | Directional command |
| 3 | "Eagle-1 orbit over 300, 300 at 120 meters" | Drone orbit pattern |
| 4 | "Alpha and Charlie patrol east in echelon" | Multi-vessel + formation |
| 5 | "All vessels search area 800, 800 in line abreast" | Full surface fleet + formation |
| 6 | "Eagle-1 sweep the eastern sector at 80 meters" | Drone sweep pattern |
| 7 | "Bravo escort Charlie to 1000, 500 in column" | Escort mission |
| 8 | "Eagle-1 conduct aerial recon south at 100 meters" | Aerial recon (drone-primary) |
| 9 | "All assets patrol the northern harbor in echelon. Eagle-1 orbit overhead at 150 meters." | Full multi-domain combined op |
| 10 | "All assets loiter at current positions" | Loiter / hold |
