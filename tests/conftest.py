"""Shared test setup: keep tests out of the operator's real mission log.

MissionLogger() without a db_path writes to data/logs/mission_log.db, and
src/api/server.py builds a module-level app (with such a logger) on import.
Point the default log directory at a temporary one for the whole session,
and at a fresh per-test directory for each test.
"""
import shutil
import tempfile

import pytest

import src.logging.mission_logger as mission_logger

_session_log_dir = None


def pytest_configure(config):
    global _session_log_dir
    _session_log_dir = tempfile.mkdtemp(prefix="localfleet-test-logs-")
    mission_logger.DEFAULT_DB_DIR = _session_log_dir


def pytest_unconfigure(config):
    if _session_log_dir:
        shutil.rmtree(_session_log_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_mission_log(tmp_path, monkeypatch):
    monkeypatch.setattr(mission_logger, "DEFAULT_DB_DIR", str(tmp_path))
