"""
SGP4 propagation — turns a TLE into position/velocity vectors at any past or
future time.

All outputs are in the TEME frame (True Equator, Mean Equinox), which is what
SGP4 natively produces. We deliberately do NOT convert to J2000/GCRF here:
every object is propagated in the same TEME frame, so relative distances
between objects (which is all Phase 3 needs) are already valid without a
frame conversion. Converting to another frame would only matter if we were
overlaying this with data from a different source that uses a different
frame — not the case here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from sgp4.api import Satrec, SatrecArray, jday

from conjunction.propagation.models import (
    MultiObjectPropagationWindow,
    PropagatedState,
    PropagationWindow,
)


def load_satellite(line1: str, line2: str) -> Satrec:
    """Parse a TLE into an sgp4 Satrec object, ready for propagation."""
    return Satrec.twoline2rv(line1, line2)


def _datetime_to_jd_fr(dt: datetime) -> tuple[float, float]:
    """Convert a datetime to the (julian_day, fraction_of_day) pair sgp4 expects."""
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    jd, fr = jday(
        dt_utc.year,
        dt_utc.month,
        dt_utc.day,
        dt_utc.hour,
        dt_utc.minute,
        dt_utc.second + dt_utc.microsecond / 1e6,
    )
    return jd, fr


def propagate_at(satrec: Satrec, dt: datetime) -> PropagatedState:
    """Position/velocity for a single object at a single instant."""
    jd, fr = _datetime_to_jd_fr(dt)
    error_code, position, velocity = satrec.sgp4(jd, fr)
    return PropagatedState(
        time=dt,
        position_km=np.array(position),
        velocity_km_s=np.array(velocity),
        error_code=error_code,
    )


def _build_time_grid(start: datetime, end: datetime, step_seconds: float) -> list[datetime]:
    n_steps = int((end - start).total_seconds() / step_seconds) + 1
    return [start + timedelta(seconds=i * step_seconds) for i in range(n_steps)]


def propagate_all_at(
    satellites: list[Satrec], dt: datetime
) -> tuple[np.ndarray, np.ndarray]:
    """Positions for MANY objects at a single instant, in one vectorized
    SatrecArray call — orders of magnitude faster than looping propagate_at
    when the catalog has tens of thousands of objects.

    Returns (positions_km (n, 3), error_codes (n,)).
    """
    jd, fr = _datetime_to_jd_fr(dt)
    satrec_array = SatrecArray(satellites)
    error_codes, positions, _velocities = satrec_array.sgp4(
        np.array([jd]), np.array([fr])
    )
    return positions[:, 0, :], error_codes[:, 0]


def propagate_window(
    satrec: Satrec, start: datetime, end: datetime, step_seconds: float
) -> PropagationWindow:
    """Position/velocity for a single object over a grid of times.

    Uses sgp4's vectorized array API (jd/fr arrays in, position/velocity
    arrays out) rather than looping in Python — this matters once we're doing
    it for every object over a 72-hour window at fine time steps.
    """
    times = _build_time_grid(start, end, step_seconds)
    jd_fr_pairs = [_datetime_to_jd_fr(t) for t in times]
    jds = np.array([p[0] for p in jd_fr_pairs])
    frs = np.array([p[1] for p in jd_fr_pairs])

    error_codes, positions, velocities = satrec.sgp4_array(jds, frs)

    return PropagationWindow(
        times=times,
        positions_km=positions,
        velocities_km_s=velocities,
        error_codes=error_codes,
    )


def propagate_many(
    satellites: dict[int, Satrec], start: datetime, end: datetime, step_seconds: float
) -> MultiObjectPropagationWindow:
    """Position/velocity for MANY objects over the same time grid, vectorized
    across both objects and time steps. This is what Phase 3 will call:
    given N objects, this returns an (N, T, 3) position array that pairwise
    minimum-distance search operates on directly.
    """
    times = _build_time_grid(start, end, step_seconds)
    jd_fr_pairs = [_datetime_to_jd_fr(t) for t in times]
    jds = np.array([p[0] for p in jd_fr_pairs])
    frs = np.array([p[1] for p in jd_fr_pairs])

    norad_ids = list(satellites.keys())
    satrec_array = SatrecArray([satellites[nid] for nid in norad_ids])

    # error_codes, positions, velocities each shaped (n_objects, n_times[, 3])
    # Note: SatrecArray exposes this as `.sgp4()`, not `.sgp4_array()` — the
    # "_array" naming only applies to the single-Satrec vectorized method.
    error_codes, positions, velocities = satrec_array.sgp4(jds, frs)

    return MultiObjectPropagationWindow(
        norad_ids=norad_ids,
        times=times,
        positions_km=positions,
        velocities_km_s=velocities,
        error_codes=error_codes,
    )
