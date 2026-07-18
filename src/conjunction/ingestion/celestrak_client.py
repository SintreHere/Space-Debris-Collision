"""
CelesTrak ingestion client — no-auth fallback data source.

Used when Space-Track credentials aren't set up yet, or as a quick sanity
check. Fetches the "active" satellite group and filters locally to the
target altitude band, same approach as the Space-Track client.
"""

from __future__ import annotations

import logging

import httpx

from conjunction.ingestion.altitude import in_altitude_band
from conjunction.ingestion.spacetrack_client import _parse_tle_block  # reuse parser

logger = logging.getLogger(__name__)

CELESTRAK_ACTIVE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"


def fetch_tles_in_altitude_band(
    band_min_km: float,
    band_max_km: float,
    limit: int | None = None,
    timeout_s: float = 30.0,
) -> list:
    """Fetch active-satellite TLEs from CelesTrak and filter by altitude band."""
    with httpx.Client(timeout=timeout_s) as client:
        response = client.get(CELESTRAK_ACTIVE_URL)
        response.raise_for_status()
        raw_text = response.text

    records = _parse_tle_block(raw_text, source="celestrak")
    filtered = [
        r
        for r in records
        if in_altitude_band(r.mean_motion, r.eccentricity, band_min_km, band_max_km)
    ]

    logger.info(
        "CelesTrak: fetched %d objects, %d in altitude band [%.0f, %.0f] km",
        len(records),
        len(filtered),
        band_min_km,
        band_max_km,
    )

    return filtered[:limit] if limit else filtered
