"""
Phase 2 — bulk historical downloader (resumable, rate-limited, dry-runnable).

Usage (from repo root, credentials in .env):

    # See the full request plan and budget WITHOUT touching the network:
    PYTHONPATH=src:. python -m research.history.downloader --dry-run

    # Real run, quarterly snapshots + Indian primary histories:
    PYTHONPATH=src:. python -m research.history.downloader

    # Annual fallback cadence (plan Recommendation 2 degraded mode):
    PYTHONPATH=src:. python -m research.history.downloader --cadence annual

    # Re-run after interruption: already-complete snapshots are skipped
    # automatically via the snapshot_meta ledger.

Design notes:
  * Snapshots are fetched oldest-first so the riskiest data (2019 depth) is
    confirmed early — aligned with plan Recommendation 2.
  * Primary histories are chunked per calendar year, one request-chain per
    chunk covering ALL primary NORAD IDs at once (never per-object loops).
  * Budget arithmetic (printed in --dry-run): ~31 quarterly snapshots x ~1-6
    paginated requests each, plus ~8 primary-year chunks — comfortably inside
    300/hr when paced by the limiter; wall-clock cost is dominated by payload
    size, so budget DAYS for the full pull, not hours.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from research.assets.registry import load_assets
from research.history.snapshots import STUDY_START, snapshot_plan
from research.history.store import (
    completed_snapshots,
    init_history_db,
    store_primary_history,
    store_snapshot,
)

logger = logging.getLogger("research.history.downloader")

DEFAULT_DB = Path("data/gp_history.db")


def primary_norad_ids() -> list[int]:
    """Every registry asset, regardless of status — the historical pull wants
    decayed/retired objects too (they were primaries at earlier epochs)."""
    return sorted(a.norad_id for a in load_assets())


def plan_primary_chunks(start_year: int, end_year: int) -> list[tuple[str, str]]:
    return [
        (f"{y}-01-01", f"{y + 1}-01-01") for y in range(start_year, end_year + 1)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the request plan; no network, no writes")
    parser.add_argument("--cadence", choices=["quarterly", "annual"],
                        default="quarterly")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--skip-primaries", action="store_true")
    parser.add_argument("--skip-snapshots", action="store_true")
    parser.add_argument("--only", nargs="*", default=None,
                        help="restrict to specific snapshot labels, e.g. 2019Q1 2019Q2")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    snapshots = snapshot_plan(cadence=args.cadence)
    if args.only:
        snapshots = [s for s in snapshots if s.label in set(args.only)]
    ids = primary_norad_ids()
    chunks = plan_primary_chunks(STUDY_START.year, date.today().year)

    print(f"Plan: {len(snapshots)} snapshots ({args.cadence}), "
          f"{len(ids)} primary objects, {len(chunks)} primary-history year-chunks")

    if args.dry_run:
        print("\n--- DRY RUN: request plan ---")
        if not args.skip_snapshots:
            for s in snapshots:
                print(f"  gp_history  epoch={s.spacetrack_epoch_range:23s} "
                      f"mean_motion>11 ecc<0.25  -> snapshot {s.label}")
        if not args.skip_primaries:
            for start, end in chunks:
                print(f"  gp_history  epoch={start}--{end}  "
                      f"norad_cat_id=<{len(ids)} primary IDs>")
        n_req_min = len(snapshots) + len(chunks)
        print(f"\nMinimum request count: {n_req_min} "
              f"(more with pagination; limiter caps at 20/min, 250/hr)")
        print("No network calls made. Remove --dry-run to execute.")
        return 0

    # Real run — construct the credentialed client only now.
    from research.history.client import GPHistoryClient

    client = GPHistoryClient()
    init_history_db(args.db)

    if not args.skip_snapshots:
        done = completed_snapshots(args.db)
        todo = [s for s in snapshots if s.label not in done]
        print(f"Snapshots: {len(done)} already complete, {len(todo)} to fetch")
        for s in todo:  # oldest first: confirm 2019 depth early
            records = client.fetch_snapshot(s)
            n = store_snapshot(args.db, s, records)
            print(f"  {s.label}: stored {n} objects")

    if not args.skip_primaries:
        for start, end in chunks:
            records = client.fetch_object_history(ids, start, end)
            n = store_primary_history(args.db, records)
            print(f"  primaries {start[:4]}: stored {n} elsets")

    print(f"Done. Database: {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
