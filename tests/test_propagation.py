"""Validate the propagator against a real, known TLE (ISS)."""

from datetime import datetime, timedelta, timezone

import numpy as np

from conjunction.propagation.sgp4_propagator import (
    load_satellite,
    propagate_at,
    propagate_many,
    propagate_window,
)

EARTH_RADIUS_KM = 6378.137

# Real ISS TLE, epoch 2024-001.5 (Jan 1 2024, 12:00 UTC)
ISS_LINE1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9994"
ISS_LINE2 = "2 25544  51.6416 339.7760 0007976  13.6742  63.6467 15.50142606421917"


def _altitude_km(position_km: np.ndarray) -> float:
    return float(np.linalg.norm(position_km) - EARTH_RADIUS_KM)


def test_propagate_at_epoch_gives_sane_iss_altitude():
    satrec = load_satellite(ISS_LINE1, ISS_LINE2)
    epoch = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    state = propagate_at(satrec, epoch)

    assert state.error_code == 0
    alt = _altitude_km(state.position_km)
    assert 380 < alt < 430  # ISS orbits roughly 400-420 km


def test_propagate_window_stays_in_sane_altitude_range_over_72h():
    satrec = load_satellite(ISS_LINE1, ISS_LINE2)
    start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=72)

    window = propagate_window(satrec, start, end, step_seconds=300)  # 5-min steps

    assert all(code == 0 for code in window.error_codes)
    altitudes = [_altitude_km(p) for p in window.positions_km]
    # ISS altitude decays slowly due to drag but won't move hundreds of km
    # in 72 hours — a wide sanity band, not a precision check.
    assert min(altitudes) > 350
    assert max(altitudes) < 450


def test_propagate_many_matches_single_object_propagation():
    """The vectorized multi-object path should give the same answer as the
    single-object path, for the same satellite."""
    satrec = load_satellite(ISS_LINE1, ISS_LINE2)
    start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)

    single = propagate_window(satrec, start, end, step_seconds=600)

    satrec2 = load_satellite(ISS_LINE1, ISS_LINE2)
    multi = propagate_many({25544: satrec2}, start, end, step_seconds=600)

    assert multi.positions_km.shape == (1, len(single.times), 3)
    np.testing.assert_allclose(multi.positions_km[0], single.positions_km, rtol=1e-9)
