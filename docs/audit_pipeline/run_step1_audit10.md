# STEP 1: Audit 10 — Comms-Denied Autonomy

## OBJECTIVE
Add COMMS DENIED mode. When the C2 link goes down, the fleet continues
operating autonomously. Escalation ladder: continue mission → execute
standing orders → auto-engage threats after 60s delay.

## PRE-FLIGHT CHECKS

1. Verify Audit 9 committed: `git log --oneline -1` should show Audit 9
2. Run tests: `.venv/bin/python -m pytest tests/ -v` — all passing
3. Read STATUS.json — audit 9 should be "done"

## KEY CONTEXT (read these files for reference, but the spec below is authoritative)

- `src/schemas.py` lines 89-101: FleetCommand has `comms_lost_behavior: str = "return_to_base"`
- `src/fleet/fleet_manager.py` line 99: `self.comms_lost_behavior` already stored
- `src/fleet/fleet_manager.py` lines 349-381: `_check_threats()` sets `self.intercept_recommended`
- `src/fleet/fleet_manager.py` lines 434-455: `get_fleet_state_dict()` injects threat data
- `src/fleet/fleet_manager.py` lines 460-492: `return_to_base()` method
- `src/api/routes.py` lines 29-33: `post_command()`, lines 90-96: `post_command_direct()`
- `src/api/routes.py` lines 62-67: `post_return_to_base()`

## WHAT TO BUILD

### A) fleet_manager.py — Add comms state and methods

Add to `__init__()` (after line 106):
```python
# Comms mode
self.comms_mode: str = "full"
self.comms_denied_since: float | None = None
self.last_command: FleetCommand | None = None
self.autonomous_actions: list[str] = []
AUTONOMOUS_ESCALATION_DELAY = 60.0  # seconds before auto-engage
```

Add `self.last_command = cmd` as FIRST LINE of `dispatch_command()` (line 130).

Add these methods to FleetManager:

```python
def set_comms_mode(self, mode: str):
    """Toggle comms mode between 'full' and 'denied'."""
    if mode == "denied" and self.comms_mode != "denied":
        self.comms_denied_since = time.time()
        self.autonomous_actions = []
        if not self._has_active_mission():
            self._execute_comms_fallback("idle_on_denial")
    elif mode == "full" and self.comms_mode == "denied":
        duration = time.time() - (self.comms_denied_since or time.time())
        self.autonomous_actions.append(
            f"COMMS RESTORED after {duration:.0f}s"
        )
        self.comms_denied_since = None
    self.comms_mode = mode

def _has_active_mission(self) -> bool:
    return any(v["status"] in (AssetStatus.EXECUTING, AssetStatus.RETURNING)
               for v in self.vessels.values())

def _handle_comms_denied(self):
    """Autonomous behavior when C2 link is down. Called from step()."""
    if self.comms_mode != "denied" or self.comms_denied_since is None:
        return
    elapsed = time.time() - self.comms_denied_since

    # Level 2: idle fleet executes standing orders
    if not self._has_active_mission():
        self._execute_comms_fallback("idle_during_denial")

    # Level 3: auto-engage after escalation delay
    if (self.intercept_recommended
            and elapsed > 60.0
            and self.active_mission != MissionType.INTERCEPT):
        self._auto_engage_threat()

def _execute_comms_fallback(self, trigger: str):
    """Execute comms_lost_behavior standing orders."""
    behavior = self.comms_lost_behavior
    if behavior == "return_to_base":
        # Check if already returning
        if any(v["status"] == AssetStatus.RETURNING for v in self.vessels.values()):
            return
        self.return_to_base()
        self.autonomous_actions.append(
            f"AUTO-RTB: {trigger}, standing orders = return_to_base"
        )
    elif behavior == "hold_position":
        for vid, v in self.vessels.items():
            if v["status"] in (AssetStatus.EXECUTING,):
                v["status"] = AssetStatus.IDLE
                v["desired_speed"] = 0.0
        self.autonomous_actions.append(
            f"AUTO-HOLD: {trigger}, standing orders = hold_position"
        )
    # "continue_mission" = do nothing

def _auto_engage_threat(self):
    """Fully autonomous intercept — no human in the loop."""
    target_id = self.recommended_target
    if not target_id or target_id not in self.contacts:
        return
    contact = self.contacts[target_id]
    surface_cmds = []
    for vid in self.vessels:
        surface_cmds.append(AssetCommand(
            asset_id=vid, domain=DomainType.SURFACE,
            waypoints=[Waypoint(x=contact.x, y=contact.y)],
            speed=8.0,
        ))
    cmd = FleetCommand(
        mission_type=MissionType.INTERCEPT,
        assets=surface_cmds,
        formation=self.formation,
    )
    self.dispatch_command(cmd)
    elapsed = time.time() - (self.comms_denied_since or time.time())
    self.autonomous_actions.append(
        f"AUTO-INTERCEPT: {target_id} at ({contact.x:.0f}, {contact.y:.0f}) "
        f"— comms denied {elapsed:.0f}s, threat critical, no operator"
    )
```

In `step()` method, add AFTER the threat detection block (after line ~341):
```python
# Comms-denied autonomous behavior
self._handle_comms_denied()
```

In `get_fleet_state_dict()`, add after the threat injection block:
```python
# Comms state
elapsed = 0.0
if self.comms_mode == "denied" and self.comms_denied_since:
    elapsed = time.time() - self.comms_denied_since
data["autonomy"] = {
    "comms_mode": self.comms_mode,
    "comms_denied_duration": elapsed,
    "comms_lost_behavior": self.comms_lost_behavior,
    "autonomous_actions": self.autonomous_actions[-10:],
}
```

### B) routes.py — Add comms-mode endpoint and gate commands

Add import at top:
```python
# (no new imports needed — BaseModel already imported)
```

Add inside `create_router()`:

```python
class CommsModeRequest(BaseModel):
    mode: str  # "full" or "denied"

@router.post("/comms-mode")
async def post_comms_mode(req: CommsModeRequest, request: Request):
    fm = request.app.state.commander.fleet_manager
    fm.set_comms_mode(req.mode)
    elapsed = 0.0
    if fm.comms_mode == "denied" and fm.comms_denied_since:
        elapsed = time.time() - fm.comms_denied_since
    return {
        "comms_mode": fm.comms_mode,
        "autonomous_actions": fm.autonomous_actions[-10:],
        "denied_duration": elapsed,
    }
```

Add `import time` to routes.py if not already there.

Gate existing command endpoints. In `post_command()`:
```python
async def post_command(req: CommandRequest, request: Request):
    commander = request.app.state.commander
    if commander.fleet_manager.comms_mode == "denied":
        return CommandResponse(success=False, error="COMMS DENIED — fleet operating autonomously")
    return commander.handle_command(req)
```

Same pattern for `post_command_direct()`:
```python
async def post_command_direct(cmd: FleetCommand, request: Request):
    commander = request.app.state.commander
    fm = commander.fleet_manager
    if fm.comms_mode == "denied":
        return {"success": False, "error": "COMMS DENIED — fleet operating autonomously"}
    fm.dispatch_command(cmd)
    commander.last_command = cmd
    return {"success": True, "fleet_command": cmd.model_dump()}
```

And `post_return_to_base()`:
```python
async def post_return_to_base(request: Request):
    commander = request.app.state.commander
    if commander.fleet_manager.comms_mode == "denied":
        return {"success": False, "error": "COMMS DENIED — fleet operating autonomously"}
    commander.return_to_base()
    return {"success": True, "action": "return_to_base"}
```

### C) Dashboard — Comms toggle and overlay

In `App.jsx`, add comms_mode state from WebSocket data:
- Extract `data.autonomy?.comms_mode` and pass to child components
- Pass to MissionStatus and CommandPanel

In `MissionStatus.jsx`:
- When comms_mode == "denied": show red banner "⛔ COMMS DENIED — AUTONOMOUS"
- Show duration timer from autonomy.comms_denied_duration
- Show autonomous_actions list

Add a comms toggle button (in App.jsx or alongside GpsDeniedToggle):
- POST /api/comms-mode on click
- Toggle between "full" and "denied"
- Visual: green when full, pulsing red when denied

### D) Tests — tests/test_comms_denied.py

Create new test file. Use this pattern from existing tests:

```python
"""Tests for comms-denied autonomous behavior."""
import math
import time
from unittest.mock import patch

from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, Waypoint, MissionType,
    DomainType, AssetStatus, FormationType, GpsMode,
)


def _make_fleet_manager():
    """Create a FleetManager with default vessel layout."""
    return FleetManager()


def _make_patrol_command():
    """Create a simple patrol command for all vessels."""
    return FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=1000, y=1000)], speed=5.0),
            AssetCommand(asset_id="bravo", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=1000, y=1000)], speed=5.0),
            AssetCommand(asset_id="charlie", domain=DomainType.SURFACE,
                        waypoints=[Waypoint(x=1000, y=1000)], speed=5.0),
        ],
        formation=FormationType.INDEPENDENT,
    )


def test_comms_denied_blocks_dispatch():
    fm = _make_fleet_manager()
    fm.set_comms_mode("denied")
    # Verify comms mode is set
    assert fm.comms_mode == "denied"
    assert fm.comms_denied_since is not None


def test_comms_denied_fleet_continues_mission():
    fm = _make_fleet_manager()
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)
    assert any(v["status"] == AssetStatus.EXECUTING for v in fm.vessels.values())
    fm.set_comms_mode("denied")
    for _ in range(100):
        fm.step(0.25)
    # Fleet should still be executing, not stopped
    assert any(v["status"] == AssetStatus.EXECUTING for v in fm.vessels.values())


def test_comms_denied_idle_triggers_rtb():
    fm = _make_fleet_manager()
    # Fleet is idle
    assert not fm._has_active_mission()
    fm.set_comms_mode("denied")
    for _ in range(10):
        fm.step(0.25)
    # Should have triggered RTB
    assert any(v["status"] == AssetStatus.RETURNING for v in fm.vessels.values())


def test_comms_denied_idle_hold_position():
    fm = _make_fleet_manager()
    fm.comms_lost_behavior = "hold_position"
    fm.set_comms_mode("denied")
    for _ in range(10):
        fm.step(0.25)
    # All vessels should be idle (holding)
    assert all(v["status"] == AssetStatus.IDLE for v in fm.vessels.values())


def test_comms_denied_auto_engage_after_delay():
    fm = _make_fleet_manager()
    # Spawn contact at critical range
    fm.spawn_contact("bogey-1", 1500, 0, math.pi, 1.0)
    fm.set_comms_mode("denied")
    # Mock time to simulate delay elapsed
    original_since = fm.comms_denied_since
    fm.comms_denied_since = time.time() - 70  # 70s ago (past 60s delay)
    # Run threat check to set intercept_recommended
    fm._check_threats()
    assert fm.intercept_recommended
    # Now handle comms denied — should auto-engage
    fm._handle_comms_denied()
    assert fm.active_mission == MissionType.INTERCEPT


def test_comms_denied_no_auto_engage_before_delay():
    fm = _make_fleet_manager()
    fm.spawn_contact("bogey-1", 1500, 0, math.pi, 1.0)
    fm.set_comms_mode("denied")
    fm._check_threats()
    assert fm.intercept_recommended
    # Don't manipulate time — delay hasn't elapsed
    fm._handle_comms_denied()
    # Should NOT have auto-engaged yet
    assert fm.active_mission != MissionType.INTERCEPT


def test_comms_restored_accepts_commands():
    fm = _make_fleet_manager()
    fm.set_comms_mode("denied")
    fm.set_comms_mode("full")
    assert fm.comms_mode == "full"
    assert fm.comms_denied_since is None
    # Should be able to dispatch
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)
    assert fm.active_mission == MissionType.PATROL


def test_comms_denied_contacts_still_work():
    fm = _make_fleet_manager()
    fm.set_comms_mode("denied")
    contact = fm.spawn_contact("bogey-1", 5000, 5000, 0, 2.0)
    assert "bogey-1" in fm.contacts


def test_comms_denied_duration_tracks():
    fm = _make_fleet_manager()
    fm.comms_denied_since = time.time() - 10  # 10 seconds ago
    fm.comms_mode = "denied"
    state = fm.get_fleet_state_dict()
    duration = state.get("autonomy", {}).get("comms_denied_duration", 0)
    assert duration >= 9.0  # at least 9 seconds


def test_dual_failure_gps_and_comms():
    fm = _make_fleet_manager()
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)
    fm.set_gps_mode(GpsMode.DENIED)
    fm.set_comms_mode("denied")
    # Run simulation — should not crash
    for _ in range(100):
        fm.step(0.25)
    # Fleet should still be operating
    assert fm.comms_mode == "denied"
    assert fm.gps_mode == GpsMode.DENIED


def test_comms_denied_autonomous_actions_logged():
    fm = _make_fleet_manager()
    fm.set_comms_mode("denied")
    # Idle fleet should trigger RTB and log it
    for _ in range(10):
        fm.step(0.25)
    assert len(fm.autonomous_actions) > 0
    assert "AUTO-RTB" in fm.autonomous_actions[0]


def test_comms_denied_stores_last_command():
    fm = _make_fleet_manager()
    cmd = _make_patrol_command()
    fm.dispatch_command(cmd)
    assert fm.last_command is not None
    assert fm.last_command.mission_type == MissionType.PATROL
```

## EXECUTION ORDER

1. Read fleet_manager.py — verify current state matches expectations
2. Add comms state attributes to __init__
3. Add self.last_command = cmd to dispatch_command()
4. Add set_comms_mode(), _has_active_mission(), _handle_comms_denied(),
   _execute_comms_fallback(), _auto_engage_threat() methods
5. Add _handle_comms_denied() call in step()
6. Add comms state to get_fleet_state_dict()
7. Modify routes.py — add /api/comms-mode, gate command endpoints
8. Create tests/test_comms_denied.py
9. Run: `.venv/bin/python -m pytest tests/ -v`
10. Fix any failures
11. Update dashboard components (comms toggle, status display)
12. Verify: `cd dashboard && pnpm build`
13. Commit
14. Update STATUS.json

## COMMIT MESSAGE

```
feat: comms-denied autonomy — fleet keeps fighting without operator (Audit 10)

Adds COMMS DENIED mode with autonomous escalation: fleet continues last
mission, executes standing orders when idle (RTB/hold), and auto-engages
critical threats after 60s delay with no operator. Supports dual failure
(GPS-denied + comms-denied). Dashboard shows comms toggle, disabled
controls overlay, and autonomous action log.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

## POST-FLIGHT

1. `.venv/bin/python -m pytest tests/ -v` — 164+ tests, 0 failures
2. `cd dashboard && pnpm build` — no errors
3. `git log --oneline -1` — shows Audit 10 commit
4. Update STATUS.json: audit 10 status = "done", add commit hash
