"""
GPS-Denied Degradation Engine.
Adds position noise and reduces update rate when GPS is degraded.
In DENIED mode, provides dead reckoning with accumulating drift.
"""
import math
import random
import time
from dataclasses import dataclass, field
from src.schemas import GpsMode


def degrade_position(x: float, y: float, noise_meters: float = 25.0
                     ) -> tuple[float, float, float]:
    """Add Gaussian noise to a position. Returns (noisy_x, noisy_y, accuracy)."""
    noisy_x = x + random.gauss(0, noise_meters)
    noisy_y = y + random.gauss(0, noise_meters)
    return noisy_x, noisy_y, noise_meters


_last_update: dict[str, float] = {}


def should_update(asset_id: str, update_rate_hz: float = 1.0) -> bool:
    """Rate-limit updates per asset. Returns True if enough time has passed."""
    now = time.time()
    interval = 1.0 / update_rate_hz
    last = _last_update.get(asset_id, 0.0)
    if now - last >= interval:
        _last_update[asset_id] = now
        return True
    return False


# ------------------------------------------------------------------
# Dead Reckoning — used when GPS is fully denied
# ------------------------------------------------------------------

@dataclass
class DeadReckoningState:
    """Per-vessel dead reckoning estimate."""
    estimated_x: float = 0.0
    estimated_y: float = 0.0
    drift_error: float = 0.0       # accumulated drift in meters
    time_denied: float = 0.0       # seconds since GPS was lost
    _drift_heading: float = field(default_factory=lambda: random.uniform(0, 2 * math.pi))


def dead_reckon_step(dr: DeadReckoningState, speed: float,
                     heading_rad: float, dt: float) -> None:
    """Advance dead reckoning estimate by one time step.

    Updates estimated position using speed & heading, then adds a small
    random-walk drift (~0.5% of distance traveled per step).
    """
    # Advance estimated position by integrated velocity
    dist = speed * dt
    dr.estimated_x += dist * math.cos(heading_rad)
    dr.estimated_y += dist * math.sin(heading_rad)

    # Random-walk drift: 0.5% of distance traveled, in a slowly-wandering direction
    drift_amount = 0.005 * dist
    dr._drift_heading += random.gauss(0, 0.1)  # slow wander
    dr.estimated_x += drift_amount * math.cos(dr._drift_heading)
    dr.estimated_y += drift_amount * math.sin(dr._drift_heading)
    dr.drift_error += drift_amount

    dr.time_denied += dt


def get_navigated_position(true_x: float, true_y: float,
                           dr: DeadReckoningState | None,
                           gps_mode: GpsMode,
                           noise_meters: float = 25.0,
                           ) -> tuple[float, float, float]:
    """Return the position the navigation system 'sees'.

    Returns (nav_x, nav_y, accuracy_meters).
    - FULL: true position, accuracy=1.0
    - DEGRADED: noisy true position
    - DENIED: dead reckoning estimate (dr must not be None)
    """
    if gps_mode == GpsMode.FULL:
        return true_x, true_y, 1.0
    elif gps_mode == GpsMode.DEGRADED:
        return degrade_position(true_x, true_y, noise_meters)
    else:  # DENIED
        assert dr is not None, "DeadReckoningState required for DENIED mode"
        return dr.estimated_x, dr.estimated_y, dr.drift_error
