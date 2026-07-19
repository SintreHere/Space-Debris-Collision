"""
Phase 2 de-risk probe (plan Recommendation 2: "De-risk Phase 2 first").

Answers, with THREE cheap credentialed queries, the go/no-go questions before
committing to the multi-day bulk download:

  Q1. Does gp_history actually reach back to Jan 2019?
      -> pull Cartosat-2F (43111) elsets for 2019-01-01--2019-01-08.
         Non-empty => depth confirmed for at least well-tracked objects.

  Q2. How big is one full-catalog snapshot window?
      -> pull the 2019Q1 window restricted to two columns
         (predicates=NORAD_CAT_ID,EPOCH) so the payload stays small, and
         count rows + distinct objects locally. Multiply by the snapshot
         count for the total volume estimate.

  Q3. Are Indian defence primaries present at depth?
      -> pull RISAT-2B (44233) + EMISAT (44078) for one 2019 month.

Decision rule (from the plan): if extrapolated download time for the full
quarterly plan exceeds ~2 weeks of rate-limited pulls, drop to annual cadence.

Run:  PYTHONPATH=src:. python -m research.history.probe_2019_depth
"""

from __future__ import annotations

import json
import sys

from research.history.client import spacetrack_transport
from research.history.ratelimit import RateLimiter
from research.history.snapshots import snapshot_plan


def main() -> int:
    transport = spacetrack_transport()
    limiter = RateLimiter()

    def query(predicates: dict) -> list[dict]:
        limiter.acquire()
        raw = transport("gp_history", {**predicates, "format": "json"})
        return json.loads(raw)

    print("Q1: 2019 depth for Cartosat-2F (43111)...")
    q1 = query({"norad_cat_id": "43111", "epoch": "2019-01-01--2019-01-08"})
    print(f"    {len(q1)} elsets in the first week of 2019 "
          f"-> depth {'CONFIRMED' if q1 else 'NOT CONFIRMED - STOP AND REPLAN'}")

    print("Q2: full-catalog 2019Q1 window volume (columns restricted)...")
    q2 = query({
        "epoch": "2018-12-30--2019-01-03",
        "mean_motion": ">11",
        "eccentricity": "<0.25",
        "predicates": "NORAD_CAT_ID,EPOCH",
        "orderby": "NORAD_CAT_ID",
    })
    n_rows = len(q2)
    n_objects = len({r["NORAD_CAT_ID"] for r in q2})
    n_snapshots = len(snapshot_plan())
    print(f"    {n_rows} elset rows over {n_objects} distinct LEO objects in a 4-day window")
    print(f"    x {n_snapshots} quarterly snapshots ~= {n_rows * n_snapshots:,} rows total "
          f"(row growth over 2019->2026 will push this higher)")

    print("Q3: defence-primary depth (RISAT-2B 44233, EMISAT 44078), June 2019...")
    q3 = query({"norad_cat_id": "44233,44078", "epoch": "2019-06-01--2019-07-01"})
    per_obj: dict[str, int] = {}
    for r in q3:
        per_obj[r["NORAD_CAT_ID"]] = per_obj.get(r["NORAD_CAT_ID"], 0) + 1
    print(f"    elsets: {per_obj or 'NONE - flag in risk register'}")

    print("\nProbe complete (3 requests). Apply the decision rule from the "
          "module docstring before launching the bulk download.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
