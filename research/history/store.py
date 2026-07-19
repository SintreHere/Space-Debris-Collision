"""
Phase 2 — epoch-indexed historical storage.

Extends the operational storage philosophy (SQLite now, interface stable so
the backend is swappable to Postgres/TimescaleDB per plan Recommendation 1)
with two additions the research pipeline needs:

  1. snapshot_label on every row — per-epoch screening runs select by label,
     never by fuzzy date math;
  2. a snapshot_meta ledger making multi-day downloads RESUMABLE: a snapshot
     is only marked 'complete' after all its rows are committed, so a crashed
     or rate-limit-interrupted run re-does at most one snapshot.

Parquet export is optional (pandas+pyarrow); the SQLite copy is canonical.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from research.history.models import GPRecord
from research.history.snapshots import Snapshot

PRIMARY_HISTORY_LABEL = "__primary_history__"  # non-snapshot rows (full primary elset history)

SCHEMA = """
CREATE TABLE IF NOT EXISTS gp_history (
    norad_id INTEGER NOT NULL,
    epoch TEXT NOT NULL,
    snapshot_label TEXT NOT NULL,
    object_name TEXT,
    object_type TEXT,
    country_code TEXT,
    intl_designator TEXT,
    mean_motion REAL NOT NULL,
    eccentricity REAL NOT NULL,
    inclination_deg REAL,
    raan_deg REAL,
    arg_pericenter_deg REAL,
    mean_anomaly_deg REAL,
    bstar REAL,
    perigee_altitude_km REAL NOT NULL,
    apogee_altitude_km REAL NOT NULL,
    tle_line1 TEXT,
    tle_line2 TEXT,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (norad_id, epoch, snapshot_label)
);
CREATE INDEX IF NOT EXISTS idx_gp_history_label ON gp_history(snapshot_label);
CREATE INDEX IF NOT EXISTS idx_gp_history_norad ON gp_history(norad_id);

CREATE TABLE IF NOT EXISTS snapshot_meta (
    snapshot_label TEXT PRIMARY KEY,
    target_date TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    status TEXT NOT NULL,            -- 'complete' | 'failed'
    n_objects INTEGER NOT NULL,
    completed_at TEXT NOT NULL
);
"""

_COLUMNS = (
    "norad_id", "epoch", "snapshot_label", "object_name", "object_type",
    "country_code", "intl_designator", "mean_motion", "eccentricity",
    "inclination_deg", "raan_deg", "arg_pericenter_deg", "mean_anomaly_deg",
    "bstar", "perigee_altitude_km", "apogee_altitude_km",
    "tle_line1", "tle_line2", "source", "fetched_at",
)


def init_history_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _row(r: GPRecord, label: str) -> tuple:
    return (
        r.norad_id, r.epoch.isoformat(), label, r.object_name, r.object_type,
        r.country_code, r.intl_designator, r.mean_motion, r.eccentricity,
        r.inclination_deg, r.raan_deg, r.arg_pericenter_deg, r.mean_anomaly_deg,
        r.bstar, r.perigee_altitude_km, r.apogee_altitude_km,
        r.tle_line1, r.tle_line2, r.source, r.fetched_at.isoformat(),
    )


def store_snapshot(db_path: Path, snapshot: Snapshot, records: list[GPRecord]) -> int:
    """Commit a snapshot's records and mark it complete, atomically."""
    placeholders = ",".join("?" for _ in _COLUMNS)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f"INSERT OR REPLACE INTO gp_history ({','.join(_COLUMNS)}) "
            f"VALUES ({placeholders})",
            [_row(r, snapshot.label) for r in records],
        )
        conn.execute(
            "INSERT OR REPLACE INTO snapshot_meta VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot.label,
                snapshot.target.isoformat(),
                snapshot.window_start.isoformat(),
                snapshot.window_end.isoformat(),
                "complete",
                len(records),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    return len(records)


def store_primary_history(db_path: Path, records: list[GPRecord]) -> int:
    placeholders = ",".join("?" for _ in _COLUMNS)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f"INSERT OR REPLACE INTO gp_history ({','.join(_COLUMNS)}) "
            f"VALUES ({placeholders})",
            [_row(r, PRIMARY_HISTORY_LABEL) for r in records],
        )
        conn.commit()
    return len(records)


def completed_snapshots(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT snapshot_label FROM snapshot_meta WHERE status = 'complete'"
        ).fetchall()
    return {r[0] for r in rows}


def load_snapshot(db_path: Path, label: str) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM gp_history WHERE snapshot_label = ? ORDER BY norad_id",
            (label,),
        ).fetchall()


def export_snapshot_parquet(db_path: Path, label: str, out_dir: Path) -> Path | None:
    """Optional parquet export; returns None (with a hint) if pandas/pyarrow
    are unavailable. SQLite remains the canonical store either way."""
    try:
        import pandas as pd
    except ImportError:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT * FROM gp_history WHERE snapshot_label = ?",
            conn,
            params=(label,),
        )
    out = out_dir / f"gp_{label}.parquet"
    df.to_parquet(out, index=False)
    return out
