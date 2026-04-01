"""Tests for decision audit trail — Audit 12."""
import math
import time
import pytest
from unittest.mock import patch

from src.fleet.decision_log import DecisionLog, DecisionEntry
from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, MissionType, DomainType, Waypoint,
    FormationType, AssetStatus, DronePattern,
)


# ------------------------------------------------------------------
# DecisionLog unit tests
# ------------------------------------------------------------------

class TestDecisionLog:
    def test_log_stores_entry(self):
        dl = DecisionLog()
        e = dl.log("test_type", "did something", "because reasons")
        assert e.decision_type == "test_type"
        assert e.action_taken == "did something"
        assert e.rationale == "because reasons"
        assert len(dl.get_recent()) == 1

    def test_ring_buffer_evicts(self):
        dl = DecisionLog(max_entries=5)
        for i in range(10):
            dl.log("t", f"action_{i}", "r")
        recent = dl.get_recent(20)
        assert len(recent) == 5
        assert recent[0].action_taken == "action_5"
        assert recent[-1].action_taken == "action_9"

    def test_get_by_type(self):
        dl = DecisionLog()
        dl.log("alpha", "a1", "r")
        dl.log("beta", "b1", "r")
        dl.log("alpha", "a2", "r")
        alphas = dl.get_by_type("alpha")
        assert len(alphas) == 2
        assert all(e.decision_type == "alpha" for e in alphas)

    def test_to_dicts(self):
        dl = DecisionLog()
        dl.log("t", "action", "rationale", confidence=0.8,
               assets=["alpha"], alternatives=["wait"])
        dicts = dl.to_dicts(n=5)
        assert len(dicts) == 1
        d = dicts[0]
        assert d["type"] == "t"
        assert d["action"] == "action"
        assert d["rationale"] == "rationale"
        assert d["confidence"] == 0.8
        assert d["assets"] == ["alpha"]
        assert d["alternatives"] == ["wait"]
        assert d["parent_id"] is None
        assert "id" in d

    def test_parent_chain(self):
        dl = DecisionLog()
        parent = dl.log("parent_type", "parent_action", "r")
        child = dl.log("child_type", "child_action", "r",
                       parent_id=parent.id)
        assert child.parent_id == parent.id
        assert child.parent_id.startswith("parent_type_")

    def test_entry_id_format(self):
        dl = DecisionLog()
        e = dl.log("threat_assessment", "action", "r")
        assert e.id.startswith("threat_assessment_")


# ------------------------------------------------------------------
# Fleet manager integration — decision logging at decision points
# ------------------------------------------------------------------

class TestFleetManagerDecisionLogging:
    def _make_fm_with_contact(self, cx=5000.0, cy=0.0, heading=math.pi,
                               speed=5.0, contact_id="bogey-1"):
        fm = FleetManager()
        fm.spawn_contact(contact_id, cx, cy, heading, speed)
        return fm

    def test_intercept_logs_solution(self):
        fm = self._make_fm_with_contact()
        cmd = FleetCommand(
            mission_type=MissionType.INTERCEPT,
            assets=[
                AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                             waypoints=[Waypoint(x=5000, y=0)], speed=8.0),
                AssetCommand(asset_id="bravo", domain=DomainType.SURFACE,
                             waypoints=[Waypoint(x=5000, y=0)], speed=8.0),
                AssetCommand(asset_id="charlie", domain=DomainType.SURFACE,
                             waypoints=[Waypoint(x=5000, y=0)], speed=8.0),
            ],
            formation=FormationType.INDEPENDENT,
        )
        fm.dispatch_command(cmd)
        entries = fm.decision_log.get_by_type("intercept_solution")
        assert len(entries) == 1
        assert "bogey-1" in entries[0].rationale
        assert entries[0].confidence > 0

    def test_threat_assessment_logged(self):
        fm = self._make_fm_with_contact(cx=3000.0)
        # Run enough steps for threat check
        for _ in range(5):
            fm.step(0.25)
        entries = fm.decision_log.get_by_type("threat_assessment")
        assert len(entries) >= 1

    def test_auto_track_logged(self):
        fm = self._make_fm_with_contact(cx=3000.0)
        # Need to trigger auto-track: drone idle + threat warning/critical
        fm.drone.status = AssetStatus.IDLE
        for _ in range(5):
            fm.step(0.25)
        entries = fm.decision_log.get_by_type("auto_track")
        assert len(entries) >= 1
        assert "eagle-1" in entries[0].assets_involved

    def test_replan_logged(self):
        fm = self._make_fm_with_contact(cx=5000.0, speed=10.0)
        cmd = FleetCommand(
            mission_type=MissionType.INTERCEPT,
            assets=[
                AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                             waypoints=[Waypoint(x=5000, y=0)], speed=8.0),
            ],
            formation=FormationType.INDEPENDENT,
        )
        fm.dispatch_command(cmd)
        # Fast-forward contact far enough to trigger replan
        for c in fm.contacts.values():
            c.x -= 2000  # big shift
        fm._replan_counter = 39  # force replan on next step
        fm.step(0.25)
        entries = fm.decision_log.get_by_type("replan")
        assert len(entries) >= 1

    def test_fleet_state_includes_decisions(self):
        fm = FleetManager()
        fm.decision_log.log("test", "action", "rationale")
        data = fm.get_fleet_state_dict()
        assert "decisions" in data
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["type"] == "test"

    def test_decisions_api_endpoint(self):
        """Verify the decisions endpoint serialization matches expected format."""
        dl = DecisionLog()
        dl.log("intercept_solution", "Intercept: (100, 200)", "target moving",
               confidence=0.9, assets=["alpha", "bravo"])
        dl.log("threat_assessment", "bogey: WARNING 3000m", "closing fast",
               confidence=0.6)
        # Test get_recent
        recent = dl.get_recent(50)
        assert len(recent) == 2
        # Test type filter
        threats = dl.get_by_type("threat_assessment")
        assert len(threats) == 1
        assert threats[0].action_taken == "bogey: WARNING 3000m"
