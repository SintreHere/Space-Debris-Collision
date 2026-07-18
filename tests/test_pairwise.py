from datetime import datetime, timedelta, timezone

import numpy as np

from conjunction.propagation.catalog import CatalogObject
from conjunction.propagation.models import MultiObjectPropagationWindow
from conjunction.risk.pairwise import (
    ConjunctionEvent,
    find_altitude_overlap_pairs,
    find_conjunctions,
)


def _obj(norad_id: int, perigee: float, apogee: float) -> CatalogObject:
    return CatalogObject(
        norad_id=norad_id,
        name=f"OBJ-{norad_id}",
        line1="",
        line2="",
        perigee_altitude_km=perigee,
        apogee_altitude_km=apogee,
    )


def test_overlap_pairs_basic():
    objs = [
        _obj(1, 700, 800),
        _obj(2, 750, 850),  # overlaps 1
        _obj(3, 900, 1000),  # overlaps nobody
    ]
    assert find_altitude_overlap_pairs(objs) == [(1, 2)]


def test_overlap_pairs_touching_endpoints_count_as_overlap():
    objs = [_obj(1, 700, 800), _obj(2, 800, 900)]
    assert find_altitude_overlap_pairs(objs) == [(1, 2)]


def test_overlap_pairs_containment():
    objs = [_obj(1, 700, 1000), _obj(2, 800, 850)]
    assert find_altitude_overlap_pairs(objs) == [(1, 2)]


def _window(positions, velocities, error_codes):
    n_objects, n_times = error_codes.shape
    t0 = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
    return MultiObjectPropagationWindow(
        norad_ids=list(range(1, n_objects + 1)),
        times=[t0 + timedelta(seconds=30 * i) for i in range(n_times)],
        positions_km=positions,
        velocities_km_s=velocities,
        error_codes=error_codes,
    )


def test_find_conjunctions_locates_tca_and_miss_distance():
    # Two objects on the x-axis closing to 2 km apart at t index 1, then separating.
    pos = np.zeros((2, 3, 3))
    pos[0, :, 0] = [7000.0, 7000.0, 7000.0]
    pos[1, :, 0] = [7010.0, 7002.0, 7010.0]
    vel = np.zeros((2, 3, 3))
    vel[1, :, 1] = 1.0  # relative velocity 1 km/s at every step
    err = np.zeros((2, 3), dtype=int)

    window = _window(pos, vel, err)
    events = find_conjunctions(window, [(1, 2)], {1: "A", 2: "B"}, threshold_km=5.0)

    assert len(events) == 1
    e = events[0]
    assert isinstance(e, ConjunctionEvent)
    assert e.norad_id_a == 1 and e.norad_id_b == 2
    assert abs(e.miss_distance_km - 2.0) < 1e-9
    assert e.tca == window.times[1]
    assert abs(e.relative_velocity_km_s - 1.0) < 1e-9


def test_find_conjunctions_respects_threshold():
    pos = np.zeros((2, 2, 3))
    pos[1, :, 0] = 100.0  # constant 100 km separation
    vel = np.zeros((2, 2, 3))
    err = np.zeros((2, 2), dtype=int)

    events = find_conjunctions(_window(pos, vel, err), [(1, 2)], {}, threshold_km=25.0)
    assert events == []


def test_find_conjunctions_masks_error_code_timesteps():
    # Garbage near-zero separation at t=0, but object 2's propagation failed
    # there — the mask must exclude it, leaving the t=1 separation as the min.
    pos = np.zeros((2, 2, 3))
    pos[0, :, 0] = [7000.0, 7000.0]
    pos[1, :, 0] = [7000.001, 7010.0]
    vel = np.zeros((2, 2, 3))
    err = np.zeros((2, 2), dtype=int)
    err[1, 0] = 6  # decayed

    events = find_conjunctions(_window(pos, vel, err), [(1, 2)], {}, threshold_km=25.0)
    assert len(events) == 1
    assert abs(events[0].miss_distance_km - 10.0) < 1e-9


def test_find_conjunctions_drops_pairs_missing_from_window():
    pos = np.zeros((2, 2, 3))
    vel = np.zeros((2, 2, 3))
    err = np.zeros((2, 2), dtype=int)
    # norad_id 99 never propagated (bad TLE) — pair must be silently dropped.
    events = find_conjunctions(_window(pos, vel, err), [(1, 99)], {}, threshold_km=25.0)
    assert events == []
