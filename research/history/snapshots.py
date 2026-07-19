"""
Phase 2 — snapshot policy.

THE epoch-selection policy (documented per plan Phase 2 risk note):

  * Cadence: quarterly target dates (Jan/Apr/Jul/Oct 1, 00:00 UTC) from
    2019-01-01 to the present. Annual fallback = keep only Q1 labels
    (plan Recommendation 2's degraded mode if downloads run long).
  * Window: for each target date we pull all gp_history elsets with
    EPOCH in [target - window_days, target + window_days] (default ±2 days,
    a 4-day span). LEO objects are typically updated multiple times per day,
    so ±2 days captures >~99% of tracked LEO objects while bounding volume.
  * Selection: per object, keep the single elset whose epoch is NEAREST to
    the target date ("nearest-TLE-to-snapshot-date"). Ties break toward the
    earlier elset for determinism.
  * Sparse objects (no elset in the window) are simply absent from that
    snapshot — acceptable for the secondary catalog. Indian primaries are
    immune to this: their full elset history is downloaded separately
    (fetch_object_history), so primary coverage never depends on the window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from research.history.models import GPRecord

STUDY_START = date(2019, 1, 1)
QUARTER_MONTHS = (1, 4, 7, 10)
DEFAULT_WINDOW_DAYS = 2.0


@dataclass(frozen=True)
class Snapshot:
    label: str  # e.g. "2019Q1"
    target: datetime  # UTC midnight of the target date
    window_start: datetime
    window_end: datetime

    @property
    def spacetrack_epoch_range(self) -> str:
        """Space-Track range predicate, e.g. '2019-01-30--2019-02-03'."""
        return f"{self.window_start:%Y-%m-%d}--{self.window_end:%Y-%m-%d}"


def _mk_snapshot(year: int, month: int, window_days: float) -> Snapshot:
    q = QUARTER_MONTHS.index(month) + 1
    target = datetime(year, month, 1, tzinfo=timezone.utc)
    delta = timedelta(days=window_days)
    return Snapshot(
        label=f"{year}Q{q}",
        target=target,
        window_start=target - delta,
        window_end=target + delta,
    )


def snapshot_plan(
    start: date = STUDY_START,
    end: date | None = None,
    cadence: str = "quarterly",
    window_days: float = DEFAULT_WINDOW_DAYS,
) -> list[Snapshot]:
    """All snapshot epochs in [start, end], quarterly or annual cadence."""
    if cadence not in ("quarterly", "annual"):
        raise ValueError(f"unknown cadence: {cadence}")
    end = end or datetime.now(timezone.utc).date()
    months = QUARTER_MONTHS if cadence == "quarterly" else (1,)

    out = []
    for year in range(start.year, end.year + 1):
        for month in months:
            d = date(year, month, 1)
            if start <= d <= end:
                out.append(_mk_snapshot(year, month, window_days))
    return out


def nearest_per_object(records: list[GPRecord], target: datetime) -> list[GPRecord]:
    """Apply the nearest-TLE-to-snapshot-date policy: one elset per object."""
    best: dict[int, GPRecord] = {}
    for r in records:
        cur = best.get(r.norad_id)
        if cur is None:
            best[r.norad_id] = r
            continue
        d_new = abs((r.epoch - target).total_seconds())
        d_cur = abs((cur.epoch - target).total_seconds())
        if d_new < d_cur or (d_new == d_cur and r.epoch < cur.epoch):
            best[r.norad_id] = r
    return sorted(best.values(), key=lambda r: r.norad_id)
