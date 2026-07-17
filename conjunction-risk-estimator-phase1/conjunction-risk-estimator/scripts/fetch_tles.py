#!/usr/bin/env python
"""
Phase 1 deliverable: fetch current TLEs for a defined altitude band and
cache them locally.

Usage:
    python scripts/fetch_tles.py --min-alt 700 --max-alt 900
    python scripts/fetch_tles.py --min-alt 700 --max-alt 900 --use-celestrak
    python scripts/fetch_tles.py --min-alt 700 --max-alt 900 --limit 50
"""

from __future__ import annotations

import argparse
import logging
import sys

from conjunction.ingestion.service import ingest_altitude_band

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and cache TLEs in an altitude band")
    parser.add_argument("--min-alt", type=float, default=700.0, help="Band minimum, km")
    parser.add_argument("--max-alt", type=float, default=900.0, help="Band maximum, km")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of objects")
    parser.add_argument(
        "--use-celestrak",
        action="store_true",
        help="Skip Space-Track and go straight to the no-auth CelesTrak fallback",
    )
    args = parser.parse_args()

    records = ingest_altitude_band(
        band_min_km=args.min_alt,
        band_max_km=args.max_alt,
        limit=args.limit,
        prefer_celestrak=args.use_celestrak,
    )

    print(f"\nFetched {len(records)} objects in [{args.min_alt}, {args.max_alt}] km band:\n")
    for r in records[:20]:
        print(
            f"  {r.norad_id:>6}  {r.name:<25}  "
            f"perigee={r.perigee_altitude_km:6.1f} km  apogee={r.apogee_altitude_km:6.1f} km  "
            f"source={r.source}"
        )
    if len(records) > 20:
        print(f"  ... and {len(records) - 20} more (see data/tle_cache.db)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
