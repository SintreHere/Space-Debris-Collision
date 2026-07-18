"""
Phase 3b — true pairwise conjunction detection: minimum separation between
every candidate pair of catalog objects over a propagation window, not just
user-vs-catalog.

Two stages, standard conjunction-screening practice:

1. Coarse filter: a sweep line over each object's [perigee, apogee] altitude
   interval discards pairs whose orbits can never come near each other
   (non-overlapping altitude bands), in O(n log n + k) rather than O(n^2).
2. Fine search: for surviving pairs, chunked vectorized numpy over the
   already-propagated (n_objects, n_times, 3) position grid finds each
   pair's minimum separation and time of closest approach (TCA). Chunking
   bounds peak memory regardless of total pair count.

Timesteps where either object's SGP4 error_code != 0 are masked out of the
minimum — a failed propagation step can contain garbage positions that would
otherwise corrupt the argmin.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from conjunction.propagation.catalog import CatalogObject
from conjunction.propagation.models import MultiObjectPropagationWindow
from conjunction.risk.proximity import YELLOW_KM

# 2000 pairs/chunk keeps the transient (k, T, 3) diff arrays ~35MB at a
# 721-step window — sized for small containers (Railway), not workstations.
DEFAULT_CHUNK_SIZE = 2000

_START, _END = 0, 1  # event kinds; START sorts before END at equal altitude


@dataclass
class ConjunctionEvent:
    norad_id_a: int
    name_a: str
    norad_id_b: int
    name_b: str
    tca: datetime
    miss_distance_km: float
    relative_velocity_km_s: float


def find_altitude_overlap_pairs(objects: Iterable[CatalogObject]) -> list[tuple[int, int]]:
    """Sweep line over [perigee, apogee] altitude intervals. Returns
    (norad_id_a, norad_id_b) with a < b for every pair whose altitude bands
    overlap — inclusive of touching endpoints, matching in_altitude_band's
    <=/>= semantics in ingestion/altitude.py."""
    events = []
    for obj in objects:
        events.append((obj.perigee_altitude_km, _START, obj.norad_id))
        events.append((obj.apogee_altitude_km, _END, obj.norad_id))
    events.sort()

    active: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _alt, kind, norad_id in events:
        if kind == _START:
            for other in active:
                pairs.append((min(norad_id, other), max(norad_id, other)))
            active.add(norad_id)
        else:
            active.discard(norad_id)
    return pairs


def find_conjunctions(
    window: MultiObjectPropagationWindow,
    candidate_pairs: Sequence[tuple[int, int]],
    names_by_id: dict[int, str],
    threshold_km: float = YELLOW_KM,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[ConjunctionEvent]:
    """Chunked vectorized minimum-distance search over candidate pairs.

    Pairs referencing a norad_id absent from window.norad_ids are dropped
    (propagate_catalog skips objects whose TLE fails to parse). Only pairs
    whose minimum separation is below threshold_km are returned.
    """
    id_to_idx = {nid: i for i, nid in enumerate(window.norad_ids)}
    pairs = [(a, b) for a, b in candidate_pairs if a in id_to_idx and b in id_to_idx]

    events: list[ConjunctionEvent] = []
    for chunk_start in range(0, len(pairs), chunk_size):
        chunk = pairs[chunk_start : chunk_start + chunk_size]
        idx_a = np.array([id_to_idx[a] for a, _ in chunk])
        idx_b = np.array([id_to_idx[b] for _, b in chunk])

        pos_a = window.positions_km[idx_a]  # (k, T, 3)
        pos_b = window.positions_km[idx_b]
        dist = np.linalg.norm(pos_a - pos_b, axis=2)  # (k, T)

        valid = (window.error_codes[idx_a] == 0) & (window.error_codes[idx_b] == 0)
        dist = np.where(valid, dist, np.inf)

        min_dist = dist.min(axis=1)
        tca_idx = dist.argmin(axis=1)

        for i in np.where(min_dist < threshold_km)[0]:
            a, b = chunk[i]
            t_idx = int(tca_idx[i])
            vel_a = window.velocities_km_s[idx_a[i], t_idx]
            vel_b = window.velocities_km_s[idx_b[i], t_idx]
            events.append(
                ConjunctionEvent(
                    norad_id_a=a,
                    name_a=names_by_id.get(a, str(a)),
                    norad_id_b=b,
                    name_b=names_by_id.get(b, str(b)),
                    tca=window.times[t_idx],
                    miss_distance_km=float(min_dist[i]),
                    relative_velocity_km_s=float(np.linalg.norm(vel_a - vel_b)),
                )
            )
    return events


def screen_catalog(
    catalog: list[CatalogObject],
    window: MultiObjectPropagationWindow,
    threshold_km: float = YELLOW_KM,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[ConjunctionEvent]:
    """Full two-stage screen: altitude-overlap filter, then minimum-distance
    search on the survivors."""
    pairs = find_altitude_overlap_pairs(catalog)
    names_by_id = {o.norad_id: o.name for o in catalog}
    return find_conjunctions(window, pairs, names_by_id, threshold_km, chunk_size)
