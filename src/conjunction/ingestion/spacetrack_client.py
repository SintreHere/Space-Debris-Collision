"""
Space-Track.org ingestion client — primary TLE data source.

Uses the `gp` (General Perturbations) request class, which is Space-Track's
current recommended class for "latest elset per object" (it replaced the
older `tle_latest` class). We fetch a broad, unfiltered set of LEO-ish
objects (by mean motion, which is always populated) and then filter locally
to the exact altitude band using conjunction.ingestion.altitude — this is
more robust than depending on exact server-side predicate names, which have
changed over time on Space-Track.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from spacetrack import SpaceTrackClient

from conjunction.config import settings
from conjunction.ingestion.altitude import in_altitude_band
from conjunction.ingestion.models import TLERecord
from conjunction.ingestion.parsing import parse_eccentricity, parse_mean_motion

logger = logging.getLogger(__name__)


class SpaceTrackIngestionError(RuntimeError):
    pass


def fetch_tles_in_altitude_band(
    band_min_km: float,
    band_max_km: float,
    limit: int | None = None,
) -> list[TLERecord]:
    """
    Fetch current TLEs for on-orbit objects and return only those whose orbit
    overlaps [band_min_km, band_max_km]. Raises SpaceTrackIngestionError on
    auth or request failure so the caller can decide whether to fall back to
    CelesTrak.
    """
    if not settings.has_spacetrack_credentials():
        raise SpaceTrackIngestionError(
            "No Space-Track credentials found in environment "
            "(SPACETRACK_USERNAME / SPACETRACK_PASSWORD)."
        )

    try:
        st = SpaceTrackClient(
            identity=settings.spacetrack_username,
            password=settings.spacetrack_password,
        )

        # mean_motion range corresponding to roughly all of LEO (very wide net,
        # ~200km to ~2000km altitude); we narrow to the exact band ourselves
        # below using computed altitude, rather than trusting a tight
        # server-side mean_motion cutoff.
        raw_lines = st.generic_request(
            "gp",
            mean_motion=">11",
            eccentricity="<0.25",
            decay_date="null-val",
            orderby="norad_cat_id",
            format="tle",
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as our own error type
        raise SpaceTrackIngestionError(f"Space-Track request failed: {exc}") from exc

    records = _parse_tle_block(raw_lines, source="spacetrack")
    filtered = [
        r
        for r in records
        if in_altitude_band(r.mean_motion, r.eccentricity, band_min_km, band_max_km)
    ]

    logger.info(
        "Space-Track: fetched %d objects, %d in altitude band [%.0f, %.0f] km",
        len(records),
        len(filtered),
        band_min_km,
        band_max_km,
    )

    return filtered[:limit] if limit else filtered


def _parse_tle_block(raw_text: str, source: str) -> list[TLERecord]:
    """Parse a multi-satellite TLE text block (name line + line1 + line2, x N)."""
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    records: list[TLERecord] = []
    fetched_at = datetime.now(timezone.utc)

    i = 0
    while i < len(lines):
        # Name line is optional in some feeds — detect by line1 starting with "1 "
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            name = f"UNKNOWN-{lines[i][2:7].strip()}"
            line1, line2 = lines[i], lines[i + 1]
            i += 2
        elif i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name = lines[i].strip()
            line1, line2 = lines[i + 1], lines[i + 2]
            i += 3
        else:
            i += 1
            continue

        try:
            norad_id = int(line1[2:7].strip())
            mean_motion = parse_mean_motion(line2)
            eccentricity = parse_eccentricity(line2)
            epoch = _epoch_from_line1(line1)
            perigee_alt, apogee_alt = _altitudes(mean_motion, eccentricity)

            records.append(
                TLERecord(
                    norad_id=norad_id,
                    name=name,
                    line1=line1,
                    line2=line2,
                    epoch=epoch,
                    mean_motion=mean_motion,
                    eccentricity=eccentricity,
                    perigee_altitude_km=perigee_alt,
                    apogee_altitude_km=apogee_alt,
                    source=source,
                    fetched_at=fetched_at,
                )
            )
        except (ValueError, IndexError) as exc:
            logger.warning("Skipping malformed TLE near line %d: %s", i, exc)

    return records


def _altitudes(mean_motion: float, eccentricity: float) -> tuple[float, float]:
    from conjunction.ingestion.altitude import perigee_apogee_altitude_km

    return perigee_apogee_altitude_km(mean_motion, eccentricity)


def _epoch_from_line1(line1: str) -> datetime:
    """TLE epoch format: columns 19-32, YYDDD.DDDDDDDD (year + day-of-year fraction)."""
    epoch_str = line1[18:32].strip()
    year_2digit = int(epoch_str[:2])
    day_frac = float(epoch_str[2:])
    year = 2000 + year_2digit if year_2digit < 57 else 1900 + year_2digit

    from datetime import timedelta

    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_frac - 1)
