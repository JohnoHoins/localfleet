"""Regression: running the test suite must not write into the operator's
mission log (data/logs/mission_log.db); see tests/conftest.py."""
import os

from src.api.server import create_app
from src.logging.mission_logger import MissionLogger

REPO_LOG_DIR = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "logs"))


def _in_repo_log_dir(path: str) -> bool:
    return os.path.realpath(path).startswith(REPO_LOG_DIR + os.sep)


def test_default_mission_logger_is_redirected():
    assert not _in_repo_log_dir(MissionLogger().db_path)


def test_create_app_default_logger_is_redirected():
    app = create_app()
    assert not _in_repo_log_dir(app.state.logger.db_path)


def test_module_level_app_logger_is_redirected():
    from src.api.server import app
    assert not _in_repo_log_dir(app.state.logger.db_path)
