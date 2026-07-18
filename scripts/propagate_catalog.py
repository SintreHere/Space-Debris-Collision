#!/usr/bin/env python
"""
Phase 2 deliverable: propagate every cached object over a forward time
window and report position vectors, using SGP4's vectorized multi-object API.

Usage:
    python scripts/propagate_catalog.py
    python scripts/propagate_catalog.py --hours 72 --step-seconds 300
    python scripts/propagate_catalog.py --norad-id 25544   # single object, verbose
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

from conjunction.propagation.catalog import load_catalog, propagate_catalog
from conjunction.propagation.sgp4_propagator import load_satellite, propagate_window

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

EARTH_RADIUS_KM = 6378.137


def main() -> int:
    parser = argparse.ArgumentParser(description="Propagate cached catalog with SGP4")
    parser.add_argument("--hours", type=float, default=72.0, help="Propagation window, hours")
    parser.add_argument("--step-seconds", type=float, default=300.0, help="Time step, seconds")
    parser.add_argument(
        "--norad-id", type=int, default=None, help="Propagate a single object with detail"
    )
    args = parser.parse_args()

    catalog = load_catalog()
    if not catalog:
        print("No cached objects found — run scripts/fetch_tles.py first.")
        return 1

    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=args.hours)

    if args.norad_id is not None:
        obj = next((o for o in catalog if o.norad_id == args.norad_id), None)
        if obj is None:
            print(f"NORAD ID {args.norad_id} not found in cached catalog.")
            return 1

        satrec = load_satellite(obj.line1, obj.line2)
        window = propagate_window(satrec, start, end, args.step_seconds)
        altitudes = np.linalg.norm(window.positions_km, axis=1) - EARTH_RADIUS_KM
        n_errors = int((window.error_codes != 0).sum())

        print(f"{obj.name} (NORAD {obj.norad_id})")
        print(f"  {len(window.times)} steps from {window.times[0]} to {window.times[-1]}")
        print(f"  t0:  pos={window.positions_km[0].round(1)} km  alt={altitudes[0]:.1f} km")
        mid = len(window.times) // 2
        print(f"  t/2: pos={window.positions_km[mid].round(1)} km  alt={altitudes[mid]:.1f} km")
        print(f"  tN:  pos={window.positions_km[-1].round(1)} km  alt={altitudes[-1]:.1f} km")
        print(f"  propagation errors: {n_errors}/{len(window.times)}")
        return 0

    # Batch mode: propagate the whole catalog in one vectorized call
    result = propagate_catalog(catalog, start, end, args.step_seconds)
    print(f"Time grid: {len(result.times)} steps from {result.times[0]} to {result.times[-1]}")
    print(f"Propagated {len(result.norad_ids)}/{len(catalog)} objects successfully.\n")

    radii = np.linalg.norm(result.positions_km, axis=2)  # (n_objects, n_times)
    altitudes = radii - EARTH_RADIUS_KM
    names = {o.norad_id: o.name for o in catalog}

    print(f"{'NORAD ID':>10}  {'Name':<25} {'Alt @ t0 (km)':>15} {'Alt @ tN (km)':>15}")
    for i, norad_id in enumerate(result.norad_ids[:15]):
        print(
            f"{norad_id:>10}  {names.get(norad_id, '?'):<25} "
            f"{altitudes[i, 0]:>15.1f} {altitudes[i, -1]:>15.1f}"
        )
    if len(result.norad_ids) > 15:
        print(f"  ... and {len(result.norad_ids) - 15} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
