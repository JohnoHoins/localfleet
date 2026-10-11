"""Shared test setup: keep the test suite out of the real mission log.

src.api.server builds a module-level app (and its MissionLogger) at import
time, so the log location is redirected here at module level, before any
test module imports the server, and again per test for create_app() calls.
"""
import atexit
import os
import shutil
import tempfile

import pytest

_SESSION_LOG_DIR = tempfile.mkdtemp(prefix="localfleet-test-logs-")
os.environ["LOCALFLEET_LOG_DB"] = os.path.join(_SESSION_LOG_DIR, "mission_log.db")
atexit.register(shutil.rmtree, _SESSION_LOG_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_mission_log(tmp_path, monkeypatch):
    """Every test gets its own default mission log database."""
    monkeypatch.setenv("LOCALFLEET_LOG_DB", str(tmp_path / "mission_log.db"))
