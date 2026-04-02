# V2 Simulation — Observer Notes (Formatted)

Live observations from Johno watching the dashboard during the V2 run,
cross-referenced with captured telemetry data.

---

## TEST-01: PATROL (Echelon Formation, 3 waypoints, 7 m/s)

### What Johno Saw
- Ships headed in **separate directions** but generally the same way
- Eventually fell into **single file**, one after another on the same path
- Made **two turns** while in single file (right-handed)
- Drone **circled in one fixed spot** the whole time, then headed home
- Ships returned to base after the turns

### What the Data Says
- **Formation was ECHELON** (diagonal right+back), not column/single file
- Alpha-bravo mean spacing: **100m** (target: 200m) — half the commanded distance
- Bravo-charlie mean spacing: **241m** (max 397m!) — wildly inconsistent
- The "single file" look is likely echelon collapsing: alpha-bravo too close, giving a trailing appearance
- Drone orbit: **perfect 150m radius**, center at (1000, 167) — it was orbiting the fleet centroid correctly
- 3 waypoint transitions per vessel, **0 full loops** — they visited all 3 WPs but didn't loop back to WP0

### Issues Identified
1. **Echelon spacing is broken** — AB=100m instead of 200m. Vessels are too close together, which is why they look single-file.
2. **V1 collision concern confirmed** — at 100m spacing with surface vessels, they're close enough to interfere. The "running into each other" from V1 is a real problem.
3. **No patrol loop** — vessels visited WP0→WP1→WP2 but didn't cycle back to WP0. The patrol loop behavior may be broken or the 180s wasn't enough for a full second pass at 7 m/s.

---

## TEST-02: SEARCH (Line Abreast, 1 waypoint, 5 m/s)

### What Johno Saw
- All vehicles headed out to sea, **formation looked good**
- Eagle **paused at a location** (stuck)
- Boats made it to where the drone was, then returned home

### What the Data Says
- Line abreast spacing: **215m** (target: 200m) — actually solid, 7.5% error
- **Eagle-1 stuck for 104 seconds** — reproduced the V1 bug. Speed=0 while status="executing"
- Zero heading reversals detected — the **zigzag lawnmower pattern may not be working**

### Issues Identified
1. **Eagle-1 sweep bug confirmed** — drone gets stuck at a sweep endpoint for 104s. This is the same bug from V1 (280 frames stuck). It's a real issue in `drone_dynamics.py` or `drone_coordinator.py`.
2. **No zigzag detected** — search is supposed to do a lawnmower pattern but no heading reversals were measured. Either the zigzag isn't implemented or the pattern is too subtle to detect with heading changes.

---

## TEST-03: ESCORT (Column Formation, contact at 500m, 4 m/s)

### What Johno Saw
- Target spawned **right on top of them** and started traveling away
- Drone tracked immediately and followed target away from base
- Boats didn't seem to move much, then returned to base

### What the Data Says
- Closest approach: **18m** — massive improvement over V1's 973m
- The target was spawned at (500, 200) — intentionally close this time
- Boats did close on the target (bravo within 31m, charlie within 18m)

### Issues Identified
1. **Escort works when target starts close** — but the V1 problem of never catching a distant target still exists. Escort may not have continuous waypoint updating for a moving contact.
2. Worth testing escort with target starting further away to see if the fleet can close the gap.

---

## TEST-04: LOITER (Spread Formation, 1 waypoint, 5 m/s)

### What Johno Saw
- Boats **splayed out in different directions**
- Then all making a **right-hand curve, sharp left, another curve**
- All three doing **circles**
- Then returned to base

### What the Data Says
- Orbit waypoints generated: YES
- Orbit radius: **131-132m** per vessel (target: 150m, ~12% undersized)
- Each vessel orbiting at a different center, **offset from each other** — this is the spread formation working (each vessel gets its own orbit center)
- Drone orbit: perfect 150m radius

### Issues Identified
1. **Orbit radius undersized** — 131m vs 150m target. Consistent across all 3 vessels. Likely a waypoint generation constant is off.
2. The "splaying out then circling" behavior is actually correct — spread formation with loiter means each vessel navigates to its own offset position, then generates orbit waypoints there.

---

## TEST-05: AERIAL RECON (Independent, 1 waypoint at 2000m, 5 m/s)

### What Johno Saw
- All headed off in the same direction, **good formation**
- Drone branched off left, u-turned, went toward boats, u-turned again
- Drone doing **back-and-forth sweeps** in front/left of the boats
- All turned around and headed home

### What the Data Says
- Drone altitude: steady **150m** (correct per spec)
- The back-and-forth is the **SWEEP pattern** — drone doing a raster scan of the recon area. This is working correctly.
- Surface vessels should hold 500m south of (2000, 2000) = at ~(2000, 1500)

### Issues Identified
- None obvious — the sweep pattern and surface hold behavior look correct from both observer and data perspectives.

---

## TEST-06: THREAT ESCALATION (no mission, bogey at ~8900m)

### What Johno Saw
- All stayed still until target entered a certain area
- Drone left and tracked the target

### What the Data Says
- bogey-far spawned at 8902m range
- Threat went from **none → detected at 8000m** (the level V1 never saw!)
- Kill chain entered DETECT phase
- But: bogey only reached 7121m closest approach in 240s — never got to WARNING (5000m)
- Drone didn't leave because auto-track only triggers at WARNING range (2000-5000m)

### Issues Identified
1. **4-minute test was too short** — at 2 m/s from 8900m, the contact needed ~1950s to reach warning range. The 240s test only got it to 7121m. Future runs should either spawn closer or use a faster contact.
2. **"detected" level confirmed** — this is a win. V1 never observed it because contacts were spawned inside warning range.

---

## TEST-07: INTERCEPT REPLAN (bogey at 4000m, direction change at 35s)

### What Johno Saw
- Target entered area, drone gave "instructions" for interception
- **Target changed course**, interception point moved
- This one **showcased a lot of awesome stuff**

### What the Data Says
- Full kill chain: **TRACK → LOCK (at 2997m) → ENGAGE**
- Target locked for **592 frames** (~148s)
- Confidence climbed from 0.30 to 0.98 as range closed from 2997m to 72m
- **2 replan events** detected (V1 had zero!)
- Contact was respawned heading North after 35s — intercept point shifted

### Issues Identified
- This test was a clear success. The replan system works. The kill chain progresses correctly. The confidence curve is smooth and realistic.

---

## TEST-08: COMMS DENIED — Continue Mission

### What Johno Saw
- Drone left, got ahead, started circling
- Boats followed
- Comms went down, boats **continued the mission**
- Comms came back, returned to base

### What the Data Says
- **3 waypoint transitions during comms denial** — confirmed, vessels continued patrol
- Comms behavior = "continue_mission" worked correctly

### Issues Identified
- Working as designed. This is the correct behavior for continue_mission standing orders.

---

## TEST-09: COMMS DENIED — Hold Position

### What Johno Saw
- Comms went out on the way out
- Boats **formation maybe a little off**
- Made it to the drone, comms came back, returned to base

### What the Data Says
- Mean speed during denial: **7.34 m/s** — vessels did NOT stop
- **Zero frames near zero speed**
- Vessels kept "executing" status throughout denial

### Issues Identified
1. **hold_position standing order is BROKEN** — vessels should have stopped when comms were denied, but they kept moving at full speed. The comms_lost_behavior="hold_position" is not being honored by the fleet manager.
2. This matches Johno's observation that the formation looked off but they kept going.

---

## TEST-10: COMMS DENIED — Return to Base

### What the Data Says
- Status during denial: `{'executing': 1904}` — all executing, no returning
- **Zero autonomous actions logged**
- No RTB behavior triggered

### Issues Identified
1. **return_to_base standing order is BROKEN** — same problem as hold_position. The comms_lost_behavior setting is not triggering the expected behavior when comms go denied.
2. This was also flagged in V1: "comms_lost_behavior reverted to return_to_base" — but the real problem is that **none of the standing orders work except continue_mission** (which is just "do nothing different").

---

## General Observations from Johno

### "Boats speed vs Havoc's actual boats"
- V2 tested speeds from 2-10 m/s. Actual surface speeds achieved: 4.4-9.3 m/s
- **Question for Johno**: What speed do Havoc's boats actually run at? This should be configured to match.

### "Missions need to be further out / more complex"
- The short-range tests (500-2000m) are good for diagnostics but don't showcase realistic scenarios
- Realistic intercepts would be at much greater range
- Future simulation scenarios should push 5000m+ to stress the system at operational ranges

### "Formations look funky"
The data confirms this:
- **Echelon**: AB=67-100m instead of 200m — significantly undersized
- **Line abreast**: AB=53m instead of 200m — even worse
- **Column**: AB=210m — actually correct!
- **Spread**: AB=180m instead of 300m — undersized
- Formations are tightest in echelon/line and widest in column/independent

---

## Priority Issues to Fix (Ranked)

### P0 — Broken Functionality
1. **hold_position standing order does nothing** (TEST-09) — vessels keep moving at full speed
2. **return_to_base standing order does nothing** (TEST-10) — no RTB triggered, no autonomous actions

### P1 — Bugs
3. **Eagle-1 sweep stuck bug** (TEST-02) — drone freezes for 100+ seconds during sweep pattern
4. **Echelon/line formation spacing too tight** (TEST-01, TEST-15) — 50-100m instead of 200m

### P2 — Incorrect but Functional
5. **Loiter orbit radius undersized** (TEST-04) — 131m instead of 150m target
6. **No zigzag in search pattern** (TEST-02) — zero heading reversals detected
7. **Patrol doesn't loop** (TEST-01) — visits all waypoints once but doesn't cycle back
8. **DR drift rate 3x spec** (TEST-13) — measured 1.5% vs specified 0.5%

### P3 — Improvements
9. **Max range waypoint not reached** (TEST-18) — alpha only reached 2115m of 4900m target in 90s (needs more time, not a bug)
10. **GPS restore snap** (TEST-13) — 80-87m position jump when GPS restored after denial (no smooth blending)
