# STEP 3: Audit 12 — Decision Audit Trail

## OBJECTIVE
Add explainable decision logging. Every autonomous action gets a human-readable
rationale with confidence scores. Stream via WebSocket, expose via REST API.

## PRE-FLIGHT CHECKS

1. `git log --oneline -1` — should show Audit 11 commit
2. `.venv/bin/python -m pytest tests/ -v` — 176+ tests passing
3. Read STATUS.json — audits 9-11 should be "done"

## KEY CONTEXT

Decision points to instrument (read these locations):
- `fleet_manager.py dispatch_command()` — intercept solution + asset allocation
- `fleet_manager.py _replan_intercept()` — replan when waypoints shift
- `fleet_manager.py _check_threats()` — threat assessment + auto drone retask
- `fleet_manager.py _handle_comms_denied()` — comms fallback actions
- `fleet_manager.py _auto_engage_threat()` — autonomous intercept
- `fleet_manager.py _advance_kill_chain()` — kill chain phase transitions
- `fleet_manager.py get_fleet_state_dict()` — where to inject decisions

## WHAT TO BUILD

### A) New file: src/fleet/decision_log.py

```python
"""Decision audit trail — explainable autonomous decisions."""
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class DecisionEntry:
    timestamp: float
    decision_type: str
    action_taken: str
    rationale: str
    confidence: float = 1.0
    assets_involved: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    parent_id: str | None = None

    @property
    def id(self) -> str:
        return f"{self.decision_type}_{self.timestamp:.3f}"


class DecisionLog:
    def __init__(self, max_entries: int = 200):
        self._entries: deque[DecisionEntry] = deque(maxlen=max_entries)

    def log(self, decision_type: str, action: str, rationale: str,
            confidence: float = 1.0, assets: list[str] | None = None,
            alternatives: list[str] | None = None,
            parent_id: str | None = None) -> DecisionEntry:
        entry = DecisionEntry(
            timestamp=time.time(),
            decision_type=decision_type,
            action_taken=action,
            rationale=rationale,
            confidence=confidence,
            assets_involved=assets or [],
            alternatives=alternatives or [],
            parent_id=parent_id,
        )
        self._entries.append(entry)
        return entry

    def get_recent(self, n: int = 20) -> list[DecisionEntry]:
        return list(self._entries)[-n:]

    def get_by_type(self, dtype: str) -> list[DecisionEntry]:
        return [e for e in self._entries if e.decision_type == dtype]

    def to_dicts(self, n: int = 10) -> list[dict]:
        """Serialize recent entries for WebSocket/API."""
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "type": e.decision_type,
                "action": e.action_taken,
                "rationale": e.rationale,
                "confidence": e.confidence,
                "assets": e.assets_involved,
                "alternatives": e.alternatives,
                "parent_id": e.parent_id,
            }
            for e in list(self._entries)[-n:]
        ]
```

### B) fleet_manager.py — Add decision log and instrument decisions

Add to __init__():
```python
from src.fleet.decision_log import DecisionLog
self.decision_log = DecisionLog()
```

Instrument EACH decision point. The key pattern is: at the moment a
decision is made, call self.decision_log.log() with type, action, and
a rationale string built from the data you already have.

**1. Intercept solution** — in dispatch_command(), after compute_intercept_point():
```python
dist = math.sqrt((pred_x - cx)**2 + (pred_y - cy)**2)
eta = dist / fleet_speed if fleet_speed > 0 else 0
lead = math.sqrt((pred_x - target.x)**2 + (pred_y - target.y)**2)
self.decision_log.log(
    "intercept_solution",
    f"Intercept: ({pred_x:.0f}, {pred_y:.0f})",
    f"Target {target.contact_id} at ({target.x:.0f}, {target.y:.0f}) "
    f"hdg {math.degrees(target.heading):.0f}° spd {target.speed:.1f}m/s. "
    f"Fleet centroid ({cx:.0f}, {cy:.0f}). ETA {eta:.0f}s. Lead {lead:.0f}m.",
    confidence=min(1.0, fleet_speed / max(target.speed, 0.1)),
    assets=[ac.asset_id for ac in surface_cmds],
)
```

**2. Threat assessment** — in _check_threats(), for warning/critical:
```python
self.decision_log.log(
    "threat_assessment",
    f"{ta.contact_id}: {ta.threat_level.upper()} {ta.distance:.0f}m",
    ta.reason,
    confidence=1.0 - (ta.distance / 8000.0),
)
```

**3. Auto-track** — in _check_threats(), when drone is retasked:
```python
self.decision_log.log(
    "auto_track",
    f"Eagle-1 → TRACK {ta.contact_id}",
    f"Contact {ta.distance:.0f}m ({ta.threat_level}). Fleet "
    f"{'idle' if not active_intercept else 'not intercepting'}. "
    f"Drone fastest asset (15 m/s), aerial advantage.",
    assets=["eagle-1"],
)
```

**4. Kill chain transitions** — in _advance_kill_chain(), on phase change:
```python
if self.kill_chain_phase != old_phase and self.kill_chain_phase is not None:
    self.decision_log.log(
        "kill_chain_transition",
        f"Kill chain: {old_phase or 'NONE'} → {self.kill_chain_phase}",
        f"Target: {self.kill_chain_target}. "
        f"Drone {'locked' if self.targeting_data and self.targeting_data.locked else 'searching'}.",
    )
```

**5. Replan** — in _replan_intercept(), when waypoints update:
```python
self.decision_log.log(
    "replan",
    f"Waypoints shifted {shift:.0f}m",
    f"({cur_wp_x:.0f},{cur_wp_y:.0f}) → ({pred_x:.0f},{pred_y:.0f}). "
    f"Target moved since last plan.",
)
```

**6. Comms fallback** — in _execute_comms_fallback():
```python
self.decision_log.log(
    "comms_fallback",
    f"AUTO-{behavior.upper()}: {trigger}",
    f"Comms denied. Standing orders: {behavior}.",
    confidence=1.0,
)
```

**7. Auto-engage** — in _auto_engage_threat():
```python
self.decision_log.log(
    "auto_engage",
    f"AUTO-INTERCEPT: {target_id}",
    f"Comms denied {elapsed:.0f}s. {target_id} critical range. "
    f"No operator. Timeout escalation.",
    confidence=0.7,
    assets=list(self.vessels.keys()) + ["eagle-1"],
)
```

In get_fleet_state_dict(), add:
```python
data["decisions"] = self.decision_log.to_dicts(n=10)
```

### C) routes.py — Add decisions endpoint

```python
@router.get("/decisions")
async def get_decisions(request: Request,
                        limit: int = Query(50),
                        dtype: Optional[str] = Query(None, alias="type")):
    fm = request.app.state.commander.fleet_manager
    if dtype:
        entries = fm.decision_log.get_by_type(dtype)[-limit:]
    else:
        entries = fm.decision_log.get_recent(limit)
    return {"decisions": [
        {"id": e.id, "timestamp": e.timestamp, "type": e.decision_type,
         "action": e.action_taken, "rationale": e.rationale,
         "confidence": e.confidence, "assets": e.assets_involved,
         "alternatives": e.alternatives, "parent_id": e.parent_id}
        for e in entries
    ]}
```

### D) Dashboard — Decision display in MissionLog

In MissionLog.jsx: display decision entries from `data.decisions[]`.
Each entry shows type badge (color-coded), action (bold), and expandable
rationale. Confidence as a percentage. Most recent at top.

### E) Tests — tests/test_decision_log.py

12 tests covering: store, ring buffer, filter by type, to_dicts,
parent chain, intercept logs solution, allocation logs, threat logs,
auto-track logs, replan logs, fleet state inclusion, API endpoint.

## COMMIT MESSAGE

```
feat: decision audit trail — explainable autonomy with confidence (Audit 12)

Every autonomous decision now logged with human-readable rationale and
confidence score. Instruments 7 decision points: intercept solution,
threat assessment, auto-track, kill chain transitions, replan, comms
fallback, auto-engage. Streams last 10 decisions via WebSocket. REST
API at GET /api/decisions for post-mission review.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

## POST-FLIGHT

1. `.venv/bin/python -m pytest tests/ -v` — 188+ tests, 0 failures
2. `cd dashboard && pnpm build` — no errors
3. `git log --oneline -1` — shows Audit 12 commit
4. Update STATUS.json: audit 12 status = "done", add commit hash
