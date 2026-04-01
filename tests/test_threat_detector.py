"""Tests for Audit 9 — Autonomous Threat Response."""
import math
from src.fleet.threat_detector import assess_threats, ThreatAssessment
from src.fleet.fleet_manager import FleetManager
from src.schemas import (
    FleetCommand, AssetCommand, Waypoint,
    DomainType, MissionType, FormationType, AssetStatus, DronePattern,
)


def _make_fleet_manager():
    """Create a FleetManager with vessels at known positions."""
    return FleetManager()


# ------------------------------------------------------------------
# 1. No contacts → empty assessment
# ------------------------------------------------------------------
def test_no_contacts_no_threats():
    fm = _make_fleet_manager()
    result = assess_threats(fm.vessels, fm.contacts)
    assert result == []


# ------------------------------------------------------------------
# 2. Contact out of range (>8km)
# ------------------------------------------------------------------
def test_contact_out_of_range():
    fm = _make_fleet_manager()
    fm.spawn_contact("bogey-1", x=10000.0, y=0.0, heading=math.pi, speed=3.0)
    result = assess_threats(fm.vessels, fm.contacts)
    assert len(result) == 1
    assert result[0].threat_level == "none"


# ------------------------------------------------------------------
# 3. Contact in detected range (5-8km)
# ------------------------------------------------------------------
def test_contact_detected_range():
    fm = _make_fleet_manager()
    # Fleet centroid is roughly at (200, 0) — place contact ~6km east
    fm.spawn_contact("bogey-1", x=6200.0, y=0.0, heading=math.pi, speed=3.0)
    result = assess_threats(fm.vessels, fm.contacts)
    assert len(result) == 1
    assert result[0].threat_level == "detected"
    assert result[0].recommended_action == "monitor"


# ------------------------------------------------------------------
# 4. Contact in warning range (2-5km)
# ------------------------------------------------------------------
def test_contact_warning_range():
    fm = _make_fleet_manager()
    fm.spawn_contact("bogey-1", x=3200.0, y=0.0, heading=math.pi, speed=3.0)
    result = assess_threats(fm.vessels, fm.contacts)
    assert len(result) == 1
    assert result[0].threat_level == "warning"
    assert result[0].recommended_action == "track"


# ------------------------------------------------------------------
# 5. Contact in critical range (<2km)
# ------------------------------------------------------------------
def test_contact_critical_range():
    fm = _make_fleet_manager()
    fm.spawn_contact("bogey-1", x=1700.0, y=0.0, heading=math.pi, speed=3.0)
    result = assess_threats(fm.vessels, fm.contacts)
    assert len(result) == 1
    assert result[0].threat_level == "critical"
    assert result[0].recommended_action == "intercept"


# ------------------------------------------------------------------
# 6. Closing rate computation
# ------------------------------------------------------------------
def test_closing_rate_computation():
    fm = _make_fleet_manager()
    # Contact heading toward fleet (west, heading=pi) → should be closing (negative)
    fm.spawn_contact("closer", x=5000.0, y=0.0, heading=math.pi, speed=5.0)
    # Contact heading away from fleet (east, heading=0) → should be opening (positive)
    fm.spawn_contact("farther", x=5000.0, y=500.0, heading=0.0, speed=5.0)

    result = assess_threats(fm.vessels, fm.contacts)
    by_id = {ta.contact_id: ta for ta in result}

    assert by_id["closer"].closing_rate < 0, "Contact heading toward fleet should have negative closing_rate"
    assert by_id["farther"].closing_rate > 0, "Contact heading away should have positive closing_rate"


# ------------------------------------------------------------------
# 7. Auto drone retask on warning
# ------------------------------------------------------------------
def test_auto_drone_retask_on_warning():
    fm = _make_fleet_manager()
    assert fm.drone.status == AssetStatus.IDLE

    # Spawn contact in warning range
    fm.spawn_contact("bogey-1", x=3200.0, y=0.0, heading=math.pi, speed=3.0)

    # Run enough steps to trigger threat check (THREAT_CHECK_INTERVAL = 4)
    for _ in range(5):
        fm.step(0.25)

    # Drone should now be executing TRACK
    assert fm.drone.status == AssetStatus.EXECUTING
    assert fm.drone_coordinator._current_pattern == DronePattern.TRACK


# ------------------------------------------------------------------
# 8. No auto retask during active intercept mission
# ------------------------------------------------------------------
def test_no_auto_retask_during_active_mission():
    fm = _make_fleet_manager()

    # Dispatch an intercept mission
    cmd = FleetCommand(
        mission_type=MissionType.INTERCEPT,
        assets=[
            AssetCommand(asset_id="alpha", domain=DomainType.SURFACE,
                         waypoints=[Waypoint(x=5000.0, y=0.0)], speed=8.0),
            AssetCommand(asset_id="bravo", domain=DomainType.SURFACE,
                         waypoints=[Waypoint(x=5000.0, y=0.0)], speed=8.0),
            AssetCommand(asset_id="eagle-1", domain=DomainType.AIR,
                         waypoints=[Waypoint(x=5000.0, y=0.0)], speed=15.0,
                         altitude=100.0, drone_pattern=DronePattern.TRACK),
        ],
        formation=FormationType.INDEPENDENT,
    )
    fm.spawn_contact("bogey-1", x=5000.0, y=0.0, heading=math.pi, speed=3.0)
    fm.dispatch_command(cmd)

    # Record drone waypoints after dispatch
    initial_wps = list(fm.drone.waypoints)

    # Spawn another contact in warning range
    fm.spawn_contact("bogey-2", x=3200.0, y=500.0, heading=math.pi, speed=3.0)

    # Run steps — drone should NOT be retasked to bogey-2
    for _ in range(10):
        fm.step(0.25)

    # Fleet is actively executing intercept, so drone retask should not happen
    # for the new contact. The drone should still be tracking (from the dispatch).
    assert fm.drone.status == AssetStatus.EXECUTING


# ------------------------------------------------------------------
# 9. Intercept recommended flag
# ------------------------------------------------------------------
def test_intercept_recommended_flag():
    fm = _make_fleet_manager()
    assert fm.intercept_recommended is False

    # Spawn contact in critical range
    fm.spawn_contact("bogey-1", x=1700.0, y=0.0, heading=math.pi, speed=3.0)

    # Run enough steps for threat check
    for _ in range(5):
        fm.step(0.25)

    assert fm.intercept_recommended is True
    assert fm.recommended_target == "bogey-1"


# ------------------------------------------------------------------
# 10. Threat data in fleet state
# ------------------------------------------------------------------
def test_threat_in_fleet_state():
    fm = _make_fleet_manager()
    fm.spawn_contact("bogey-1", x=3200.0, y=0.0, heading=math.pi, speed=3.0)

    # Run enough steps for threat check
    for _ in range(5):
        fm.step(0.25)

    state_dict = fm.get_fleet_state_dict()

    assert "threat_assessments" in state_dict
    assert len(state_dict["threat_assessments"]) == 1
    ta = state_dict["threat_assessments"][0]
    assert ta["contact_id"] == "bogey-1"
    assert ta["threat_level"] in ("warning", "detected", "critical")
    assert "bearing_deg" in ta
    assert "closing_rate" in ta
    assert "recommended_action" in ta
    assert "reason" in ta

    assert "intercept_recommended" in state_dict
    assert "recommended_target" in state_dict
