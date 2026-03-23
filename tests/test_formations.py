"""Tests for formations.py and task_allocator.py — Step 8."""
import math
import pytest
from src.schemas import Waypoint, FormationType, MissionType, DomainType, DronePattern
from src.fleet.formations import compute_formation_offsets, apply_formation
from src.fleet.task_allocator import get_mission_roles, allocate_assets


VESSEL_IDS = ["alpha", "bravo", "charlie"]


# ===== formations.py tests =====

class TestComputeFormationOffsets:
    def test_leader_always_at_origin(self):
        for fmt in FormationType:
            offsets = compute_formation_offsets(VESSEL_IDS, fmt, spacing=200.0)
            assert offsets["alpha"].x == 0.0
            assert offsets["alpha"].y == 0.0

    def test_echelon_diagonal(self):
        offsets = compute_formation_offsets(VESSEL_IDS, FormationType.ECHELON, spacing=200.0)
        # bravo: right 200, behind 200
        assert offsets["bravo"].x == 200.0
        assert offsets["bravo"].y == -200.0
        # charlie: right 400, behind 400
        assert offsets["charlie"].x == 400.0
        assert offsets["charlie"].y == -400.0

    def test_line_abreast_side_by_side(self):
        offsets = compute_formation_offsets(VESSEL_IDS, FormationType.LINE_ABREAST, spacing=200.0)
        assert offsets["bravo"].x == 200.0
        assert offsets["bravo"].y == 0.0
        assert offsets["charlie"].x == 400.0
        assert offsets["charlie"].y == 0.0

    def test_column_single_file(self):
        offsets = compute_formation_offsets(VESSEL_IDS, FormationType.COLUMN, spacing=200.0)
        assert offsets["bravo"].x == 0.0
        assert offsets["bravo"].y == -200.0
        assert offsets["charlie"].x == 0.0
        assert offsets["charlie"].y == -400.0

    def test_spread_wider_than_line(self):
        line = compute_formation_offsets(VESSEL_IDS, FormationType.LINE_ABREAST, spacing=200.0)
        spread = compute_formation_offsets(VESSEL_IDS, FormationType.SPREAD, spacing=200.0)
        assert spread["bravo"].x > line["bravo"].x

    def test_independent_all_at_origin(self):
        offsets = compute_formation_offsets(VESSEL_IDS, FormationType.INDEPENDENT, spacing=200.0)
        for vid in VESSEL_IDS:
            assert offsets[vid].x == 0.0
            assert offsets[vid].y == 0.0


class TestApplyFormation:
    def test_heading_north_echelon(self):
        positions = apply_formation(
            leader_x=1000.0, leader_y=2000.0, heading_deg=0.0,
            vessel_ids=VESSEL_IDS, formation=FormationType.ECHELON, spacing=200.0,
        )
        # Leader at exact position
        assert positions["alpha"].x == pytest.approx(1000.0, abs=0.1)
        assert positions["alpha"].y == pytest.approx(2000.0, abs=0.1)
        # Heading north (0 deg): body-right = world +x, body-behind = world -y
        assert positions["bravo"].x == pytest.approx(1200.0, abs=0.1)
        assert positions["bravo"].y == pytest.approx(1800.0, abs=0.1)

    def test_heading_east_column(self):
        positions = apply_formation(
            leader_x=0.0, leader_y=0.0, heading_deg=90.0,
            vessel_ids=VESSEL_IDS, formation=FormationType.COLUMN, spacing=100.0,
        )
        # Heading east (90 deg): body-behind = world -x direction
        assert positions["alpha"].x == pytest.approx(0.0, abs=0.1)
        assert positions["bravo"].x == pytest.approx(-100.0, abs=0.1)
        assert positions["charlie"].x == pytest.approx(-200.0, abs=0.1)

    def test_three_vessels_echelon_maintain_spacing(self):
        """Key test from build spec: 3 vessels in echelon maintain spacing."""
        positions = apply_formation(
            leader_x=500.0, leader_y=500.0, heading_deg=45.0,
            vessel_ids=VESSEL_IDS, formation=FormationType.ECHELON, spacing=200.0,
        )
        # All three have distinct positions
        coords = [(p.x, p.y) for p in positions.values()]
        assert len(set(coords)) == 3

        # Spacing between adjacent vessels is consistent
        d01 = math.sqrt((coords[1][0] - coords[0][0])**2 +
                        (coords[1][1] - coords[0][1])**2)
        d12 = math.sqrt((coords[2][0] - coords[1][0])**2 +
                        (coords[2][1] - coords[1][1])**2)
        assert d01 == pytest.approx(d12, abs=1.0)


# ===== task_allocator.py tests =====

FLEET_ASSETS = [
    {"asset_id": "alpha", "domain": DomainType.SURFACE},
    {"asset_id": "bravo", "domain": DomainType.SURFACE},
    {"asset_id": "charlie", "domain": DomainType.SURFACE},
    {"asset_id": "eagle-1", "domain": DomainType.AIR},
]


class TestGetMissionRoles:
    def test_all_mission_types_have_roles(self):
        for mt in MissionType:
            roles = get_mission_roles(mt)
            assert "surface_behavior" in roles
            assert "air_pattern" in roles
            assert "air_altitude" in roles

    def test_patrol_uses_echelon(self):
        roles = get_mission_roles(MissionType.PATROL)
        assert roles["surface_formation"] == FormationType.ECHELON

    def test_search_uses_sweep(self):
        roles = get_mission_roles(MissionType.SEARCH)
        assert roles["air_pattern"] == DronePattern.SWEEP


class TestAllocateAssets:
    def test_allocates_all_assets(self):
        assignments = allocate_assets(MissionType.PATROL, FLEET_ASSETS)
        assert len(assignments) == 4
        assert "alpha" in assignments
        assert "eagle-1" in assignments

    def test_surface_gets_no_drone_pattern(self):
        assignments = allocate_assets(MissionType.PATROL, FLEET_ASSETS)
        assert assignments["alpha"]["drone_pattern"] is None
        assert assignments["alpha"]["altitude"] is None

    def test_air_gets_drone_pattern(self):
        assignments = allocate_assets(MissionType.PATROL, FLEET_ASSETS)
        assert assignments["eagle-1"]["drone_pattern"] == DronePattern.ORBIT
        assert assignments["eagle-1"]["altitude"] == 120.0

    def test_search_assigns_sweep_to_drone(self):
        assignments = allocate_assets(MissionType.SEARCH, FLEET_ASSETS)
        assert assignments["eagle-1"]["drone_pattern"] == DronePattern.SWEEP
        assert assignments["eagle-1"]["altitude"] == 80.0

    def test_aerial_recon_surface_independent(self):
        assignments = allocate_assets(MissionType.AERIAL_RECON, FLEET_ASSETS)
        assert assignments["alpha"]["formation"] == FormationType.INDEPENDENT
