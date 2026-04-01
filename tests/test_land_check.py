"""Tests for src/navigation/land_check.py — land awareness module."""

import math
import numpy as np
import pytest

from src.navigation.land_check import (
    is_on_land,
    nearest_water_point,
    check_path_clear,
    land_repulsion_heading,
    latlng_to_meters,
    LAND_POLYGONS,
)


# ------------------------------------------------------------------
# Coordinate conversion
# ------------------------------------------------------------------

class TestCoordinateConversion:
    def test_origin_is_zero(self):
        x, y = latlng_to_meters(42.0, -70.0)
        assert x == 0.0
        assert y == 0.0

    def test_east_is_positive_x(self):
        x, _ = latlng_to_meters(42.0, -69.99)
        assert x > 0

    def test_north_is_positive_y(self):
        _, y = latlng_to_meters(42.01, -70.0)
        assert y > 0


# ------------------------------------------------------------------
# is_on_land — point-in-polygon
# ------------------------------------------------------------------

class TestIsOnLand:
    def test_origin_is_water(self):
        """Origin (42N, -70W) is ~30 km offshore — must be water."""
        assert is_on_land(0.0, 0.0) is False

    def test_deep_ocean_is_water(self):
        """A point far east of Cape Cod is ocean."""
        assert is_on_land(5000.0, 0.0) is False

    def test_cape_cod_interior_is_land(self):
        """A point inside the Cape Cod polygon is land."""
        # North Truro interior: 42.03N, -70.13W
        x, y = latlng_to_meters(42.03, -70.13)
        assert is_on_land(x, y) is True

    def test_provincetown_is_land(self):
        """Provincetown tip interior."""
        x, y = latlng_to_meters(42.05, -70.19)
        assert is_on_land(x, y) is True

    def test_nantucket_sound_is_water(self):
        """South of the Cape, in the sound."""
        x, y = latlng_to_meters(41.55, -70.2)
        assert is_on_land(x, y) is False


# ------------------------------------------------------------------
# check_path_clear
# ------------------------------------------------------------------

class TestCheckPathClear:
    def test_ocean_path_is_clear(self):
        """Path entirely in open ocean is clear."""
        assert check_path_clear(0, 0, 1000, 0) is True

    def test_path_through_cape_is_blocked(self):
        """Path from ocean to bay side crosses land."""
        # From origin (ocean) heading west through Truro
        x_land, y_land = latlng_to_meters(42.0, -70.15)
        assert check_path_clear(0, 0, x_land, y_land) is False

    def test_path_along_coast_may_be_clear(self):
        """Path parallel to coast in open water stays clear."""
        assert check_path_clear(0, 0, 0, 5000) is True


# ------------------------------------------------------------------
# nearest_water_point
# ------------------------------------------------------------------

class TestNearestWaterPoint:
    def test_water_point_unchanged(self):
        wx, wy = nearest_water_point(0.0, 0.0)
        assert wx == 0.0 and wy == 0.0

    def test_land_point_moved_to_water(self):
        """A point on land should be moved to water."""
        x, y = latlng_to_meters(42.03, -70.13)
        assert is_on_land(x, y)
        wx, wy = nearest_water_point(x, y)
        assert not is_on_land(wx, wy)


# ------------------------------------------------------------------
# land_repulsion_heading
# ------------------------------------------------------------------

class TestLandRepulsionHeading:
    def test_no_correction_in_open_ocean(self):
        """Heading east from origin — nothing but ocean ahead."""
        corr = land_repulsion_heading(0, 0, 0.0, look_ahead=100.0)
        assert corr == 0.0

    def test_correction_when_heading_toward_land(self):
        """Heading west from origin eventually hits Cape Cod — should get correction."""
        # Truro outer coast is at x=-2460m. Stand ~160m from coast.
        x, y = latlng_to_meters(42.0, -70.028)  # ~2296 m west
        psi = math.pi  # heading west (toward land)
        corr = land_repulsion_heading(x, y, psi, look_ahead=100.0)
        assert corr != 0.0, "Should steer away from approaching land"

    def test_correction_sign_turns_away(self):
        """Correction should turn the vessel away from land, not into it."""
        # Approaching coast from east (ocean side), ~160m from coast
        x, y = latlng_to_meters(42.0, -70.028)
        psi = math.pi  # heading due west
        corr = land_repulsion_heading(x, y, psi, look_ahead=100.0)
        # The corrected heading should point more toward water (east-ish)
        new_psi = psi + corr
        # Check that looking ahead on corrected heading is water
        fx = x + 100.0 * math.cos(new_psi)
        fy = y + 100.0 * math.sin(new_psi)
        assert not is_on_land(fx, fy), "Corrected heading should point to water"


# ------------------------------------------------------------------
# Integration: vessel heading toward land is redirected
# ------------------------------------------------------------------

class TestVesselLandRedirect:
    def test_vessel_heading_toward_land_is_redirected(self):
        """
        Simulate a vessel near the coast heading toward land.
        After several steps with land_repulsion_heading corrections,
        the vessel should NOT end up on land.
        """
        from src.dynamics.vessel_dynamics import vessel_dynamics
        from src.dynamics.controller import controller
        from src.dynamics.actuator_modeling import actuator_modeling
        from src.core.integration import integration

        SAT_AMP = 20
        dt = 0.25

        # Start ~200 m from Truro coast, heading due west (toward land)
        x, y = latlng_to_meters(42.0, -70.025)
        state = np.array([x, y, math.pi, 0.0, 0.0, 0.0])
        ui_psi1 = 0.0
        desired_speed = 5.0

        for _ in range(200):  # 50 seconds of simulation
            psi_desired = math.pi  # keep commanding "go west"

            # Land avoidance correction
            corr = land_repulsion_heading(state[0], state[1], psi_desired, look_ahead=75.0)
            psi_desired += corr

            heading_err = abs((psi_desired - state[2] + np.pi) % (2 * np.pi) - np.pi)
            speed_scale = max(0.3, 1.0 - 0.7 * heading_err / np.pi)
            effective_speed = desired_speed * speed_scale

            tau_c, v_c, ui_psi1 = controller(
                psi_desired, state[2], state[3],
                effective_speed, state[4], ui_psi1, dt,
            )
            tau_ac = actuator_modeling(tau_c, SAT_AMP)
            x_dot = vessel_dynamics(state, [tau_ac, v_c])
            state = integration(state, x_dot, dt)

        assert not is_on_land(state[0], state[1]), \
            f"Vessel ended up on land at ({state[0]:.0f}, {state[1]:.0f})"
