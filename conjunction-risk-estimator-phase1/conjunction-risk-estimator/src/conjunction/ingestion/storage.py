"""SQLite cache for TLE records. Deliberately lightweight for the core-first
phase — this gets swapped for Postgres/TimescaleDB when we build the SaaS
layer, but the interface (init_db / upsert_tles / get_latest_tles) stays the
same so callers don't need to change."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from conjunction.ingestion.models import TLERecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS tle_cache (
    norad_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    line1 TEXT NOT NULL,
    line2 TEXT NOT NULL,
    epoch TEXT NOT NULL,
    mean_motion REAL NOT NULL,
    eccentricity REAL NOT NULL,
    perigee_altitude_km REAL NOT NULL,
    apogee_altitude_km REAL NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (norad_id, epoch)
);
CREATE INDEX IF NOT EXISTS idx_tle_cache_norad ON tle_cache(norad_id);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_tles(db_path: Path, records: list[TLERecord]) -> int:
    """Insert or replace TLE records (keyed by norad_id + epoch, so re-fetching
    the same elset is a no-op, but a new epoch for the same object adds a row —
    this is what lets you later show TLE history / trend analysis)."""
    if not records:
        return 0

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO tle_cache
                (norad_id, name, line1, line2, epoch, mean_motion, eccentricity,
                 perigee_altitude_km, apogee_altitude_km, source, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.norad_id,
                    r.name,
                    r.line1,
                    r.line2,
                    r.epoch.isoformat(),
                    r.mean_motion,
                    r.eccentricity,
                    r.perigee_altitude_km,
                    r.apogee_altitude_km,
                    r.source,
                    r.fetched_at.isoformat(),
                )
                for r in records
            ],
        )
        conn.commit()
    return len(records)


def get_latest_tles(db_path: Path) -> list[sqlite3.Row]:
    """Returns the single most recent TLE per object (by epoch)."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT t1.* FROM tle_cache t1
            INNER JOIN (
                SELECT norad_id, MAX(epoch) AS max_epoch
                FROM tle_cache GROUP BY norad_id
            ) t2 ON t1.norad_id = t2.norad_id AND t1.epoch = t2.max_epoch
            ORDER BY t1.norad_id
            """
        )
        return cursor.fetchall()
