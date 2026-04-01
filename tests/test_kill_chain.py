"""Tests for cross-domain kill chain — drone sensor + kill chain state machine."""
import math
import pytest

from src.schemas import (
    Contact, DomainType, DronePattern, MissionType, Waypoint,
    AssetStatus, FleetCommand, AssetCommand,
)
from src.fleet.drone_sensor import (
    drone_detect_contacts, TargetingData, DRONE_SENSOR_RANGE, DRONE_SENSOR_FOV,
)
from src.fleet.fleet_manager import FleetManager


# ------------------------------------------------------------------ #
# Drone sensor tests
# ------------------------------------------------------------------ #

class TestDroneSensor:
    def test_detect_contact_in_range(self):
        """Contact within range and FOV is detected."""
        contacts = {
            "tgt-1": Contact(contact_id="tgt-1", x=1000.0, y=0.0,
                             heading=math.pi, speed=5.0, domain=DomainType.SURFACE),
        }
        results = drone_detect_contacts(0.0, 0.0, 0.0, contacts)
        assert len(results) == 1
        assert results[0].contact_id == "tgt-1"
        assert results[0].range_m == pytest.approx(1000.0, abs=1.0)

    def test_detect_contact_out_of_range(self):
        """Contact beyond sensor range is not detected."""
        contacts = {
            "tgt-far": Contact(contact_id="tgt-far", x=5000.0, y=0.0,
                               heading=0.0, speed=5.0, domain=DomainType.SURFACE),
        }
        results = drone_detect_contacts(0.0, 0.0, 0.0, contacts)
        assert len(results) == 0

    def test_detect_contact_outside_fov(self):
        """Contact behind drone (outside FOV) is not detected."""
        contacts = {
            "tgt-behind": Contact(contact_id="tgt-behind", x=-1000.0, y=0.0,
                                  heading=0.0, speed=5.0, domain=DomainType.SURFACE),
        }
        # Drone heading east (0 rad), contact is directly behind
        results = drone_detect_contacts(0.0, 0.0, 0.0, contacts)
        assert len(results) == 0

    def test_confidence_degrades_with_range(self):
        """Confidence should be lower for distant contacts."""
        contacts = {
            "near": Contact(contact_id="near", x=100.0, y=0.0,
                            heading=0.0, speed=0.0, domain=DomainType.SURFACE),
            "far": Contact(contact_id="far", x=2500.0, y=0.0,
                           heading=0.0, speed=0.0, domain=DomainType.SURFACE),
        }
        results = drone_detect_contacts(0.0, 0.0, 0.0, contacts)
        near_r = next(r for r in results if r.contact_id == "near")
        far_r = next(r for r in results if r.contact_id == "far")
        assert near_r.confidence > far_r.confidence

    def test_contact_at_fov_edge(self):
        """Contact at the edge of FOV should still be detected."""
        half_fov = math.radians(DRONE_SENSOR_FOV / 2)
        # Place contact just inside FOV edge
        angle = half_fov - 0.01
        contacts = {
            "edge": Contact(contact_id="edge",
                            x=1000.0 * math.cos(angle),
                            y=1000.0 * math.sin(angle),
                            heading=0.0, speed=0.0, domain=DomainType.SURFACE),
        }
        results = drone_detect_contacts(0.0, 0.0, 0.0, contacts)
        assert len(results) == 1


# ------------------------------------------------------------------ #
# Kill chain state machine tests
# ------------------------------------------------------------------ #

class TestKillChain:
    def _make_fm_with_contact(self, cx=3000.0, cy=0.0, speed=5.0):
        """Helper: FleetManager with a contact spawned."""
        fm = FleetManager()
        fm.spawn_contact("bogey-1", x=cx, y=cy,
                         heading=math.pi, speed=speed)
        return fm

    def test_detect_phase_on_threat(self):
        """Kill chain enters DETECT when threat detector finds a real threat."""
        fm = self._make_fm_with_contact()
        # Run threat check to populate threat_assessments
        fm._check_threats()
        fm._advance_kill_chain()
        assert fm.kill_chain_phase == "DETECT"
        assert fm.kill_chain_target == "bogey-1"

    def test_track_phase_on_drone_track(self):
        """Kill chain advances to TRACK when drone is in TRACK pattern."""
        fm = self._make_fm_with_contact()
        fm._check_threats()
        fm._advance_kill_chain()  # -> DETECT
        assert fm.kill_chain_phase == "DETECT"

        # Set drone to TRACK pattern
        fm.drone_coordinator.assign_pattern(
            DronePattern.TRACK,
            [Waypoint(x=3000.0, y=0.0)],
            altitude=100.0,
        )
        fm._advance_kill_chain()  # -> TRACK
        assert fm.kill_chain_phase == "TRACK"

    def test_lock_phase_on_targeting_lock(self):
        """Kill chain advances to LOCK when targeting data is locked."""
        fm = self._make_fm_with_contact(cx=500.0, cy=0.0)
        # Position drone near the contact facing it
        fm.drone.x = 200.0
        fm.drone.y = 0.0
        fm.drone.heading = 90.0  # nautical east = math 0

        fm._check_threats()
        fm._advance_kill_chain()  # -> DETECT

        fm.drone_coordinator.assign_pattern(
            DronePattern.TRACK,
            [Waypoint(x=500.0, y=0.0)],
            altitude=100.0,
        )
        fm._advance_kill_chain()  # -> TRACK

        # Drone is in TRACK, contact is in range+FOV -> locked=True
        fm._advance_kill_chain()  # -> LOCK
        assert fm.kill_chain_phase == "LOCK"
        assert fm.targeting_data is not None
        assert fm.targeting_data.locked is True

    def test_engage_phase_on_intercept_mission(self):
        """Kill chain advances to ENGAGE when intercept mission is active."""
        fm = self._make_fm_with_contact(cx=500.0, cy=0.0)
        fm.drone.x = 200.0
        fm.drone.y = 0.0
        fm.drone.heading = 90.0

        fm._check_threats()
        fm._advance_kill_chain()  # -> DETECT
        fm.drone_coordinator.assign_pattern(
            DronePattern.TRACK, [Waypoint(x=500.0, y=0.0)], altitude=100.0)
        fm._advance_kill_chain()  # -> TRACK
        fm._advance_kill_chain()  # -> LOCK

        fm.active_mission = MissionType.INTERCEPT
        fm._advance_kill_chain()  # -> ENGAGE
        assert fm.kill_chain_phase == "ENGAGE"

    def test_full_progression_to_converge(self):
        """Kill chain progresses through all phases to CONVERGE."""
        fm = self._make_fm_with_contact(cx=500.0, cy=0.0, speed=0.0)
        fm.drone.x = 200.0
        fm.drone.y = 0.0
        fm.drone.heading = 90.0

        fm._check_threats()
        fm._advance_kill_chain()  # DETECT
        assert fm.kill_chain_phase == "DETECT"

        fm.drone_coordinator.assign_pattern(
            DronePattern.TRACK, [Waypoint(x=500.0, y=0.0)], altitude=100.0)
        fm._advance_kill_chain()  # TRACK
        assert fm.kill_chain_phase == "TRACK"

        fm._advance_kill_chain()  # LOCK
        assert fm.kill_chain_phase == "LOCK"

        fm.active_mission = MissionType.INTERCEPT
        fm._advance_kill_chain()  # ENGAGE
        assert fm.kill_chain_phase == "ENGAGE"

        # Move a vessel within 1000m of the contact
        fm.vessels["alpha"]["state"][0] = 500.0
        fm.vessels["alpha"]["state"][1] = 0.0
        fm._advance_kill_chain()  # CONVERGE
        assert fm.kill_chain_phase == "CONVERGE"

    def test_reset_on_contact_removal(self):
        """Kill chain resets when all contacts are removed."""
        fm = self._make_fm_with_contact()
        fm._check_threats()
        fm._advance_kill_chain()
        assert fm.kill_chain_phase == "DETECT"

        fm.remove_contact("bogey-1")
        fm._advance_kill_chain()
        assert fm.kill_chain_phase is None
        assert fm.kill_chain_target is None
        assert fm.targeting_data is None

    def test_targeting_data_in_fleet_state(self):
        """Fleet state dict includes kill chain phase and targeting data."""
        fm = self._make_fm_with_contact(cx=500.0, cy=0.0)
        fm.drone.x = 200.0
        fm.drone.y = 0.0
        fm.drone.heading = 90.0

        fm._check_threats()
        fm._advance_kill_chain()
        fm.drone_coordinator.assign_pattern(
            DronePattern.TRACK, [Waypoint(x=500.0, y=0.0)], altitude=100.0)
        fm._advance_kill_chain()
        fm._advance_kill_chain()  # LOCK with targeting data

        data = fm.get_fleet_state_dict()
        assert data["autonomy"]["kill_chain_phase"] == "LOCK"
        assert "targeting" in data["autonomy"]
        assert data["autonomy"]["targeting"]["locked"] is True
        assert data["autonomy"]["targeting"]["contact_id"] == "bogey-1"
