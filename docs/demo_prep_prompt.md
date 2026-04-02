# Demo Video Preparation — Final Simulation Rehearsal & Sequence

## CONTEXT FOR THE AGENT

You are preparing Johno for a one-take demo video of LocalFleet — a multi-domain autonomous
fleet simulation with local LLM command & control. This video is a portfolio piece targeting
defense tech companies (specifically Havoc). It must demonstrate: **autonomy, resilience
under degraded conditions, explainable decision-making, cross-domain coordination, and
natural language / voice control.** Everything runs air-gapped on a Mac Studio M3 Ultra.

The system is fully built and tested (222 tests passing after Audit 14). All major bugs
are fixed. The goal of THIS session is:

1. Build a pre-flight checklist that verifies every system component before recording
2. Create an exact rehearsal script with voice lines, click sequences, and timing
3. Build a dry-run test sequence Johno can practice until it's muscle memory
4. Identify and mitigate every failure mode that could ruin a take
5. Produce the final prompt card / cue sheet Johno reads during recording

**Read `CLAUDE.md` first. Read `data/sim_full_analysis.md` Section 7 for demo readiness.**

---

## PHASE 1: PRE-FLIGHT CHECKLIST

Create a numbered checklist that Johno runs through before hitting record. Each item
must have a **verify** action (what to check) and a **fix** action (what to do if it fails).

### System Checks

1. **Ollama running** — Verify: `curl http://localhost:11434/api/tags` returns model list.
   Model `qwen2.5:72b` must be loaded. Fix: `ollama serve` then `ollama pull qwen2.5:72b`.

2. **Backend server running** — Verify: `curl http://127.0.0.1:8000/api/assets` returns
   JSON with 4 assets. Fix: `.venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000`.

3. **Dashboard running** — Verify: browser at `http://localhost:5173` shows map with
   4 asset markers near Cape Cod. Connection indicator is green. Fix: `cd dashboard && pnpm dev`.

4. **WebSocket streaming** — Verify: assets on map are updating (check the connection
   status dot in the header — must be green). Fix: restart backend, refresh browser.

5. **Voice input** — Verify: click MIC button, speak "test", click STOP. Button should
   go red while recording, yellow while processing, then show transcription result.
   Fix: check browser microphone permissions (System Settings > Privacy > Microphone).

6. **LLM responding** — Verify: type "all vessels patrol to 1000 500" in command input,
   click SEND. Should show success with LLM response time < 30s. Fleet should start
   moving. Fix: check Ollama logs, ensure qwen2.5:72b is warm (run a throwaway command first).

7. **Clean state** — Verify: no contacts on map, no active mission, all assets at home
   positions near origin. Fix: restart the backend server to reset all state.

8. **Screen layout** — Verify: dashboard fills the screen, no browser chrome visible,
   map is zoomed to show the full operating area (~5km radius from origin). Decision log
   panel is visible. Fix: F11 for fullscreen, adjust zoom with scroll wheel.

9. **Audio input level** — Verify: use System Settings > Sound > Input to confirm
   microphone is picking up voice at reasonable levels. Fix: adjust gain, move closer
   to mic, or switch to a different input device.

10. **LLM warm-up** — Verify: send 2-3 throwaway text commands to warm the model so
    response times during recording are fast (< 10s ideal). Fix: just send more commands.

### Pre-Record State Reset

After all checks pass, reset to clean state:
```
1. Restart backend server (kills all state)
2. Refresh dashboard browser tab
3. Wait for green connection indicator
4. Verify 4 assets at home positions, no contacts, no active mission
5. Zoom map to show ~5km operating area around origin
```

---

## PHASE 2: DEMO SCRIPT — EXACT SEQUENCE

The demo is structured as 5 acts. Total target time: **5-6 minutes**. Each act showcases
a different capability pillar. The script specifies exact voice lines, click actions,
what to point out on screen, and what the audience should see.

**Pacing rule**: After every voice command, PAUSE 2-3 seconds to let the LLM parse and
the fleet respond visually. Don't rush into narration while the fleet is still reacting.

**Narration rule**: Speak in short, confident sentences. Use defense terminology naturally.
Frame everything as capability demonstration, not "look at my project."

---

### ACT 1: INTERCEPT & KILL CHAIN (90 seconds)
**Capability pillars**: Cross-domain coordination, kill chain automation, predictive navigation

**Setup** (before speaking — 10s):
- Click the contact panel spawn fields
- Type: ID=`bogey-1`, x=`4000`, y=`0`, heading=`180` (toward fleet), speed=`3`
- Click SPAWN CONTACT

**Narration while contact appears**:
> "We have a surface contact inbound from the east at 3 meters per second. The threat
> detector picks it up automatically — you can see the assessment in the decision log."

**Wait** for threat assessment to appear in the decision log panel (~2-4 seconds).
Point out the threat level indicator changing to WARNING, then CRITICAL as the contact
closes range.

> "The drone auto-retasks to TRACK the contact — that's the kill chain progressing from
> DETECT to TRACK. No human command needed."

**Wait** for drone to start moving toward the contact on the map. The kill chain phase
indicator should show TRACK.

**Voice command** (click MIC, speak clearly, click STOP):
> "All assets intercept bogey one in echelon formation"

**Wait** for LLM to parse (watch for success indicator), then watch the fleet start moving.

> "The fleet is converging on a predicted intercept point — not where the target IS,
> but where it WILL BE when the fleet arrives. You can see the intercept solution in
> the decision log with the confidence score."

**Point out on screen**:
- Kill chain phase progressing: TRACK -> LOCK -> ENGAGE
- Intercept prediction line on the map
- Fleet moving in echelon formation toward the predicted point
- Decision log showing intercept_solution entry with confidence

> "Kill chain: detect, track, lock, engage. The drone provides targeting data — bearing,
> range, confidence. The fleet navigates to the intercept point. This is autonomous
> JADC2 at the edge."

**Wait** for fleet to close on the contact. When vessels are within ~1000m, kill chain
should show CONVERGE.

**Transition**: Remove the contact (click X in contact panel) to clean up.

---

### ACT 2: FORMATION PATROL & SEARCH (60 seconds)
**Capability pillars**: Multi-domain coordination, formation geometry, mission types

**Voice command**:
> "All vessels patrol to two thousand one thousand in echelon formation at five meters per second"

**Wait** for fleet to start moving.

> "Echelon formation — the followers continuously track the leader's position and heading.
> The formation holds shape through turns, not just at the destination."

**Point out**: The three surface vessel markers maintaining diagonal spacing on the map.
The drone is orbiting over the fleet centroid.

**After ~15 seconds** of watching the formation move, transition to search:

**Voice command**:
> "All assets search area at two thousand five hundred"

**Wait** for command to parse and fleet to reorganize.

> "Search mission — surface vessels get a zigzag lawnmower pattern, the drone switches
> to sweep. Multi-domain sensor coverage of the search area."

**Point out**: Drone sweeping a raster pattern at altitude while surface vessels navigate
the zigzag. This is the sweep fix from Audit 14 working — no freeze.

---

### ACT 3: COMMS-DENIED AUTONOMY (90 seconds)
**Capability pillars**: Resilience, autonomous decision-making, human-on-the-loop

This is the money act. Defense audiences care most about degraded operations.

**First**, dispatch a patrol so the fleet is actively executing:

**Voice command**:
> "All vessels patrol to three thousand zero in column formation"

**Wait** for fleet to start moving.

> "Fleet is executing a patrol. Now I'm going to cut the comms link."

**Click** the COMMS toggle button (should change from green FULL to red pulsing DENIED).

> "Comms denied. The fleet has standing orders: hold position. Watch what happens."

**Point out**: The comms denied alert box appears (red pulsing), vessels decelerate and
stop. Status changes to IDLE. The autonomous actions log shows "AUTO-HOLD" with exactly
one entry.

> "The fleet executed its standing orders autonomously — held position, logged the action,
> and is waiting for comms to be restored. One action, not spammed every tick."

**Wait** 5 seconds to let the audience absorb the stopped fleet.

**Click** COMMS toggle back to FULL.

> "Comms restored. Now let me show the escalation path."

**Voice command**:
> "All vessels patrol to two thousand zero"

**Wait** for fleet to start moving.

**Before going comms denied again**, spawn a threat:
- Spawn contact: ID=`bogey-2`, x=`2000`, y=`1500`, heading=`200` (toward fleet), speed=`3`

> "Contact inbound. Now I cut comms again — but this time with continue-mission standing orders."

**Important**: Before clicking COMMS toggle, you need to set the standing orders to
`continue_mission`. Do this via the text command input:
Type in command box: `set comms behavior continue mission` — OR if the UI doesn't support
this, use a REST call in a separate terminal:
```bash
curl -X POST http://127.0.0.1:8000/api/command -H "Content-Type: application/json" \
  -d '{"text": "all vessels patrol to 2000 0", "comms_lost_behavior": "continue_mission"}'
```

**NOTE TO AGENT**: Check if there is a way to set `comms_lost_behavior` through the UI
or through the command dispatch. If not, the next agent should add a small UI control or
accept it as a parameter in the command panel. Alternatively, since `dispatch_command`
sets `comms_lost_behavior` from the FleetCommand, and the LLM might generate it, test
whether saying "patrol to 2000 0 with continue mission standing orders" produces
`comms_lost_behavior="continue_mission"` in the parsed command. If the LLM doesn't
handle this, the pre-demo can set it via API before the take.

**Click** COMMS toggle to DENIED.

> "Comms denied. The fleet continues executing — that's the continue-mission standing order.
> But now there's a threat closing in. Watch the escalation."

**Wait** ~60 seconds (this is real time — the auto-engage timeout is 60s). During this
time, narrate what's happening:

> "The threat detector is still running autonomously. The drone auto-retasks to track
> the contact. Kill chain is progressing. After 60 seconds without operator input, the
> fleet will make an autonomous decision to engage."

**At ~60s**, the fleet should auto-engage. Point out:

> "AUTO-INTERCEPT. The fleet autonomously decided to engage the threat after the escalation
> timeout. One intercept action — logged with full rationale, confidence score, and the
> fact that no operator was available. This is human-on-the-loop autonomy: the system
> acts when it must, but every decision is explainable and auditable."

**Click** COMMS back to FULL. Remove contact.

---

### ACT 4: GPS-DENIED OPERATIONS (60 seconds)
**Capability pillars**: Navigation resilience, dead reckoning, smooth degradation

**Voice command**:
> "All vessels patrol to three thousand one thousand at five meters per second"

**Wait** for fleet to start moving (~5 seconds).

**Click** GPS mode toggle to DENIED.

> "GPS denied. The fleet switches to dead reckoning — inertial navigation with
> accumulating drift. Watch the position accuracy indicator degrade over time."

**Point out**: The GPS mode indicator turning red, the position accuracy field changing,
the fleet continuing to navigate but with increasing uncertainty.

**Wait** ~15 seconds to let drift accumulate visibly.

> "The fleet is still navigating, still executing its mission, but position estimates
> are drifting. Physics and land avoidance still use true position — you don't want
> vessels running aground because of DR error."

**Click** GPS mode back to FULL.

> "GPS restored. Watch the position blend — no snap. A smooth 5-second transition from
> the dead reckoning estimate back to true GPS position."

**Point out**: The navigation position smoothly converging (no visible jump on the map).

---

### ACT 5: MULTI-CONTACT THREAT PRIORITIZATION (60 seconds)
**Capability pillars**: Threat assessment, autonomous decision-making, sensor fusion

**Spawn 3 contacts rapidly**:
- `bogey-A`: x=`3000`, y=`1000`, heading=`200`, speed=`2` (distant, slow)
- `bogey-B`: x=`1500`, y=`500`, heading=`180`, speed=`4` (close, fast)
- `bogey-C`: x=`4000`, y=`-500`, heading=`270`, speed=`1` (far, slow)

> "Three contacts in the operating area — different ranges, speeds, and threat profiles.
> The threat detector automatically prioritizes by range and closing rate."

**Point out**: Threat assessments appearing in the decision log. The closest fast-mover
(bogey-B) should get CRITICAL threat level. The drone auto-retasks to track it.

> "The drone autonomously retasks to track the highest-priority threat. Decision log shows
> why — range, closing rate, threat level. Every autonomous action has a rationale."

**Voice command**:
> "All assets intercept bogey bravo"

**Wait** for fleet to respond.

> "Fleet converging on the priority target. The other contacts are still tracked — if
> the threat picture changes, the system adapts."

**Closing narration**:
> "That's LocalFleet — edge-native autonomous C2. Natural language command, local LLM
> parsing, multi-domain coordination, kill chain automation, and resilient operations
> under GPS and comms denial. Every decision is explainable, every action is auditable.
> Built entirely on local compute — no cloud dependency."

Remove all contacts. End.

---

## PHASE 3: FAILURE MODES & MITIGATIONS

| Failure | Probability | Impact | Mitigation |
|---------|-------------|--------|------------|
| LLM takes > 15s to parse | Medium | Awkward pause | Warm up with 3+ commands pre-record. Have text fallback ready. |
| LLM misparses voice command | Medium | Wrong mission dispatched | Speak slowly, use exact asset names. Practice the exact phrases. Have text input as backup. |
| Voice transcription fails | Low | No command executed | Check mic levels pre-flight. Fall back to typing. |
| Ollama crashes mid-demo | Very Low | Demo over | Run `ollama ps` to verify model is loaded before recording. Don't run other heavy processes. |
| WebSocket disconnects | Low | Map stops updating | Check connection indicator. Refresh browser if needed. |
| Fleet doesn't respond to command | Low | Dead air | Check comms mode is FULL (not accidentally left DENIED). Retry command via text. |
| Contact doesn't spawn | Very Low | Missing threat scenario | Use contact panel UI — it's reliable. Double-check field values. |
| 60s auto-engage wait feels long | Certain | Boring dead air | Fill with narration about what the system is doing. Point out decision log entries appearing in real time. Practice this section especially. |
| Vessels sail off screen | Low | Lose visual | Pre-set map zoom to cover ~5km radius. Use waypoints within 3000m of origin. |
| Decision log cluttered from previous acts | Medium | Confusing | The log keeps last 10 entries. Between acts, the old entries scroll away naturally. If needed, restart backend between acts (but this kills all state). |

---

## PHASE 4: REHEARSAL PROTOCOL

### Rehearsal 1: Technical Dry Run (no narration)
Run through the entire sequence silently, focusing on:
- Click targets and timing
- Voice command recognition accuracy
- System response times
- Map zoom level and visibility

**Success criteria**: Every command parses correctly, every feature triggers as expected,
no crashes or disconnects. Time the full run.

### Rehearsal 2: Narration + Clicks (no recording)
Run through with full narration, but don't record. Focus on:
- Speaking pace (slower than natural — you're demonstrating, not chatting)
- Transition timing between acts
- Filling the 60s auto-engage wait naturally
- Not rushing past visual moments (let the fleet move before narrating what it's doing)

**Success criteria**: Smooth narration, no "uh"s or restarts, total time 5-6 minutes.

### Rehearsal 3: Full Dress Rehearsal (screen record, no publish)
Record the screen with QuickTime or OBS. Watch it back critically:
- Is the map visible and readable?
- Can you hear the voice clearly?
- Are there dead spots where nothing is happening on screen?
- Does the pacing feel right for an audience that doesn't know the system?

**Success criteria**: You'd be comfortable sending this video if you had to.

### Rehearsal 4: Final Take
Record for real. If something goes wrong in the first 30 seconds, restart immediately.
If something goes wrong after Act 2, either recover gracefully (defense systems handle
failure — so can you) or note it and move on. A small recovery is better than a restart.

---

## PHASE 5: CUE SHEET (Print This)

This is the condensed version Johno keeps next to the screen during recording.

```
PRE-FLIGHT
[ ] Ollama running + warm (3 throwaway commands)
[ ] Backend running (curl http://127.0.0.1:8000/api/assets)
[ ] Dashboard running + green connection
[ ] Mic working (test record)
[ ] Clean state (restart backend, refresh browser)
[ ] Map zoomed to ~5km, fullscreen

ACT 1 — INTERCEPT (90s)
  Spawn: bogey-1, 4000, 0, hdg 180, spd 3
  Wait for threat detection + drone auto-track
  VOICE: "All assets intercept bogey one in echelon formation"
  Point out: kill chain, intercept prediction, decision log
  Clean up: remove contact

ACT 2 — FORMATION + SEARCH (60s)
  VOICE: "All vessels patrol to two thousand one thousand in echelon at five meters per second"
  Point out: formation spacing holds during transit
  VOICE: "All assets search area at two thousand five hundred"
  Point out: drone sweep, surface zigzag

ACT 3 — COMMS DENIED (90s)
  VOICE: "All vessels patrol to three thousand zero in column"
  Click COMMS DENIED (hold_position standing orders)
  Point out: fleet stops, AUTO-HOLD logged once
  Click COMMS FULL
  VOICE: "All vessels patrol to two thousand zero"
  Spawn: bogey-2, 2000, 1500, hdg 200, spd 3
  [Set continue_mission standing orders if needed]
  Click COMMS DENIED
  Wait 60s (narrate: threat detector, drone retask, escalation)
  Point out: AUTO-INTERCEPT fires once, decision rationale
  Click COMMS FULL, remove contact

ACT 4 — GPS DENIED (60s)
  VOICE: "All vessels patrol to three thousand one thousand at five"
  Click GPS DENIED
  Point out: DR mode, drift accumulating
  Wait 15s
  Click GPS FULL
  Point out: smooth blend, no snap

ACT 5 — MULTI-CONTACT (60s)
  Spawn: bogey-A 3000/1000/hdg200/spd2
  Spawn: bogey-B 1500/500/hdg180/spd4
  Spawn: bogey-C 4000/-500/hdg270/spd1
  Point out: threat prioritization, drone retasks to bogey-B
  VOICE: "All assets intercept bogey bravo"
  Closing narration (edge-native C2, explainable autonomy)
  Remove all contacts
```

---

## WHAT THE AGENT SHOULD DO

The agent receiving this prompt should:

1. **Run the pre-flight checklist** — start the backend, dashboard, and Ollama. Verify
   every item passes. Fix anything that doesn't.

2. **Test every voice line** — type each voice command from the script into the text
   command input and verify it parses correctly and the fleet responds as expected.
   Record exact LLM response times. If any command consistently misparses, rewrite the
   voice line to something the LLM handles reliably.

3. **Test the comms_lost_behavior flow** — verify that there IS a way to set the standing
   orders to different values between the two comms-denied demos. If the LLM doesn't
   support it via voice, find the simplest alternative (API call, UI addition, or
   pre-dispatch with the behavior set).

4. **Time each act** — run through the full sequence with a stopwatch. Report actual
   timing per act and total. Adjust the script if any act runs too long or too short.

5. **Test the 60-second auto-engage wait** — verify that the auto-engage actually fires
   at ~60s, that it produces exactly 1 AUTO-INTERCEPT action, and that the decision log
   entry has the full rationale.

6. **Verify map visibility** — take a screenshot of the dashboard at each key moment
   (fleet in formation, contacts on map, comms denied alert, GPS denied indicator) and
   confirm everything is readable at the recording resolution.

7. **Produce a final revised script** — based on test results, update any voice lines
   that didn't parse, adjust timing, and note any caveats or workarounds discovered.

8. **Document the exact startup sequence** — terminal commands in order, with expected
   output, so Johno can cold-start the entire system in under 2 minutes.

**Do not modify source code unless a blocking bug is discovered during testing.** This
session is about verification and rehearsal preparation, not development.
