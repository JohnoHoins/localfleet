"""
GPS-Denied Degradation Engine.
Adds position noise and reduces update rate when GPS is degraded.
Cosmetic — signals awareness of contested environments.
"""
import random
import time
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
