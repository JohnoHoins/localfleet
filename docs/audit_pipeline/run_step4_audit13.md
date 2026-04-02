# STEP 4: Audit 13 — Mission-Specific Behaviors

## OBJECTIVE
Make each of the 6 mission types produce visually distinct fleet behavior.
PATROL loops, SEARCH zigzags, ESCORT follows contacts, LOITER orbits,
AERIAL_RECON delegates to drone. INTERCEPT unchanged.

## PRE-FLIGHT CHECKS

1. `git log --oneline -1` — should show Audit 12 commit
2. `.venv/bin/python -m pytest tests/ -v` — 188+ tests passing
3. Read STATUS.json — audits 9-12 should be "done"

## KEY CONTEXT

Read these specific sections of fleet_manager.py:
- `step()` lines 281-292: waypoint completion logic that goes IDLE — this is
  the PRIMARY code to modify for PATROL, SEARCH, LOITER
- `dispatch_command()` lines 129-218: where to add mission-specific waypoint
  generation for SEARCH and AERIAL_RECON
- `__init__()`: where to add _escort_target_id attribute
- DroneCoordinator: assign_pattern(ORBIT/SWEEP, waypoints, altitude)

The current IDLE block (lines 286-292):
```python
if i_wpt >= len(wpts_x):
    v["status"] = AssetStatus.IDLE
    v["i_wpt"] = len(wpts_x) - 1
    inputs = [0.0, 0.0]
    x_dot = vessel_dynamics(state, inputs)
    v["state"] = integration(state, x_dot, dt)
    continue
```

This needs to become mission-aware.

## WHAT TO BUILD

### A) fleet_manager.py — __init__ additions

```python
self._escort_target_id: str | None = None
```

### B) fleet_manager.py — dispatch_command() mission-specific setup

After the existing formation handling (around line 175), before the
per-asset loop, add mission-specific waypoint generation:

```python
# --- Mission-specific waypoint generation ---
if cmd.mission_type == MissionType.SEARCH:
    # Generate zigzag pattern from center waypoint
    for ac in cmd.assets:
        if ac.domain == DomainType.SURFACE and ac.waypoints:
            center = ac.waypoints[0]
            idx = [a.asset_id for a in cmd.assets
                   if a.domain == DomainType.SURFACE].index(ac.asset_id)
            ac.waypoints = self._generate_search_pattern(
                center.x, center.y,
                lateral_offset=idx * cmd.spacing_meters
            )

if cmd.mission_type == MissionType.ESCORT and self.contacts:
    # Store closest contact as escort target
    surface_xs = [self.vessels[ac.asset_id]["state"][0]
                  for ac in cmd.assets
                  if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels]
    surface_ys = [self.vessels[ac.asset_id]["state"][1]
                  for ac in cmd.assets
                  if ac.domain == DomainType.SURFACE and ac.asset_id in self.vessels]
    if surface_xs:
        cx, cy = np.mean(surface_xs), np.mean(surface_ys)
        closest = min(self.contacts.values(),
                      key=lambda c: (c.x - cx)**2 + (c.y - cy)**2)
        self._escort_target_id = closest.contact_id

if cmd.mission_type == MissionType.AERIAL_RECON:
    # Drone gets wide SWEEP, surface vessels get holding position
    for ac in cmd.assets:
        if ac.domain == DomainType.AIR and ac.waypoints:
            center = ac.waypoints[0] if ac.waypoints else Waypoint(x=1000, y=1000)
            sw = Waypoint(x=center.x - 500, y=center.y - 500)
            ne = Waypoint(x=center.x + 500, y=center.y + 500)
            ac.waypoints = [sw, ne]
            ac.drone_pattern = DronePattern.SWEEP
            ac.altitude = 150.0
        elif ac.domain == DomainType.SURFACE and ac.waypoints:
            # Surface holds 500m south of recon area
            center = ac.waypoints[0]
            ac.waypoints = [Waypoint(x=center.x, y=center.y - 500)]
```

After the per-asset loop, set drone pattern for PATROL:
```python
# Drone patterns for non-intercept missions
if cmd.mission_type == MissionType.PATROL:
    wps = [ac.waypoints for ac in cmd.assets
           if ac.domain == DomainType.SURFACE and ac.waypoints]
    if wps:
        all_wps = wps[0]
        cx = sum(w.x for w in all_wps) / len(all_wps)
        cy = sum(w.y for w in all_wps) / len(all_wps)
        self.drone_coordinator.assign_pattern(
            DronePattern.ORBIT, [Waypoint(x=cx, y=cy)], altitude=100.0)

if cmd.mission_type == MissionType.LOITER:
    wps = [ac.waypoints[-1] for ac in cmd.assets
           if ac.domain == DomainType.SURFACE and ac.waypoints]
    if wps:
        self.drone_coordinator.assign_pattern(
            DronePattern.ORBIT, [wps[0]], altitude=100.0)
```

### C) fleet_manager.py — Helper method for search pattern

```python
def _generate_search_pattern(self, center_x: float, center_y: float,
                              width: float = 500.0, height: float = 500.0,
                              legs: int = 6,
                              lateral_offset: float = 0.0) -> list[Waypoint]:
    """Generate zigzag lawnmower search waypoints."""
    wps = []
    leg_spacing = height / legs
    half_w = width / 2
    for i in range(legs):
        y = center_y - height / 2 + i * leg_spacing
        if i % 2 == 0:
            wps.append(Waypoint(x=center_x - half_w + lateral_offset, y=y))
            wps.append(Waypoint(x=center_x + half_w + lateral_offset, y=y))
        else:
            wps.append(Waypoint(x=center_x + half_w + lateral_offset, y=y))
            wps.append(Waypoint(x=center_x - half_w + lateral_offset, y=y))
    return wps
```

### D) fleet_manager.py — step() mission-aware completion

Replace the IDLE block (lines 286-292) with:

```python
if i_wpt >= len(wpts_x):
    # Mission-specific behavior at last waypoint
    if self.active_mission in (MissionType.PATROL, MissionType.SEARCH):
        # Loop back to first real waypoint
        v["i_wpt"] = 1
        i_wpt = 1
        # Fall through to navigation below
    elif self.active_mission == MissionType.LOITER:
        if not v.get("_loiter_orbit"):
            # Generate orbit waypoints around loiter point
            lx = wpts_x[-1] / METERS_TO_NMI
            ly = wpts_y[-1] / METERS_TO_NMI
            orbit_x = [v["state"][0] * METERS_TO_NMI]
            orbit_y = [v["state"][1] * METERS_TO_NMI]
            for j in range(8):
                angle = j * (2 * math.pi / 8)
                orbit_x.append((lx + 150 * math.cos(angle)) * METERS_TO_NMI)
                orbit_y.append((ly + 150 * math.sin(angle)) * METERS_TO_NMI)
            v["waypoints_x"] = orbit_x
            v["waypoints_y"] = orbit_y
            v["i_wpt"] = 1
            v["_loiter_orbit"] = True
            i_wpt = 1
            wpts_x = orbit_x
            wpts_y = orbit_y
        else:
            # Already orbiting — loop
            v["i_wpt"] = 1
            i_wpt = 1
    else:
        # Default: go IDLE
        v["status"] = AssetStatus.IDLE
        v["i_wpt"] = len(wpts_x) - 1
        inputs = [0.0, 0.0]
        x_dot = vessel_dynamics(state, inputs)
        v["state"] = integration(state, x_dot, dt)
        continue
```

IMPORTANT: clear the loiter flag on new dispatch. In dispatch_command(),
in the per-asset loop for surface vessels, add:
```python
v["_loiter_orbit"] = False  # reset on new command
```

### E) fleet_manager.py — Escort continuous tracking

Add method:
```python
def _update_escort_positions(self):
    """Update waypoints to follow escort target contact."""
    if self.active_mission != MissionType.ESCORT:
        return
    if not self._escort_target_id or self._escort_target_id not in self.contacts:
        return
    contact = self.contacts[self._escort_target_id]
    for vid, v in self.vessels.items():
        if v["status"] != AssetStatus.EXECUTING:
            continue
        wpts_x = v["waypoints_x"]
        wpts_y = v["waypoints_y"]
        if len(wpts_x) >= 2:
            wpts_x[-1] = contact.x * METERS_TO_NMI
            wpts_y[-1] = contact.y * METERS_TO_NMI
```

Call from step(), BEFORE the per-vessel loop, gated by interval:
```python
# Escort tracking — update every threat check interval
if (self.active_mission == MissionType.ESCORT
        and self._threat_check_counter == 0):
    self._update_escort_positions()
```

### F) Dashboard — Mission type colors

In MissionStatus.jsx, add color mapping for active_mission display:
```javascript
const MISSION_COLORS = {
  patrol: '#22c55e',     // green
  search: '#3b82f6',     // blue
  escort: '#06b6d4',     // cyan
  loiter: '#f59e0b',     // amber
  aerial_recon: '#a855f7', // purple
  intercept: '#ef4444',  // red
};
```

### G) Tests — tests/test_mission_behaviors.py

12 tests. Use FleetManager directly. Pattern:

```python
"""Tests for mission-specific fleet behaviors."""
import math
import numpy as np
from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, Waypoint, MissionType,
    DomainType, AssetStatus, FormationType, DronePattern,
)

def _make_fm():
    return FleetManager()

def _make_cmd(mission_type, waypoint_x=1000, waypoint_y=1000, speed=5.0):
    return FleetCommand(
        mission_type=mission_type,
        assets=[
            AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=waypoint_x, y=waypoint_y)], speed=speed),
            AssetCommand(asset_id="bravo", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=waypoint_x, y=waypoint_y)], speed=speed),
            AssetCommand(asset_id="charlie", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=waypoint_x, y=waypoint_y)], speed=speed),
            AssetCommand(asset_id="eagle-1", domain=DomainType.AIR,
                        waypoints=[Waypoint(x=waypoint_x, y=waypoint_y)],
                        speed=15.0, altitude=100.0, drone_pattern=DronePattern.ORBIT),
        ],
    )

# Tests for: patrol_loops_back, patrol_multiple_loops,
# search_generates_zigzag, search_loops, loiter_orbits,
# loiter_generated_once, escort_follows, escort_holds_on_remove,
# aerial_recon_drone_sweeps, aerial_recon_surface_loiters,
# intercept_unchanged, mission_type_in_fleet_state
```

Test patrol loop:
```python
def test_patrol_loops_back():
    fm = _make_fm()
    # Use close waypoint so vessel arrives quickly
    cmd = _make_cmd(MissionType.PATROL, waypoint_x=200, waypoint_y=0, speed=8.0)
    fm.dispatch_command(cmd)
    # Run until vessel would normally go IDLE
    for _ in range(400):
        fm.step(0.25)
    # Should still be EXECUTING (looped), not IDLE
    statuses = [v["status"] for v in fm.vessels.values()]
    assert AssetStatus.EXECUTING in statuses
```

## EXECUTION ORDER

1. Read fleet_manager.py current state
2. Add _escort_target_id to __init__
3. Add _generate_search_pattern() method
4. Add mission-specific dispatch logic
5. Modify step() IDLE block to be mission-aware
6. Add _update_escort_positions() method
7. Add escort update call in step()
8. Clear _loiter_orbit flag in dispatch
9. Create tests/test_mission_behaviors.py
10. Run tests, fix failures
11. Dashboard mission type colors
12. `cd dashboard && pnpm build`
13. Commit, update STATUS.json

## COMMIT MESSAGE

```
feat: mission-specific behaviors — patrol loops, search sweeps, escort tracks (Audit 13)

Each mission type now produces distinct behavior: PATROL loops continuously,
SEARCH generates zigzag lawnmower pattern, ESCORT follows closest contact,
LOITER orbits after arrival, AERIAL_RECON delegates drone SWEEP with surface
security. Dashboard shows mission type color coding.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

## POST-FLIGHT

1. `.venv/bin/python -m pytest tests/ -v` — 200+ tests, 0 failures
2. `cd dashboard && pnpm build` — no errors
3. `git log --oneline -1` — shows Audit 13 commit
4. Update STATUS.json: audit 13 status = "done", add commit hash
5. ALL AUDITS COMPLETE
