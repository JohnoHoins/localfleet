# STEP 2: Audit 11 — Cross-Domain Kill Chain

## OBJECTIVE
Build the sensor-to-effector loop: drone sensor model → targeting data relay
→ 5-phase kill chain state machine → fleet intercepts using drone's data.

## PRE-FLIGHT CHECKS

1. `git log --oneline -1` — should show Audit 10 commit
2. `.venv/bin/python -m pytest tests/ -v` — 164+ tests passing
3. Read STATUS.json — audits 9 and 10 should be "done"

## KEY CONTEXT

Read these files before coding:
- `src/fleet/threat_detector.py` — assess_threats() returns ThreatAssessment list.
  Kill chain phases are DRIVEN BY these threat levels, not parallel.
- `src/fleet/fleet_manager.py` — _check_threats() (lines ~349-381), _replan_intercept()
  (lines ~222-256), step() (lines ~260-344), get_fleet_state_dict() (lines ~434-455)
- `src/fleet/drone_coordinator.py` — DroneCoordinator with assign_pattern(),
  generate_track_waypoints() (single point — needs continuous update)
- `src/dynamics/drone_dynamics.py` — DroneAgent with .x, .y, .heading, .status

Key types from schemas.py:
- DronePattern: ORBIT, SWEEP, TRACK, STATION
- AssetStatus: IDLE, EXECUTING, AVOIDING, RETURNING, ERROR
- Contact: contact_id, x, y, heading (radians math convention), speed

## WHAT TO BUILD

### A) New file: src/fleet/drone_sensor.py

```python
"""Drone sensor model — detection range and FOV for targeting."""
import math
from dataclasses import dataclass


DRONE_SENSOR_RANGE = 3000.0  # meters
DRONE_SENSOR_FOV = 120.0     # degrees, forward-looking


@dataclass
class TargetingData:
    contact_id: str
    bearing: float       # radians from drone to contact
    range_m: float       # meters
    contact_x: float     # estimated contact position
    contact_y: float
    confidence: float    # 1.0 at 0m, degrades with range
    locked: bool = False # True when drone is tracking + in range + in FOV


def drone_detect_contacts(drone_x: float, drone_y: float,
                          drone_heading: float, contacts: dict,
                          sensor_range: float = DRONE_SENSOR_RANGE,
                          fov_deg: float = DRONE_SENSOR_FOV
                          ) -> list[TargetingData]:
    """Return targeting data for contacts visible to drone sensor."""
    results = []
    half_fov = math.radians(fov_deg / 2)
    for cid, contact in contacts.items():
        dx = contact.x - drone_x
        dy = contact.y - drone_y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > sensor_range:
            continue
        bearing = math.atan2(dy, dx)
        # Check FOV
        angle_diff = (bearing - drone_heading + math.pi) % (2 * math.pi) - math.pi
        if abs(angle_diff) > half_fov:
            continue
        confidence = max(0.3, 1.0 - (dist / sensor_range) * 0.7)
        results.append(TargetingData(
            contact_id=cid, bearing=bearing, range_m=dist,
            contact_x=contact.x, contact_y=contact.y,
            confidence=confidence, locked=False,
        ))
    return results
```

### B) fleet_manager.py — Kill chain state and methods

Add to __init__():
```python
# Kill chain state
self.kill_chain_phase: str | None = None
self.kill_chain_target: str | None = None
self.targeting_data: "TargetingData | None" = None
```

Add import at top:
```python
from src.fleet.drone_sensor import drone_detect_contacts, TargetingData
```

Add method:
```python
def _advance_kill_chain(self):
    """Progress kill chain based on threat detector + drone sensor."""
    if not self.contacts:
        self.kill_chain_phase = None
        self.kill_chain_target = None
        self.targeting_data = None
        return

    # Run drone sensor
    drone_hdg_rad = math.radians(90 - self.drone.heading) % (2 * math.pi)
    detections = drone_detect_contacts(
        self.drone.x, self.drone.y, drone_hdg_rad, self.contacts
    )

    # Update targeting data — best detection by confidence
    if detections:
        best = max(detections, key=lambda d: d.confidence)
        if (self.drone_coordinator._current_pattern == DronePattern.TRACK
                and best.range_m < 3000.0):
            best = TargetingData(
                contact_id=best.contact_id, bearing=best.bearing,
                range_m=best.range_m, contact_x=best.contact_x,
                contact_y=best.contact_y, confidence=best.confidence,
                locked=True,
            )
        self.targeting_data = best
        self.kill_chain_target = best.contact_id
    else:
        self.targeting_data = None

    # Phase transitions
    old_phase = self.kill_chain_phase

    if self.kill_chain_phase is None:
        real_threats = [t for t in self.threat_assessments
                        if t.threat_level != "none"]
        if real_threats:
            self.kill_chain_phase = "DETECT"
            self.kill_chain_target = real_threats[0].contact_id

    elif self.kill_chain_phase == "DETECT":
        if self.drone_coordinator._current_pattern == DronePattern.TRACK:
            self.kill_chain_phase = "TRACK"

    elif self.kill_chain_phase == "TRACK":
        if self.targeting_data and self.targeting_data.locked:
            self.kill_chain_phase = "LOCK"

    elif self.kill_chain_phase == "LOCK":
        if self.active_mission == MissionType.INTERCEPT:
            self.kill_chain_phase = "ENGAGE"

    elif self.kill_chain_phase == "ENGAGE":
        target = self.contacts.get(self.kill_chain_target)
        if target:
            for v in self.vessels.values():
                dist = math.sqrt(
                    (v["state"][0] - target.x) ** 2 +
                    (v["state"][1] - target.y) ** 2
                )
                if dist < 1000.0:
                    self.kill_chain_phase = "CONVERGE"
                    break

    elif self.kill_chain_phase == "CONVERGE":
        target = self.contacts.get(self.kill_chain_target)
        if not target:
            self.kill_chain_phase = None
        else:
            for v in self.vessels.values():
                dist = math.sqrt(
                    (v["state"][0] - target.x) ** 2 +
                    (v["state"][1] - target.y) ** 2
                )
                if dist < 200.0:
                    self.kill_chain_phase = None
                    break
```

In step(), add after `_handle_comms_denied()`:
```python
# Kill chain progression
self._advance_kill_chain()

# Continuous drone tracking — update TRACK target position
if (self.drone_coordinator._current_pattern == DronePattern.TRACK
        and self.kill_chain_target
        and self.kill_chain_target in self.contacts
        and self._threat_check_counter == 0):  # reuse threat check interval
    contact = self.contacts[self.kill_chain_target]
    self.drone_coordinator.assign_pattern(
        DronePattern.TRACK,
        [Waypoint(x=contact.x, y=contact.y)],
        altitude=100.0,
    )
```

In `_replan_intercept()`, after finding target, prefer drone data:
```python
# Prefer drone targeting data when available
if self.targeting_data and self.targeting_data.locked:
    target_for_intercept_x = self.targeting_data.contact_x
    target_for_intercept_y = self.targeting_data.contact_y
else:
    target_for_intercept_x = target.x
    target_for_intercept_y = target.y
# Use target_for_intercept_x/y in compute_intercept_point call
```

In get_fleet_state_dict(), add to data["autonomy"]:
```python
data["autonomy"]["kill_chain_phase"] = self.kill_chain_phase
data["autonomy"]["kill_chain_target"] = self.kill_chain_target
if self.targeting_data:
    data["autonomy"]["targeting"] = {
        "contact_id": self.targeting_data.contact_id,
        "bearing_deg": (90 - math.degrees(self.targeting_data.bearing)) % 360,
        "range_m": self.targeting_data.range_m,
        "confidence": self.targeting_data.confidence,
        "locked": self.targeting_data.locked,
    }
```

### C) Dashboard changes

FleetMap.jsx: When targeting data has locked=True, draw yellow line from
drone position to contact. MissionStatus.jsx: Show kill chain phase with
color progression (DETECT=yellow, TRACK=amber, LOCK=orange, ENGAGE=red).

### D) Tests — tests/test_kill_chain.py

Create test file with 12 tests covering:
- drone_detect_contacts: in range, out of range, outside FOV
- confidence degradation with range
- kill chain phases: DETECT, TRACK, LOCK, ENGAGE, full progression
- reset on contact removal
- targeting data in fleet state
- continuous drone tracking updates

Test pattern — use FleetManager with contacts and manually progress states.

## EXECUTION ORDER

1. Create src/fleet/drone_sensor.py
2. Add kill chain state to fleet_manager.__init__
3. Add _advance_kill_chain() method
4. Add kill chain call + continuous tracking to step()
5. Modify _replan_intercept() to prefer drone data
6. Add kill chain to get_fleet_state_dict()
7. Create tests/test_kill_chain.py
8. Run tests, fix failures
9. Dashboard updates
10. `cd dashboard && pnpm build`
11. Commit, update STATUS.json

## COMMIT MESSAGE

```
feat: cross-domain kill chain — drone sensor to fleet intercept (Audit 11)

Adds drone sensor model (3km range, 120° FOV) with targeting data relay.
Kill chain state machine: DETECT → TRACK → LOCK → ENGAGE → CONVERGE,
driven by threat detector output + drone sensor lock. Fleet intercept
replanning uses drone targeting data when available. Continuous drone
tracking keeps sensor lock on moving contacts.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

## POST-FLIGHT

1. `.venv/bin/python -m pytest tests/ -v` — 176+ tests, 0 failures
2. `cd dashboard && pnpm build` — no errors
3. `git log --oneline -1` — shows Audit 11 commit
4. Update STATUS.json: audit 11 status = "done", add commit hash
