"""Tests for GPS-denied degradation engine."""
from src.utils.gps_denied import degrade_position, should_update


def test_degrade_adds_noise():
    results = [degrade_position(100.0, 200.0, noise_meters=25.0) for _ in range(100)]
    xs = [r[0] for r in results]
    # Not all identical — noise is being applied
    assert len(set(xs)) > 1
    # Accuracy field matches noise param
    assert all(r[2] == 25.0 for r in results)
    print("Noise OK")


def test_degrade_zero_noise():
    nx, ny, acc = degrade_position(50.0, 50.0, noise_meters=0.0)
    assert nx == 50.0 and ny == 50.0
    print("Zero noise OK")


def test_should_update_rate_limit():
    # First call always passes
    assert should_update("test-asset", update_rate_hz=1.0) is True
    # Immediate second call should be rate-limited
    assert should_update("test-asset", update_rate_hz=1.0) is False
    print("Rate limit OK")


if __name__ == "__main__":
    test_degrade_adds_noise()
    test_degrade_zero_noise()
    test_should_update_rate_limit()
    print("\nAll GPS-denied tests passed!")
