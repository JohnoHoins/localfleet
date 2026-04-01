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
