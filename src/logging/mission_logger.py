"""
MissionLogger — SQLite-backed event logging for LocalFleet.
Logs MissionEvent records (commands, state snapshots, GPS changes, etc.)
to a SQLite database in data/logs/.
"""
import json
import os
import sqlite3
import time
from datetime import datetime
from typing import List, Optional

from src.schemas import (
    DomainType,
    FleetCommand,
    FleetState,
    GpsMode,
    MissionEvent,
)

DEFAULT_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs")


class MissionLogger:
    """Logs MissionEvent records to a SQLite database."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            os.makedirs(DEFAULT_DB_DIR, exist_ok=True)
            db_path = os.path.join(DEFAULT_DB_DIR, "mission_log.db")
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  REAL    NOT NULL,
                event_type TEXT    NOT NULL,
                asset_id   TEXT,
                domain     TEXT,
                data       TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp)
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Core insert
    # ------------------------------------------------------------------
    def log_event(self, event: MissionEvent):
        """Insert a single MissionEvent into the database."""
        self._conn.execute(
            "INSERT INTO events (timestamp, event_type, asset_id, domain, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.timestamp,
                event.event_type,
                event.asset_id,
                event.domain.value if event.domain else None,
                json.dumps(event.data),
                event.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Convenience loggers
    # ------------------------------------------------------------------
    def log_command(self, command: FleetCommand):
        """Log a fleet command event."""
        self.log_event(MissionEvent(
            timestamp=time.time(),
            event_type="command",
            data=command.model_dump(mode="json"),
        ))

    def log_state(self, state: FleetState):
        """Log a fleet state snapshot."""
        self.log_event(MissionEvent(
            timestamp=state.timestamp,
            event_type="state",
            data=state.model_dump(mode="json"),
        ))

    def log_gps_change(self, mode: GpsMode, noise_meters: float = 25.0):
        """Log a GPS mode change."""
        self.log_event(MissionEvent(
            timestamp=time.time(),
            event_type="gps_change",
            data={"mode": mode.value, "noise_meters": noise_meters},
        ))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def get_events(
        self,
        event_type: Optional[str] = None,
        asset_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 1000,
    ) -> List[MissionEvent]:
        """Query logged events with optional filters."""
        clauses: List[str] = []
        params: list = []

        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if asset_id is not None:
            clauses.append("asset_id = ?")
            params.append(asset_id)
        if start_time is not None:
            clauses.append("timestamp >= ?")
            params.append(start_time)
        if end_time is not None:
            clauses.append("timestamp <= ?")
            params.append(end_time)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM events{where} ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def count_events(self, event_type: Optional[str] = None) -> int:
        """Count events, optionally filtered by type."""
        if event_type:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = ?", (event_type,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> MissionEvent:
        return MissionEvent(
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            asset_id=row["asset_id"],
            domain=DomainType(row["domain"]) if row["domain"] else None,
            data=json.loads(row["data"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def close(self):
        self._conn.close()
