# LocalFleet Demo — Final Script (Verified & Fixed 2026-04-02)

> All voice commands tested via API — 7/7 parse correctly on first try.
> LLM response times: 15-21s warm, 24s cold start.
> 222 tests passing. 3 demo-blocking issues fixed (see changelog at bottom).
> System: Ollama + qwen2.5:72b on Mac Studio M3 Ultra 256GB.

---

## STARTUP SEQUENCE (Cold Start — Under 2 Minutes)

Run these in three separate terminal tabs:

```bash
# Tab 1: Ollama (skip if already running)
ollama serve

# Tab 2: Backend
cd ~/Desktop/localfleet
.venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000

# Tab 3: Dashboard
cd ~/Desktop/localfleet/dashboard
pnpm dev
```

Open browser: `http://localhost:5173`

**Expected**: Map with 4 asset markers near Cape Cod origin, green connection indicator
in the header. Simulation is ticking in the background (assets will move if commanded
even before the dashboard connects).

---

## PRE-FLIGHT CHECKLIST

```
[ ] 1. Ollama running
     curl http://localhost:11434/api/tags      → qwen2.5:72b in list
     ollama ps                                 → model loaded in memory after warm-up

[ ] 2. Backend running
     curl http://127.0.0.1:8000/api/assets     → 4 assets, active_mission: null

[ ] 3. Dashboard running + green connection dot in header

[ ] 4. Microphone working
     Click MIC → speak "test" → click STOP → red while recording, yellow processing

[ ] 5. LLM WARM-UP (CRITICAL — cold start is 24s, warm is 15-21s)
     Type 3 throwaway commands in the text input:
       "all vessels loiter at 500 500"
       "all vessels patrol to 1000 500"
       "all assets search area at 2000 1000"
     Each should return success. Check ollama ps → model should show as loaded.

[ ] 6. Clean state
     curl -X POST http://127.0.0.1:8000/api/reset   → instant reset, no restart needed
     Refresh browser, wait for green connection
     Verify: 4 assets at home positions, no contacts, no active mission

[ ] 7. Screen layout
     Fullscreen browser (F11), zoom map to ~5km radius around origin
     Decision log panel visible on right side
```

---

## ACT 1: INTERCEPT & KILL CHAIN (90 seconds)

**Capability pillars**: Cross-domain coordination, kill chain automation, predictive navigation

### Setup (before speaking — 10s)
- In the contact panel, spawn: `bogey-1`, x=`4500`, y=`2500`, heading=`230`, speed=`3`
  *(Far upper-right, heading southwest across the shore — gives the audience time to
  watch the threat close from WARNING to CRITICAL as it cuts across the operating area)*

### Narration
> "We have a surface contact to the northeast, heading southwest across the operating
> area at 3 meters per second. The threat detector picks it up automatically — you can
> see the assessment in the decision log."

**Wait 2-4s** — threat assessment appears in the decision log. Kill chain transitions
from DETECT to TRACK. Drone auto-retasks without any command.

> "The drone auto-retasks to TRACK the contact — that's the kill chain progressing from
> DETECT to TRACK. No human command needed."

### Voice Command (click MIC, speak clearly, click STOP)
> **"All assets intercept bogey one in echelon formation"**

*Verified: mission=intercept, formation=echelon, all 4 assets. ~21s parse time.*

**Wait** for LLM success indicator. During the ~20s parse, narrate:

> "The command goes to a 72 billion parameter model running locally on this machine. No
> cloud, no API calls. The model parses natural language into structured fleet commands."

Once the fleet starts moving:

> "The fleet is converging on a predicted intercept point — not where the target IS,
> but where it WILL BE when the fleet arrives. You can see the intercept solution in
> the decision log with the confidence score."

### Point out on screen
- Kill chain phase indicator: DETECT -> TRACK -> LOCK -> ENGAGE
- Fleet moving in echelon formation toward the predicted intercept point
- Decision log entries with confidence scores and rationale
- Drone providing targeting data (bearing, range)

> "Kill chain: detect, track, lock, engage. The drone provides targeting data. The fleet
> navigates to the intercept point. This is autonomous JADC2 at the edge."

**Transition**: Remove bogey-1 (click X in contact panel).

---

## ACT 2: FORMATION PATROL & SEARCH (60 seconds)

**Capability pillars**: Multi-domain coordination, formation geometry, mission diversity

### Voice Command
> **"All vessels patrol to two thousand one thousand in echelon at five meters per second"**

*Verified: mission=patrol, formation=echelon, speed=5.0, waypoint=(2000,1000). ~15s.*

> "Echelon formation — the followers continuously track the leader's position and heading.
> The formation holds shape through turns, not just at the destination."

**Point out**: Three surface vessel markers maintaining diagonal spacing on the map.
Drone orbiting over the fleet centroid.

**After ~15 seconds** of watching the formation move:

### Voice Command
> **"All assets search area at two thousand five hundred"**

*Verified: mission=search, drone=sweep pattern, surface=12 zigzag waypoints. ~21s.*

> "Search mission — surface vessels get a zigzag lawnmower pattern, the drone switches
> to sweep. Multi-domain sensor coverage of the search area."

**Point out**: Drone sweeping a raster pattern while surface vessels navigate the zigzag.

---

## ACT 3: COMMS-DENIED AUTONOMY (90 seconds)

**Capability pillars**: Resilience, autonomous decision-making, human-on-the-loop

This is the money act. Defense audiences care most about degraded operations.

### Part A: Hold Position Standing Orders

#### Voice Command
> **"All vessels patrol to three thousand zero in column with hold position standing orders"**

*Verified: mission=patrol, formation=column, comms_lost_behavior=hold_position. ~19s.*

The LLM now understands standing orders natively. No hidden terminal needed.

**Wait** for fleet to start moving (~5s).

> "Fleet is executing a patrol in column formation. I've set the standing orders to hold
> position on comms loss. Now I'm going to cut the comms link."

**Click** COMMS toggle (green FULL -> red pulsing DENIED).

> "Comms denied. Watch what happens."

**Point out**: Comms denied alert box appears (red pulsing). Vessels decelerate and stop.
Status changes to IDLE. The decision log shows exactly one entry: "AUTO-HOLD_POSITION"
with rationale "Standing orders: hold_position."

> "The fleet executed its standing orders autonomously — held position, logged the action,
> and is waiting for comms to be restored. One action, not spammed every tick. Every
> autonomous decision gets an audit trail entry."

**Wait 5s** for the audience to absorb the stopped fleet.

**Click** COMMS toggle back to FULL.

> "Comms restored."

### Part B: Continue Mission + Autonomous Engagement

#### Voice Command
> **"All vessels patrol to two thousand zero with continue mission standing orders"**

*Verified: mission=patrol, comms_lost_behavior=continue_mission. ~16s.*

**Wait** for fleet to start moving.

**Spawn contact**: `bogey-2`, x=`3500`, y=`2000`, heading=`230`, speed=`4`
*(Upper-right, heading southwest across shore toward the fleet patrol route)*

> "Contact inbound. Now I'll cut comms again — but this time the fleet has continue-mission
> standing orders."

**Click** COMMS toggle to DENIED.

> "Comms denied. The fleet continues executing — that's the continue-mission standing order.
> But now there's a threat closing in. Watch the escalation."

**TIMING**: bogey-2 starts at (3500, 2000) — ~2800m from fleet centroid near (2000, 0).
It enters WARNING range quickly, then crosses into CRITICAL (<2km) as it closes at 4 m/s.
Once critical AND 60 seconds have elapsed since comms denial, auto-engage fires.
At 4x sim speed this takes ~15s real time. At 1x, narrate through the full wait.

**Narration for the 60s wait** (rotate through these):

> "The threat detector is still running autonomously. The drone auto-retasks to track
> the contact. Kill chain is progressing. After 60 seconds without operator input, the
> fleet will make an autonomous decision to engage."

> "Every tick, the threat assessment updates — range, bearing, closing rate. The decision
> log is building the audit trail in real time. You can see each assessment with its
> confidence score."

> "This is human-on-the-loop autonomy. The operator CAN intervene at any time, but the
> system doesn't freeze when they can't. The escalation delay is configurable — 60 seconds
> here. In a real deployment, that threshold would be mission-specific."

> "Notice the standing orders display changed to 'continue_mission'. The fleet knows
> the difference between 'hold and wait for orders' and 'keep going, I trust you.'"

**At ~60s**, AUTO-INTERCEPT fires. Point out:

> "AUTO-INTERCEPT. The fleet autonomously decided to engage the threat after the escalation
> timeout. One intercept action — logged with full rationale, confidence score, and the
> fact that no operator was available. This is human-on-the-loop autonomy: the system
> acts when it must, but every decision is explainable and auditable."

**Click** COMMS back to FULL. Remove bogey-2.

---

## ACT 4: GPS-DENIED OPERATIONS (60 seconds)

**Capability pillars**: Navigation resilience, dead reckoning, smooth degradation

### Voice Command
> **"All vessels patrol to three thousand one thousand at five meters per second"**

*Verified: mission=patrol, speed=5.0, waypoint=(3000,1000). ~16s.*

**Wait** for fleet to start moving (~5s).

**Click** GPS mode toggle to DENIED.

> "GPS denied. The fleet switches to dead reckoning — inertial navigation with
> accumulating drift. Watch the position accuracy indicator degrade over time."

**Point out**: GPS mode indicator turning red, position accuracy field changing,
fleet continuing to navigate with increasing uncertainty.

**Wait ~15s** to let drift accumulate visibly.

> "The fleet is still navigating, still executing its mission, but position estimates
> are drifting. Physics and land avoidance still use true position — you don't want
> vessels running aground because of dead reckoning error."

**Click** GPS mode back to FULL.

> "GPS restored. Watch the position blend — no snap. A smooth 5-second transition from
> the dead reckoning estimate back to true GPS position."

**Point out**: Navigation position smoothly converging (no visible jump on the map).

---

## ACT 5: MULTI-CONTACT THREAT PRIORITIZATION (60 seconds)

**Capability pillars**: Threat assessment, autonomous decision-making, sensor fusion

### Spawn 3 Contacts (rapidly in the contact panel)
- `bogey-A`: x=`3000`, y=`1000`, heading=`200`, speed=`2` (distant, slow)
- `bogey-B`: x=`1500`, y=`500`, heading=`180`, speed=`4` (close, fast — PRIORITY TARGET)
- `bogey-C`: x=`4000`, y=`-500`, heading=`270`, speed=`1` (far, slow)

> "Three contacts in the operating area — different ranges, speeds, and threat profiles.
> The threat detector automatically prioritizes by range and closing rate."

**Point out**: Threat assessments appearing in the decision log. bogey-B (closest,
fastest) gets CRITICAL threat level immediately. Drone auto-retasks to track it.

> "The drone autonomously retasks to track the highest-priority threat. Decision log shows
> why — range, closing rate, threat level. Every autonomous action has a rationale."

### Voice Command
> **"All assets intercept bogey bravo"**

*Verified: mission=intercept, all 4 assets. ~21s. LLM maps "bogey bravo" to bogey-B.*

> "Fleet converging on the priority target. The other contacts are still tracked — if
> the threat picture changes, the system adapts."

### Closing Narration
> "That's LocalFleet — edge-native autonomous C2. Natural language command, local LLM
> parsing, multi-domain coordination, kill chain automation, and resilient operations
> under GPS and comms denial. Every decision is explainable, every action is auditable.
> Built entirely on local compute — no cloud dependency."

Remove all contacts. End.

---

## TIMING ESTIMATES

| Act | Content | LLM Waits | Visual + Narration | Total |
|-----|---------|-----------|-------------------|-------|
| 1 | Intercept & Kill Chain | ~21s (1 cmd) | ~70s | ~90s |
| 2 | Formation + Search | ~36s (2 cmds) | ~25s | ~60s |
| 3 | Comms Denied (A+B) | ~35s (2 cmds) | ~75s (incl 60s wait) | ~110s |
| 4 | GPS Denied | ~16s (1 cmd) | ~25s | ~40s |
| 5 | Multi-Contact | ~21s (1 cmd) | ~30s | ~50s |
| **Total** | | ~129s | ~225s | **~5.5-6 min** |

**LLM wait strategy**: Never stand silent during the 15-21s parse. Narrate what the
system is doing: "The command goes to a 72 billion parameter model running locally.
No cloud calls. It's parsing the natural language into a structured fleet command with
waypoints, formation geometry, and standing orders."

---

## REMAINING NOTES

### LLM Response Time Variability
Warm responses range 15-21s. Occasionally a complex command may take longer. If a parse
exceeds 25s, keep narrating — the audience doesn't know what "normal" is.

### The 60-Second Auto-Engage Wait
This is real time and will feel long. Practice is essential. The narration fillers above
are designed to cover it, but the key is pointing at the decision log entries appearing
in real time. The audience should be watching the screen, not you.

### Voice Recognition Accuracy
If Whisper misrecognizes a word (e.g., "alfa" instead of "alpha"), the LLM has aliases
in its prompt and will map it correctly. If a full misparse occurs, fall back to typing
the command in the text input — this still demonstrates the NL parsing capability.

---

## CUE SHEET (Print This)

```
PRE-FLIGHT
[ ] Ollama running + warm (3 commands, ollama ps shows model loaded)
[ ] Backend running (curl /api/assets → 4 assets)
[ ] Dashboard green connection, fullscreen, ~5km zoom
[ ] Mic working (test record)
[ ] Clean state: curl -X POST http://127.0.0.1:8000/api/reset
[ ] Refresh browser after reset

ACT 1 — INTERCEPT (90s)
  Spawn: bogey-1, x=4500, y=2500, hdg=230, spd=3
  Wait: threat detection + drone auto-track + kill chain in decision log
  VOICE: "All assets intercept bogey one in echelon formation"
  During 20s parse: narrate local LLM, 72B parameters, no cloud
  Point out: kill chain phases, intercept prediction, formation, decision log
  Clean up: remove bogey-1

ACT 2 — FORMATION + SEARCH (60s)
  VOICE: "All vessels patrol to two thousand one thousand in echelon at five meters per second"
  Point out: echelon spacing holds during transit
  After 15s:
  VOICE: "All assets search area at two thousand five hundred"
  Point out: drone sweep, surface zigzag

ACT 3 — COMMS DENIED (90s) *** MONEY ACT ***
  Part A:
  VOICE: "All vessels patrol to three thousand zero in column with hold position standing orders"
  Wait 5s, Click COMMS DENIED
  Point out: fleet stops, AUTO-HOLD logged once, audit trail
  Wait 5s, Click COMMS FULL

  Part B:
  VOICE: "All vessels patrol to two thousand zero with continue mission standing orders"
  Spawn: bogey-2, x=3500, y=2000, hdg=230, spd=4
  Click COMMS DENIED
  Narrate for 60s (threat escalation, human-on-the-loop, configurable delay)
  AUTO-INTERCEPT fires at ~60s → point out decision rationale + confidence
  Click COMMS FULL, remove bogey-2

ACT 4 — GPS DENIED (40s)
  VOICE: "All vessels patrol to three thousand one thousand at five"
  Wait 5s, Click GPS DENIED
  Wait 15s, narrate DR drift + position accuracy degrading
  Click GPS FULL
  Point out: smooth 5s blend, no snap

ACT 5 — MULTI-CONTACT (50s)
  Spawn: bogey-A 3000/1000/hdg200/spd2
  Spawn: bogey-B 1500/500/hdg180/spd4  ← priority target
  Spawn: bogey-C 4000/-500/hdg270/spd1
  Point out: threat prioritization in decision log, drone tracks bogey-B
  VOICE: "All assets intercept bogey bravo"
  Closing narration: edge-native C2, explainable autonomy, local compute
  Remove all contacts

EMERGENCY RESET (if anything goes wrong mid-demo):
  curl -X POST http://127.0.0.1:8000/api/reset
  Refresh browser → clean state in 3 seconds
```

---

## RECOMMENDATIONS FOR AUTHENTICITY & SMOOTHNESS

### 1. Show the Hardware
Open the video with a 3-second shot of the Mac Studio. Narrate:
> "This is the entire C2 infrastructure. One Mac Studio, air-gapped, running a 72 billion
> parameter language model locally."

This immediately establishes credibility — no cloud, no staging, no tricks.

### 2. Use Voice for Everything On Camera
Now that standing orders parse via voice, every single command in the demo can be spoken.
This is dramatically more impressive than typing. Even if Whisper occasionally fumbles,
the LLM's alias handling will catch it. Reserve the text input as a silent backup only.

### 3. Fill LLM Parse Time with "Thinking Out Loud"
The 15-21s parse window is an opportunity, not a liability. Use it to show you're not
just pressing buttons:
- "That natural language command is being parsed by the local model right now..."
- "No internet connection. Everything is running on this machine."
- Point at the processing indicator on screen.

### 4. Point at the Decision Log Constantly
The decision log is your proof of explainability. Every time something autonomous happens
(drone retask, threat assessment, auto-engage), physically point at the decision log
panel on screen. Defense audiences will immediately understand the value of an audit trail.

### 5. Slow Down After Each Visual Moment
When the fleet starts moving, when formation snaps into shape, when the kill chain
advances — pause for 2-3 seconds. Let the visual register. Don't talk over the
impressive parts.

### 6. Frame the 60-Second Wait as a Feature
> "The system doesn't rush to lethal force. It gives the operator 60 seconds to resume
> control. Only when no human can respond does it escalate autonomously."

This positions the wait as responsible design, not a limitation.

### 7. Use Nautical Terminology Naturally
Instead of "3 meters per second", occasionally say "six knots" (1 m/s ~ 2 knots).
Instead of coordinates, say "bearing 090, range 4 clicks." This signals domain fluency
without being forced.

### 8. Pre-Position for Act 3 Timing
Act 3's 60-second wait is the longest dead-air risk. Ensure you've practiced the
narration fillers until they feel natural. Consider having a small sticky note with
the 4 key narration points next to your monitor.

### 9. Record at the Highest Resolution Available
The map details, decision log text, and status indicators need to be readable. Record at
native resolution (ideally 4K if the Mac Studio supports it on your display). The
audience will pause and scrub — make sure everything is crisp.

### 10. One Take Mindset After Act 2
If something breaks in Act 1 or early Act 2, restart. After Act 2, if a minor issue
occurs, recover and continue — a smooth recovery actually demonstrates robustness.
Defense systems handle failure, and so should the demo.

### 11. End Strong
The closing narration is the most important 15 seconds. Don't rush it. Make eye contact
with the camera (or look at the fleet on screen). Deliver the key terms deliberately:
"edge-native", "explainable", "auditable", "no cloud dependency."

### 12. Instant Reset for Rehearsals
Between rehearsal takes, use the new reset endpoint instead of restarting the backend:
```bash
curl -X POST http://127.0.0.1:8000/api/reset
```
Then refresh the browser. Clean state in 3 seconds. This makes rapid iteration possible
— rehearse the tricky parts (Act 3 timing, voice commands) in isolation.

---

## CHANGELOG (Fixes Applied This Session)

### Fix 1: Standing Orders via Voice (ollama_client.py)
The LLM system prompt now documents `comms_lost_behavior`. Voice commands like
"patrol to 3000 0 with hold position standing orders" parse correctly. This eliminates
the need for hidden terminal commands during Act 3.

**Verified**: "hold position standing orders" → `hold_position` (19s),
"continue mission standing orders" → `continue_mission` (16s).

### Fix 2: Reset Endpoint (routes.py)
New `POST /api/reset` endpoint reinitializes the FleetManager to clean state.
No more restarting the backend between rehearsals.

**Verified**: Resets mission, contacts, vessel positions instantly.

### Fix 3: Background Simulation Loop (server.py, ws.py)
The simulation now ticks at 4Hz in a background asyncio task regardless of WebSocket
connections. Comms-denied fallbacks, threat detection, GPS drift, and auto-engage all
work even without the dashboard connected. The WebSocket handler now only broadcasts
state.

**Verified**: AUTO-HOLD fires correctly from API-only testing. Kill chain progresses.
Threat assessments appear in decision log. No double-stepping.

All 222 tests passing after all 3 fixes.
