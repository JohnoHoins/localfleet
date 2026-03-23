"""
MissionReplay — Replay missions from SQLite logs.
Reads logged MissionEvent records and yields them in sequence
for playback or post-mission analysis.
"""
from typing import Generator, List, Optional

from src.schemas import FleetState, MissionEvent
from src.logging.mission_logger import MissionLogger


class MissionReplay:
    """Reads back logged events for replay and analysis."""

    def __init__(self, db_path: str):
        self._logger = MissionLogger(db_path=db_path)

    # ------------------------------------------------------------------
    # Full replay
    # ------------------------------------------------------------------
    def get_all_events(self, limit: int = 10000) -> List[MissionEvent]:
        """Return all logged events in chronological order."""
        return self._logger.get_events(limit=limit)

    def iter_states(self) -> Generator[FleetState, None, None]:
        """Yield FleetState snapshots in chronological order for playback."""
        events = self._logger.get_events(event_type="state", limit=100000)
        for event in events:
            yield FleetState(**event.data)

    # ------------------------------------------------------------------
    # Filtered queries
    # ------------------------------------------------------------------
    def get_commands(self) -> List[MissionEvent]:
        """Return all command events."""
        return self._logger.get_events(event_type="command")

    def get_asset_events(self, asset_id: str) -> List[MissionEvent]:
        """Return all events for a specific asset."""
        return self._logger.get_events(asset_id=asset_id)

    def get_events_in_range(
        self,
        start_time: float,
        end_time: float,
        event_type: Optional[str] = None,
    ) -> List[MissionEvent]:
        """Return events within a time window."""
        return self._logger.get_events(
            event_type=event_type,
            start_time=start_time,
            end_time=end_time,
        )

    def get_gps_changes(self) -> List[MissionEvent]:
        """Return all GPS mode change events."""
        return self._logger.get_events(event_type="gps_change")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def summary(self) -> dict:
        """Return a summary of the logged mission."""
        total = self._logger.count_events()
        commands = self._logger.count_events("command")
        states = self._logger.count_events("state")
        gps_changes = self._logger.count_events("gps_change")

        all_events = self._logger.get_events(limit=1)
        first_ts = all_events[0].timestamp if all_events else None

        last_events = self._logger.get_events(limit=100000)
        last_ts = last_events[-1].timestamp if last_events else None

        duration = (last_ts - first_ts) if (first_ts and last_ts) else 0.0

        return {
            "total_events": total,
            "commands": commands,
            "state_snapshots": states,
            "gps_changes": gps_changes,
            "duration_seconds": round(duration, 2),
        }

    def close(self):
        self._logger.close()
