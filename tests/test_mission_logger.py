"""
Tests for Step 12 — MissionLogger and MissionReplay.
Uses a temporary SQLite database for each test.
"""
import os
import tempfile
import time

import pytest

from src.schemas import (
    AssetCommand,
    AssetState,
    AssetStatus,
    DomainType,
    DronePattern,
    FleetCommand,
    FleetState,
    FormationType,
    GpsMode,
    MissionEvent,
    MissionType,
    Waypoint,
)
from src.logging.mission_logger import MissionLogger
from src.logging.replay import MissionReplay


@pytest.fixture
def tmp_db(tmp_path):
    """Yield a temp db path and clean up after."""
    db_path = str(tmp_path / "test_log.db")
    yield db_path


@pytest.fixture
def logger(tmp_db):
    lg = MissionLogger(db_path=tmp_db)
    yield lg
    lg.close()


# ------------------------------------------------------------------
# MissionLogger tests
# ------------------------------------------------------------------

def test_log_event_basic(logger):
    """Log a raw MissionEvent and retrieve it."""
    event = MissionEvent(
        timestamp=time.time(),
        event_type="command",
        asset_id="alpha",
        domain=DomainType.SURFACE,
        data={"action": "patrol"},
    )
    logger.log_event(event)
    events = logger.get_events()
    assert len(events) == 1
    assert events[0].event_type == "command"
    assert events[0].asset_id == "alpha"
    assert events[0].domain == DomainType.SURFACE
    assert events[0].data["action"] == "patrol"


def test_log_command(logger):
    """Log a FleetCommand via convenience method."""
    cmd = FleetCommand(
        mission_type=MissionType.PATROL,
        assets=[
            AssetCommand(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                waypoints=[Waypoint(x=500, y=500)],
                speed=5.0,
            ),
            AssetCommand(
                asset_id="eagle-1",
                domain=DomainType.AIR,
                waypoints=[Waypoint(x=300, y=300)],
                speed=15.0,
                altitude=120.0,
                drone_pattern=DronePattern.ORBIT,
            ),
        ],
        formation=FormationType.ECHELON,
        raw_text="patrol harbor with eagle overhead",
    )
    logger.log_command(cmd)

    events = logger.get_events(event_type="command")
    assert len(events) == 1
    assert events[0].data["mission_type"] == "patrol"
    assert len(events[0].data["assets"]) == 2


def test_log_state(logger):
    """Log a FleetState snapshot."""
    state = FleetState(
        timestamp=time.time(),
        assets=[
            AssetState(
                asset_id="alpha",
                domain=DomainType.SURFACE,
                x=100.0, y=200.0,
                heading=45.0, speed=5.0,
                status=AssetStatus.EXECUTING,
            ),
        ],
        active_mission=MissionType.PATROL,
        formation=FormationType.ECHELON,
    )
    logger.log_state(state)

    events = logger.get_events(event_type="state")
    assert len(events) == 1
    assert events[0].data["assets"][0]["asset_id"] == "alpha"


def test_log_gps_change(logger):
    """Log a GPS mode change."""
    logger.log_gps_change(GpsMode.DEGRADED, noise_meters=30.0)

    events = logger.get_events(event_type="gps_change")
    assert len(events) == 1
    assert events[0].data["mode"] == "degraded"
    assert events[0].data["noise_meters"] == 30.0


def test_filter_by_event_type(logger):
    """Filter events by type."""
    logger.log_gps_change(GpsMode.DEGRADED)
    logger.log_event(MissionEvent(
        timestamp=time.time(),
        event_type="command",
        data={"test": True},
    ))
    logger.log_gps_change(GpsMode.FULL)

    gps = logger.get_events(event_type="gps_change")
    cmds = logger.get_events(event_type="command")
    assert len(gps) == 2
    assert len(cmds) == 1


def test_filter_by_asset_id(logger):
    """Filter events by asset_id."""
    logger.log_event(MissionEvent(
        timestamp=time.time(),
        event_type="decision",
        asset_id="alpha",
        domain=DomainType.SURFACE,
        data={"info": "avoid"},
    ))
    logger.log_event(MissionEvent(
        timestamp=time.time(),
        event_type="decision",
        asset_id="bravo",
        domain=DomainType.SURFACE,
        data={"info": "proceed"},
    ))

    alpha_events = logger.get_events(asset_id="alpha")
    assert len(alpha_events) == 1
    assert alpha_events[0].asset_id == "alpha"


def test_filter_by_time_range(logger):
    """Filter events by time range."""
    t1 = 1000.0
    t2 = 2000.0
    t3 = 3000.0

    for ts in [t1, t2, t3]:
        logger.log_event(MissionEvent(
            timestamp=ts,
            event_type="state",
            data={"ts": ts},
        ))

    events = logger.get_events(start_time=1500.0, end_time=2500.0)
    assert len(events) == 1
    assert events[0].timestamp == 2000.0


def test_count_events(logger):
    """Count events by type."""
    logger.log_gps_change(GpsMode.DEGRADED)
    logger.log_gps_change(GpsMode.FULL)
    logger.log_event(MissionEvent(
        timestamp=time.time(),
        event_type="command",
        data={},
    ))

    assert logger.count_events() == 3
    assert logger.count_events("gps_change") == 2
    assert logger.count_events("command") == 1


def test_limit(logger):
    """Limit the number of returned events."""
    for i in range(10):
        logger.log_event(MissionEvent(
            timestamp=float(i),
            event_type="state",
            data={"i": i},
        ))

    events = logger.get_events(limit=3)
    assert len(events) == 3
    assert events[0].data["i"] == 0  # chronological order


# ------------------------------------------------------------------
# MissionReplay tests
# ------------------------------------------------------------------

def test_replay_get_all(tmp_db):
    """Replay returns all events."""
    lg = MissionLogger(db_path=tmp_db)
    lg.log_gps_change(GpsMode.DEGRADED)
    lg.log_event(MissionEvent(timestamp=time.time(), event_type="command", data={"x": 1}))
    lg.close()

    replay = MissionReplay(db_path=tmp_db)
    events = replay.get_all_events()
    assert len(events) == 2
    replay.close()


def test_replay_iter_states(tmp_db):
    """Replay yields FleetState objects from state events."""
    lg = MissionLogger(db_path=tmp_db)
    for i in range(3):
        state = FleetState(
            timestamp=1000.0 + i,
            assets=[
                AssetState(
                    asset_id="alpha",
                    domain=DomainType.SURFACE,
                    x=float(i * 100), y=0.0,
                    heading=0.0, speed=5.0,
                    status=AssetStatus.EXECUTING,
                ),
            ],
        )
        lg.log_state(state)
    lg.close()

    replay = MissionReplay(db_path=tmp_db)
    states = list(replay.iter_states())
    assert len(states) == 3
    assert states[0].timestamp == 1000.0
    assert states[2].assets[0].x == 200.0
    replay.close()


def test_replay_get_commands(tmp_db):
    """Replay filters command events."""
    lg = MissionLogger(db_path=tmp_db)
    lg.log_event(MissionEvent(timestamp=time.time(), event_type="command", data={"a": 1}))
    lg.log_event(MissionEvent(timestamp=time.time(), event_type="state", data={"b": 2}))
    lg.close()

    replay = MissionReplay(db_path=tmp_db)
    cmds = replay.get_commands()
    assert len(cmds) == 1
    assert cmds[0].event_type == "command"
    replay.close()


def test_replay_get_gps_changes(tmp_db):
    """Replay filters GPS change events."""
    lg = MissionLogger(db_path=tmp_db)
    lg.log_gps_change(GpsMode.DEGRADED)
    lg.log_gps_change(GpsMode.FULL)
    lg.log_event(MissionEvent(timestamp=time.time(), event_type="command", data={}))
    lg.close()

    replay = MissionReplay(db_path=tmp_db)
    gps = replay.get_gps_changes()
    assert len(gps) == 2
    replay.close()


def test_replay_summary(tmp_db):
    """Replay summary gives correct counts and duration."""
    lg = MissionLogger(db_path=tmp_db)
    lg.log_event(MissionEvent(timestamp=100.0, event_type="command", data={}))
    lg.log_event(MissionEvent(timestamp=105.0, event_type="state", data={"assets": [], "timestamp": 105.0}))
    lg.log_event(MissionEvent(timestamp=110.0, event_type="gps_change", data={"mode": "degraded"}))
    lg.close()

    replay = MissionReplay(db_path=tmp_db)
    s = replay.summary()
    assert s["total_events"] == 3
    assert s["commands"] == 1
    assert s["state_snapshots"] == 1
    assert s["gps_changes"] == 1
    assert s["duration_seconds"] == 10.0
    replay.close()


def test_replay_events_in_range(tmp_db):
    """Replay time-range filter works."""
    lg = MissionLogger(db_path=tmp_db)
    for ts in [100.0, 200.0, 300.0, 400.0]:
        lg.log_event(MissionEvent(timestamp=ts, event_type="state", data={"ts": ts}))
    lg.close()

    replay = MissionReplay(db_path=tmp_db)
    events = replay.get_events_in_range(150.0, 350.0)
    assert len(events) == 2
    assert events[0].timestamp == 200.0
    assert events[1].timestamp == 300.0
    replay.close()
