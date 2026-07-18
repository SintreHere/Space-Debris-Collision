"""High-level ingestion orchestration: try Space-Track first, fall back to
CelesTrak, then cache results locally."""

from __future__ import annotations

import logging

from conjunction.config import settings
from conjunction.ingestion import celestrak_client, spacetrack_client, storage
from conjunction.ingestion.models import TLERecord

logger = logging.getLogger(__name__)


def ingest_altitude_band(
    band_min_km: float,
    band_max_km: float,
    limit: int | None = None,
    prefer_celestrak: bool = False,
) -> list[TLERecord]:
    """
    Fetch and cache TLEs for objects whose orbit overlaps the given altitude
    band. Tries Space-Track first (better data quality, needs credentials),
    falls back to CelesTrak automatically if Space-Track fails or isn't
    configured.
    """
    records: list[TLERecord] = []

    if not prefer_celestrak:
        try:
            records = spacetrack_client.fetch_tles_in_altitude_band(
                band_min_km, band_max_km, limit=limit
            )
        except spacetrack_client.SpaceTrackIngestionError as exc:
            logger.warning("Space-Track unavailable (%s), falling back to CelesTrak", exc)

    if not records:
        records = celestrak_client.fetch_tles_in_altitude_band(
            band_min_km, band_max_km, limit=limit
        )

    storage.init_db(settings.tle_db_path)
    stored_count = storage.upsert_tles(settings.tle_db_path, records)
    logger.info("Cached %d TLE records to %s", stored_count, settings.tle_db_path)

    return records
