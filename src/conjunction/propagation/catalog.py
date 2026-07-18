"""Bridges ingestion (cached TLEs) and propagation (SGP4). Phase 3's
conjunction detector consumes propagate_catalog()'s MultiObjectPropagationWindow
directly — it's already shaped (n_objects, n_times, 3) for vectorized
pairwise distance search."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from conjunction.config import settings
from conjunction.ingestion import storage
from conjunction.propagation.models import MultiObjectPropagationWindow
from conjunction.propagation.sgp4_propagator import load_satellite, propagate_many

logger = logging.getLogger(__name__)


@dataclass
class CatalogObject:
    norad_id: int
    name: str
    line1: str
    line2: str
    perigee_altitude_km: float
    apogee_altitude_km: float


def load_catalog(db_path: Path | None = None) -> list[CatalogObject]:
    """Load the most recent cached TLE per object."""
    db_path = db_path or settings.tle_db_path
    rows = storage.get_latest_tles(db_path)
    return [
        CatalogObject(
            norad_id=row["norad_id"],
            name=row["name"],
            line1=row["line1"],
            line2=row["line2"],
            perigee_altitude_km=row["perigee_altitude_km"],
            apogee_altitude_km=row["apogee_altitude_km"],
        )
        for row in rows
    ]


def propagate_catalog(
    catalog: list[CatalogObject], start: datetime, end: datetime, step_seconds: float
) -> MultiObjectPropagationWindow:
    """
    Propagate every object in the catalog over the same time grid, vectorized
    across objects and time steps in one call. Objects whose TLE fails to
    parse are skipped and logged, not raised — a single bad TLE shouldn't
    kill a batch run over thousands of objects.
    """
    satellites = {}
    skipped = 0

    for obj in catalog:
        try:
            satellites[obj.norad_id] = load_satellite(obj.line1, obj.line2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping NORAD %d (%s): %s", obj.norad_id, obj.name, exc)
            skipped += 1

    window = propagate_many(satellites, start, end, step_seconds)

    logger.info(
        "Propagated %d/%d objects over %d timesteps (%d skipped)",
        len(satellites),
        len(catalog),
        len(window.times),
        skipped,
    )
    return window
