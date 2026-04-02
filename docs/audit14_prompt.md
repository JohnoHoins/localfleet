# Audit 14: Simulation Bug Fixes — All Issues from Full Analysis

## YOUR MISSION

You are fixing all actionable bugs identified in the LocalFleet simulation analysis
(`data/sim_full_analysis.md`). Two simulation runs (V1: 3,468 frames, V2: 21,401 frames
across 21 isolated tests) produced a prioritized issue registry. You will fix each issue
in priority order, writing tests for every change, and running the full test suite after
each fix to confirm no regressions.

**Read `CLAUDE.md` first. Its rules are absolute.** Key constraints:
- `src/schemas.py` is immutable — never modify it
- Run `.venv/bin/python -m pytest tests/ -v` after EVERY file change
- Build bottom-up: fix the lowest-level module first, then callers

---

## FIXES TO IMPLEMENT (in order)

### Fix 1: Comms-Denied Standing Orders — P0 (fleet_manager.py)

**Bug**: `hold_position` and `return_to_base` standing orders do nothing when the fleet
is actively executing a mission. Vessels continue at full speed.

**Root cause**: `_handle_comms_denied()` at line 862 of `src/fleet/fleet_manager.py`
has this guard at line 869:
```python
if not self._has_active_mission():
    self._execute_comms_fallback("idle_during_denial")
```
`_has_active_mission()` returns True when ANY vessel is EXECUTING or RETURNING, so the
fallback NEVER fires during an active mission. `continue_mission` works by accident
(it does nothing).

**What to change in `src/fleet/fleet_manager.py`**:

1. **`_handle_comms_denied()` (line 862)**: Restructure the logic so that `hold_position`
   and `return_to_base` behaviors fire regardless of active mission state. Only
   `continue_mission` should skip the fallback when the fleet is active. Add a one-shot
   guard (`self._comms_fallback_executed`) so the fallback fires once per comms-denied
   episode, not every tick. Reset this flag in `set_comms_mode()` (line 843) when comms
   go denied.

   New logic should be:
   ```python
   def _handle_comms_denied(self):
       if self.comms_mode != "denied" or self.comms_denied_since is None:
           return
       elapsed = time.time() - self.comms_denied_since

       # Standing orders — fire once per denial episode
       if not self._comms_fallback_executed:
           behavior = self.comms_lost_behavior
           if behavior == "continue_mission":
               if not self._has_active_mission():
                   self._execute_comms_fallback("idle_during_denial")
           else:
               # hold_position and return_to_base ALWAYS execute
               self._execute_comms_fallback("comms_denied_standing_order")
           self._comms_fallback_executed = True

       # Level 3: auto-engage after escalation delay (unchanged)
       if (self.intercept_recommended
               and elapsed > 60.0
               and self.active_mission != MissionType.INTERCEPT):
           self._auto_engage_threat()
   ```

2. **`__init__()` (around line 102)**: Add `self._comms_fallback_executed = False`.

3. **`set_comms_mode()` (line 843)**: When setting mode to "denied", reset the flag:
   `self._comms_fallback_executed = False`.

4. **`_execute_comms_fallback()` (line 878)**: The `hold_position` branch (line 895)
   sets status to IDLE and speed to 0, but does NOT clear waypoints. The navigation
   loop in `step()` only runs when status is EXECUTING/RETURNING, so setting IDLE is
   sufficient. However, verify the existing code works by examining what happens when
   a vessel with waypoints goes IDLE — it should stop navigating. This is correct because
   `step()` line 432 checks `if v["status"] in (AssetStatus.EXECUTING, AssetStatus.RETURNING)`.

**Tests to add/update in `tests/test_comms_denied.py`**:

- `test_comms_hold_stops_active_mission()`: Dispatch patrol, step 20 ticks (vessels moving),
  set comms denied with `comms_lost_behavior="hold_position"`, step 20 more ticks. Assert
  all vessels have status IDLE and speed near 0.

- `test_comms_rtb_during_active_mission()`: Dispatch patrol, move vessels away from home,
  step 20 ticks, set comms denied with `comms_lost_behavior="return_to_base"`, step 20
  ticks. Assert all vessels have status RETURNING.

- `test_comms_continue_keeps_executing()`: Dispatch patrol, set comms denied with
  `comms_lost_behavior="continue_mission"`, step 100 ticks. Assert at least one vessel
  still EXECUTING. (This should already pass, but add it explicitly.)

- `test_comms_fallback_fires_once()`: Dispatch patrol with `hold_position`, set comms
  denied, step 100 ticks. Assert `autonomous_actions` contains exactly ONE "AUTO-HOLD"
  entry (not one per tick).

**Existing tests that must still pass**:
- `test_comms_denied_fleet_continues_mission` — this tests `continue_mission` behavior
  (default `comms_lost_behavior="return_to_base"` but fleet starts idle). Note: this test
  dispatches a patrol first and checks fleet stays EXECUTING. With our fix, the default
  `comms_lost_behavior` is "return_to_base", which should now trigger RTB. **You need to
  update this test**: either set `comms_lost_behavior="continue_mission"` before going
  denied, OR change the assertion to expect RETURNING. Read the test carefully before
  modifying it.
- `test_comms_denied_idle_triggers_rtb` — should still pass (idle fleet triggers RTB)
- `test_comms_denied_idle_hold_position` — should still pass

---

### Fix 2: Drone SWEEP Stuck Bug — P1 (fleet_manager.py + drone_dynamics.py)

**Bug**: Eagle-1 freezes for 100+ seconds during SEARCH mission. Status stays EXECUTING
but position doesn't change. Confirmed in both V1 and V2.

**Root cause**: Two interacting issues:

**(A)** In `src/fleet/fleet_manager.py` `dispatch_command()` around line 282:
```python
use_coordinator = (
    ac.drone_pattern is not None
    and ac.waypoints
    and (ac.drone_pattern != DronePattern.SWEEP or len(ac.waypoints) >= 2)
)
```
When SEARCH is dispatched with a single center waypoint and `drone_pattern="sweep"`,
`len(ac.waypoints) == 1` so `use_coordinator` is False. The drone gets `set_waypoints()`
with pattern=SWEEP but only 1 waypoint. It navigates there, then the SWEEP loop resets
index to 0 — the same point it's already at — and loops forever without moving.

**(B)** In `src/dynamics/drone_dynamics.py` `_step_waypoint()` at line 56: when the drone
arrives at a waypoint (dist < 2.0), it advances the index and `return`s without moving.
This is a one-tick pause normally, but combined with (A) it creates an infinite freeze.

**What to change**:

1. **`src/fleet/fleet_manager.py` `dispatch_command()`** around line 279-295: When a
   SWEEP pattern has only 1 waypoint, generate a default sweep area (similar to how
   AERIAL_RECON does it at line 240-246). Add this BEFORE the `use_coordinator` check:
   ```python
   # For air assets with SWEEP pattern and only 1 waypoint,
   # generate a default sweep area around the center point
   if (ac.domain == DomainType.AIR
           and ac.drone_pattern == DronePattern.SWEEP
           and len(ac.waypoints) == 1):
       center = ac.waypoints[0]
       ac.waypoints = [
           Waypoint(x=center.x - 500, y=center.y - 500),
           Waypoint(x=center.x + 500, y=center.y + 500),
       ]
   ```
   This ensures `use_coordinator` evaluates True and the DroneCoordinator generates
   proper raster waypoints.

2. **`src/dynamics/drone_dynamics.py` `_step_waypoint()`** at line 61-68: Remove the
   early `return` after index advance. Instead, fall through so the drone immediately
   starts heading toward the new waypoint in the same tick. Change to:
   ```python
   if dist < 2.0:
       self.current_wp_index += 1
       if self.current_wp_index >= len(self.waypoints):
           if self.pattern == DronePattern.SWEEP:
               self.current_wp_index = 0
           else:
               self.status = AssetStatus.IDLE
               return
       # Don't return — fall through to move toward next waypoint
       wp = self.waypoints[self.current_wp_index]
       dx, dy = wp.x - self.x, wp.y - self.y
       dist = math.sqrt(dx * dx + dy * dy)
       if dist < 0.1:
           return  # Already at next waypoint too
   ```

**Tests to add/update in `tests/test_drone_dynamics.py`**:

- `test_sweep_single_waypoint_no_freeze()`: Create a DroneAgent, set_waypoints with
  [Waypoint(100, 100)] and pattern=SWEEP. Step 200 times. Assert the drone is still
  EXECUTING (not frozen). With the old code this would freeze; with fix (2) alone the
  drone will at least not freeze even if trapped.

- `test_sweep_continues_moving()`: Create DroneAgent, set_waypoints with a proper
  multi-point sweep pattern, step 500 times. Record positions every 50 steps. Assert
  no two consecutive positions are identical (no stuck periods).

**Test to add in `tests/test_fleet_manager.py` or `tests/test_mission_behaviors.py`**:

- `test_search_drone_gets_sweep_area()`: Create FleetManager, dispatch SEARCH command
  with single waypoint `(1000, 1000)` and `drone_pattern="sweep"`. Assert
  `fm.drone_coordinator._current_pattern == DronePattern.SWEEP` AND
  `len(fm.drone.waypoints) > 2` (coordinator generated raster waypoints, not just the
  single point).

---

### Fix 3: Formation Continuous Tracking — P1 (fleet_manager.py)

**Bug**: Formation spacing is wrong for echelon (57m vs 200m), line abreast (53m vs 200m),
and spread (178m vs 300m). Only column is accurate.

**Root cause**: Formation offsets are applied ONCE at dispatch time to destination
waypoints. Vessels start at different distances from their formation positions, so during
transit the spacing reflects trajectory convergence, not formation geometry. The offsets
are correct in `formations.py` — the problem is that they're static, not tracked.

**What to change in `src/fleet/fleet_manager.py`**:

1. **Add `_update_formation_positions()` method** (modeled on `_update_escort_positions()`
   at line 387). This method should:
   - Only run when `self.formation != FormationType.INDEPENDENT`
   - Get the leader vessel (first in `self.vessels` dict — "alpha")
   - Compute the leader's current world position and heading
   - Call `apply_formation()` with the leader's current position and heading
   - For each follower vessel that is EXECUTING, update its last waypoint to the
     computed formation position (converted to NMI)

   ```python
   def _update_formation_positions(self):
       """Continuously update follower waypoints to maintain formation."""
       if self.formation == FormationType.INDEPENDENT:
           return
       if self.active_mission is None:
           return

       vessel_ids = list(self.vessels.keys())
       leader_id = vessel_ids[0]
       leader_v = self.vessels[leader_id]

       if leader_v["status"] != AssetStatus.EXECUTING:
           return

       leader_state = leader_v["state"]
       leader_x = float(leader_state[0])
       leader_y = float(leader_state[1])
       leader_heading_deg = (90 - math.degrees(float(leader_state[2]))) % 360

       cmd_spacing = 200.0  # Default — ideally store from last command
       if self.last_command:
           cmd_spacing = self.last_command.spacing_meters

       positions = apply_formation(
           leader_x, leader_y, leader_heading_deg,
           vessel_ids, self.formation, cmd_spacing,
       )

       for vid in vessel_ids[1:]:  # Skip leader
           v = self.vessels[vid]
           if v["status"] != AssetStatus.EXECUTING:
               continue
           wpts_x = v["waypoints_x"]
           wpts_y = v["waypoints_y"]
           if len(wpts_x) < 2:
               continue
           fp = positions[vid]
           wpts_x[-1] = fp.x * METERS_TO_NMI
           wpts_y[-1] = fp.y * METERS_TO_NMI
   ```

2. **Call it from `step()`** (around line 406): Add a call right after the escort tracking
   update, using the same `_threat_check_counter == 0` cadence (every ~1 second) to avoid
   unnecessary computation:
   ```python
   # Formation tracking — update every threat check interval
   if self._threat_check_counter == 0:
       self._update_formation_positions()
   ```
   Place this just after the existing escort tracking block (after line 410).

3. **Do NOT change `formations.py`** — the offset math is correct. Do NOT change
   `dispatch_command()` formation logic — it still sets the initial waypoints. The
   continuous update supplements the one-shot dispatch.

**Tests to add in `tests/test_fleet_manager.py` or `tests/test_mission_behaviors.py`**:

- `test_echelon_formation_spacing()`: Create FleetManager, dispatch patrol with
  echelon formation, spacing=200, waypoint at (2000, 1000). Step 400 ticks (100s).
  Compute distances between alpha and bravo, bravo and charlie. Assert both mean
  distances are within 50% of the echelon diagonal target (200*√2 ≈ 283m). The exact
  converged spacing depends on Nomoto dynamics, so use a generous tolerance.

- `test_column_formation_still_works()`: Same as above but with column formation.
  Assert AB and BC distances are within 30% of 200m target. This is a regression guard.

- `test_formation_updates_continuously()`: Dispatch with echelon formation. Record
  alpha's last waypoint and bravo's last waypoint at step 0 and step 200. Assert
  bravo's last waypoint CHANGED between step 0 and step 200 (proving continuous update).

---

### Fix 4: Auto-Engage Spam Guard — P3 (fleet_manager.py)

**Bug**: `_auto_engage_threat()` fires every tick after the 60s timeout, producing 60+
duplicate AUTO-INTERCEPT actions in the log.

**Root cause**: `_handle_comms_denied()` line 873 calls `_auto_engage_threat()` every tick
when conditions are met. There's no guard to prevent re-engagement when already
intercepting the same target.

**What to change in `src/fleet/fleet_manager.py`**:

1. **`_auto_engage_threat()` (line 905)**: Add an early return if the fleet is already
   intercepting the recommended target:
   ```python
   def _auto_engage_threat(self):
       target_id = self.recommended_target
       if not target_id or target_id not in self.contacts:
           return
       # Guard: don't re-engage if already intercepting this target
       if (self.active_mission == MissionType.INTERCEPT
               and self.kill_chain_target == target_id):
           return
       ...
   ```

**Test to add in `tests/test_comms_denied.py`**:

- `test_auto_engage_fires_once()`: Create FleetManager, spawn critical-range contact,
  set comms denied with `comms_denied_since` 70s ago (past timeout), call `_check_threats()`
  then `_handle_comms_denied()` 10 times in a loop. Assert `autonomous_actions` has
  exactly 1 AUTO-INTERCEPT entry.

---

### Fix 5: GPS Restore Smooth Blending — P2 (fleet_manager.py)

**Bug**: When GPS mode transitions from DENIED to FULL, the navigation position snaps
80-87m from the DR estimate to the true position in a single tick.

**Root cause**: `set_gps_mode()` at line 822 instantly resets DR state to true position:
```python
elif mode != GpsMode.DENIED and self.gps_mode == GpsMode.DENIED:
    for vid, v in self.vessels.items():
        s = v["state"]
        self.dr_states[vid] = DeadReckoningState(
            estimated_x=float(s[0]), estimated_y=float(s[1]),
        )
```

**What to change in `src/fleet/fleet_manager.py`**:

1. **Add blend state tracking** in `__init__()`: Add `self._gps_blend_alpha: float = 1.0`
   and `self._gps_blending: bool = False`.

2. **`set_gps_mode()` (line 822)**: When leaving DENIED mode, instead of resetting DR
   state to true position, start a blend. Set `self._gps_blending = True` and
   `self._gps_blend_alpha = 0.0`. Don't reset `self.dr_states` — keep the old DR
   estimates.

3. **In `step()` (around line 416-427)**: After the existing GPS mode navigation position
   logic, add blend handling. When `self._gps_blending` is True:
   - Increment `self._gps_blend_alpha` by `dt / 5.0` (5-second blend)
   - If `_gps_blend_alpha >= 1.0`, set `_gps_blending = False` and `_gps_blend_alpha = 1.0`
   - Use `nav_x = dr_x * (1 - alpha) + true_x * alpha` for the blended position

   This must be done carefully since the GPS mode check is inside the per-vessel loop.
   The blend should only apply when `self.gps_mode != GpsMode.DENIED` AND
   `self._gps_blending` is True. In that case, use the blend between the old DR estimate
   and the true position.

**Test to add in `tests/test_gps_denied.py`**:

- `test_gps_restore_smooth_blend()`: Create FleetManager, dispatch patrol, step 20 ticks.
  Set GPS to DENIED, step 100 ticks (accumulate drift). Record DR position. Set GPS back
  to FULL. Step 1 tick. Get fleet state — nav position should be close to old DR position,
  NOT snapped to true position. Step 20 more ticks (5s). Get fleet state — position should
  now be close to true position. Assert the initial jump is < 20m.

---

### Fix 6: Loiter Orbit Radius Correction — P2 (fleet_manager.py)

**Bug**: Loiter orbit radius is 131m instead of 150m target.

**Root cause**: In `step()` at line 452, orbit waypoints are generated as an 8-point
polygon at 150m radius. But the Nomoto dynamics cut corners on the polygon, inscribing
the octagon. The effective radius is `150 * cos(π/8) ≈ 138.6m`, and with additional
dynamics smoothing it drops to ~131m.

**What to change in `src/fleet/fleet_manager.py`**:

1. **Line 453**: Change the orbit radius to compensate for corner-cutting. Use
   `radius = 150 / math.cos(math.pi / 8)` ≈ 162.1m so the inscribed radius ≈ 150m:
   ```python
   # Compensate for octagon inscribed radius
   orbit_radius = 150.0 / math.cos(math.pi / 8)
   ...
   orbit_x.append((lx + orbit_radius * math.cos(angle)) * METERS_TO_NMI)
   orbit_y.append((ly + orbit_radius * math.sin(angle)) * METERS_TO_NMI)
   ```

**Test**: Existing loiter tests should still pass. No new test needed — this is a tuning
change that would require a full sim run to verify the measured radius.

---

## EXECUTION ORDER AND RULES

1. Fix 1 (comms P0) → run tests → Fix 2 (drone sweep P1) → run tests → Fix 3
   (formation P1) → run tests → Fix 4 (auto-engage P3) → run tests → Fix 5 (GPS blend
   P2) → run tests → Fix 6 (orbit radius P2) → run tests

2. **One file at a time.** Each fix touches at most 2 files (source + test). Finish
   and test the source change before moving to the next fix.

3. **Do not touch `src/schemas.py`.** Ever.

4. **Do not refactor working code.** If a function works and you don't need to change
   it for your fix, leave it alone.

5. **Run the full test suite** (`.venv/bin/python -m pytest tests/ -v`) after every
   source file change. If a test fails that you didn't modify, investigate before
   continuing — you may have introduced a regression.

6. **When adding tests**, put them in the existing test file for that module. Don't
   create new test files.

7. All coordinates are in meters unless explicitly converted to NMI. Headings in
   `fleet_manager.py` follow the convention: math frame (psi: 0=East, CCW+), nautical
   display ((90 - degrees(psi)) % 360 → 0=North). `formations.py` uses nautical heading
   degrees as input.

---

## FILES YOU WILL MODIFY

| File | Fixes |
|------|-------|
| `src/fleet/fleet_manager.py` | F1, F2, F3, F4, F5, F6 |
| `src/dynamics/drone_dynamics.py` | F2 |
| `tests/test_comms_denied.py` | F1, F4 |
| `tests/test_drone_dynamics.py` | F2 |
| `tests/test_mission_behaviors.py` | F2, F3 |
| `tests/test_gps_denied.py` | F5 |

**Do not modify any other source files.** If you discover a bug in another file while
working, note it but don't fix it — scope is locked to these 6 fixes.

---

## VERIFICATION

After all 6 fixes, run the full suite one final time:
```bash
.venv/bin/python -m pytest tests/ -v
```

Expected outcome: all existing tests pass + all new tests pass. Zero failures.

Then show a summary of what changed: file, function, what the fix does, and which issue
IDs from the analysis it addresses (F-01 through F-17).
