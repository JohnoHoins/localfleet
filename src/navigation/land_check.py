"""
Land awareness module for LocalFleet.

Provides coastline polygon data and utility functions for land detection
in the local meters coordinate frame (origin at ORIGIN_LAT, ORIGIN_LNG).

Uses ray-casting for point-in-polygon tests — no external dependencies.
To add new regions (e.g. RI harbor), append polygons to LAND_POLYGONS.
"""

import math
import numpy as np
from typing import List, Tuple

# --- Coordinate origin (must match dashboard/FleetMap.jsx) ---
ORIGIN_LAT = 42.0
ORIGIN_LNG = -70.0
M_PER_DEG_LAT = 111_320
M_PER_DEG_LNG = 82_000  # approximate at 42°N

# ------------------------------------------------------------------
# Simplified Cape Cod coastline polygon (lat, lng), clockwise.
# Accuracy ~500 m — sufficient for sim demo.
# Outer coast (Atlantic side) then inner coast (bay side).
# ------------------------------------------------------------------
_CAPE_COD_LATLNG = [
    (41.74, -70.62),   # Canal south (Bourne)
    (41.67, -70.52),   # Falmouth
    (41.63, -70.30),   # Hyannis south coast
    (41.65, -70.00),   # Dennis / Brewster south
    (41.67, -69.95),   # Chatham south
    (41.70, -69.94),   # Chatham east
    (41.80, -69.96),   # Orleans / Eastham outer
    (41.88, -69.97),   # Eastham outer
    (41.93, -69.97),   # Wellfleet outer
    (42.00, -70.03),   # Truro outer
    (42.04, -70.08),   # North Truro
    (42.06, -70.17),   # Provincetown east
    (42.07, -70.21),   # Race Point
    (42.05, -70.25),   # Race Point west
    (42.03, -70.19),   # P-town inner harbor
    (41.98, -70.10),   # Truro inner (bay side)
    (41.92, -70.07),   # Wellfleet inner
    (41.85, -70.05),   # Eastham inner
    (41.77, -70.06),   # Orleans inner
    (41.73, -70.10),   # Brewster inner
    (41.73, -70.20),   # Dennis inner
    (41.73, -70.40),   # Barnstable inner
    (41.76, -70.55),   # Sandwich
    (41.77, -70.62),   # Canal north
]


# ------------------------------------------------------------------
# Coordinate helpers
# ------------------------------------------------------------------

def latlng_to_meters(lat: float, lng: float) -> Tuple[float, float]:
    """Convert lat/lng to local meters relative to ORIGIN."""
    x = (lng - ORIGIN_LNG) * M_PER_DEG_LNG
    y = (lat - ORIGIN_LAT) * M_PER_DEG_LAT
    return (x, y)


def _build_polygon_meters(latlng_points) -> np.ndarray:
    """Convert a lat/lng polygon to Nx2 numpy array in local meters."""
    return np.array([latlng_to_meters(lat, lng) for lat, lng in latlng_points])


# Pre-computed land polygons in local meters (list of Nx2 arrays).
# Append here for additional regions (RI harbor, etc.).
LAND_POLYGONS: List[np.ndarray] = [
    _build_polygon_meters(_CAPE_COD_LATLNG),
]


# ------------------------------------------------------------------
# Core geometry
# ------------------------------------------------------------------

def _point_in_polygon(x: float, y: float, polygon: np.ndarray) -> bool:
    """Ray-casting point-in-polygon test (Jordan curve theorem)."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _nearest_point_on_segment(px, py, ax, ay, bx, by):
    """Return the closest point on segment AB to point P, and the distance."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq == 0:
        return ax, ay, math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    cx, cy = ax + t * dx, ay + t * dy
    return cx, cy, math.hypot(px - cx, py - cy)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def is_on_land(x: float, y: float) -> bool:
    """Check if a point (local meters) is inside any land polygon."""
    for poly in LAND_POLYGONS:
        if _point_in_polygon(x, y, poly):
            return True
    return False


def nearest_water_point(x: float, y: float, margin: float = 10.0) -> Tuple[float, float]:
    """
    If (x, y) is on land, return the nearest point just outside the polygon edge.
    If already in water, returns (x, y) unchanged.

    Parameters:
        margin: meters to push past the coastline into water
    """
    if not is_on_land(x, y):
        return (x, y)

    best_dist = float('inf')
    best_cx, best_cy = x, y

    for poly in LAND_POLYGONS:
        n = len(poly)
        for i in range(n):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % n]
            cx, cy, dist = _nearest_point_on_segment(x, y, ax, ay, bx, by)
            if dist < best_dist:
                best_dist = dist
                best_cx, best_cy = cx, cy

    # Push from the interior point through the edge point and a bit beyond
    dx = best_cx - x
    dy = best_cy - y
    d = math.hypot(dx, dy)
    if d > 0:
        best_cx += margin * dx / d
        best_cy += margin * dy / d

    return (best_cx, best_cy)


def check_path_clear(x1: float, y1: float, x2: float, y2: float,
                     steps: int = 20) -> bool:
    """Check if a straight-line path crosses land (sampled at *steps* points)."""
    for i in range(steps + 1):
        t = i / steps
        if is_on_land(x1 + t * (x2 - x1), y1 + t * (y2 - y1)):
            return False
    return True


def land_repulsion_heading(x: float, y: float, psi: float,
                           look_ahead: float = 50.0) -> float:
    """
    Compute a heading correction (radians) to steer away from land.

    Checks look-ahead points at 1x and 2x *look_ahead* distance.
    If any would be on land, sweeps left/right to find the nearest
    clear direction and returns a partial correction toward it.

    Returns 0.0 if the path ahead is clear.
    """
    for dist in (look_ahead, look_ahead * 2.0):
        fx = x + dist * math.cos(psi)
        fy = y + dist * math.sin(psi)
        if is_on_land(fx, fy):
            # Sweep outward from current heading to find clear water
            for angle in (0.3, 0.6, 1.0, 1.5, 2.0, 2.5, math.pi):
                # Try starboard (CW in math convention = negative)
                if not is_on_land(x + dist * math.cos(psi - angle),
                                  y + dist * math.sin(psi - angle)):
                    return -angle * 0.5

                # Try port (CCW = positive)
                if not is_on_land(x + dist * math.cos(psi + angle),
                                  y + dist * math.sin(psi + angle)):
                    return angle * 0.5

            # Completely boxed in — hard turn
            return math.pi * 0.5

    return 0.0
