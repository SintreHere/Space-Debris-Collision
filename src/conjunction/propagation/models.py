"""Data shapes returned by the propagator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass
class PropagatedState:
    """Single object, single point in time."""

    time: datetime
    position_km: np.ndarray  # shape (3,), TEME frame
    velocity_km_s: np.ndarray  # shape (3,), TEME frame
    error_code: int  # 0 == success; see sgp4 docs for nonzero meanings


@dataclass
class PropagationWindow:
    """Single object, propagated over a grid of times."""

    times: list[datetime]
    positions_km: np.ndarray  # shape (n_times, 3)
    velocities_km_s: np.ndarray  # shape (n_times, 3)
    error_codes: np.ndarray  # shape (n_times,)


@dataclass
class MultiObjectPropagationWindow:
    """Multiple objects, propagated over the same grid of times — this is the
    shape Phase 3 (conjunction detection) consumes directly."""

    norad_ids: list[int]
    times: list[datetime]
    positions_km: np.ndarray  # shape (n_objects, n_times, 3)
    velocities_km_s: np.ndarray  # shape (n_objects, n_times, 3)
    error_codes: np.ndarray  # shape (n_objects, n_times)
