"""
Phase 2 — Space-Track gp_history client.

Bulk-retrieval etiquette per Space-Track guidelines (and plan Section D):
full-catalog pulls per epoch window, never per-object loops; every request
passes through the RateLimiter; JSON/OMM format only (`format=json`), so the
pipeline is independent of the fixed-width TLE format and 6-digit-ID safe.

Transport is injectable: the real transport wraps the `spacetrack` library
(same auth pattern as src/conjunction/ingestion/spacetrack_client.py, reusing
SPACETRACK_USERNAME/PASSWORD from .env); tests inject fakes.

Pagination: gp_history windows over the full LEO catalog can return hundreds
of thousands of rows. We page with Space-Track's `limit/<n>,<offset>` syntax,
ordered by GP_ID for a stable cursor, and stop when a page comes back short.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from research.history.models import GPRecord, gp_record_from_omm_json
from research.history.ratelimit import RateLimiter
from research.history.snapshots import Snapshot, nearest_per_object

logger = logging.getLogger(__name__)

# LEO net: mean_motion > 11 rev/day (~ perigee below ~2000 km), matching the
# operational client's wide-net-then-filter-locally policy.
LEO_MEAN_MOTION_PREDICATE = ">11"
DEFAULT_PAGE_SIZE = 50_000

# A transport takes (request_class, predicates) and returns the raw response
# text. Keeping it a plain callable makes the client trivially testable.
Transport = Callable[[str, dict], str]


class HistoryDownloadError(RuntimeError):
    pass


def spacetrack_transport() -> Transport:
    """Real transport backed by the `spacetrack` library (lazy import so the
    module stays importable without credentials/network, e.g. in tests).

    50k-row pages can take minutes when Space-Track is under load, so the
    default 30s httpx timeout is replaced with a 5-minute read timeout, and
    transient failures (timeouts, 5xx) get two retries with a 60s pause —
    the snapshot ledger makes anything beyond that safely re-runnable."""
    import httpx
    from spacetrack import SpaceTrackClient

    from conjunction.config import settings

    if not settings.has_spacetrack_credentials():
        raise HistoryDownloadError(
            "No Space-Track credentials in environment "
            "(SPACETRACK_USERNAME / SPACETRACK_PASSWORD)."
        )
    st = SpaceTrackClient(
        identity=settings.spacetrack_username,
        password=settings.spacetrack_password,
        httpx_client=httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0)),
    )

    def _request(request_class: str, predicates: dict) -> str:
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                return st.generic_request(request_class, **predicates)
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = status is None or status >= 500
                if not retryable or attempt == attempts:
                    raise
                logger.warning(
                    "Transient Space-Track error (%s), retry %d/%d in 60s",
                    exc, attempt, attempts - 1,
                )
                time.sleep(60)
        raise AssertionError("unreachable")

    return _request


class GPHistoryClient:
    def __init__(
        self,
        transport: Transport | None = None,
        limiter: RateLimiter | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ):
        self._transport = transport or spacetrack_transport()
        self._limiter = limiter or RateLimiter()
        self._page_size = page_size

    # ---------------------------------------------------------------- pages
    def _fetch_pages(self, request_class: str, predicates: dict) -> list[dict]:
        """Fetch all pages for a query using limit/offset over GP_ID order."""
        rows: list[dict] = []
        offset = 0
        while True:
            page_predicates = dict(predicates)
            page_predicates["orderby"] = "GP_ID"
            page_predicates["limit"] = f"{self._page_size},{offset}"
            page_predicates["format"] = "json"

            slept = self._limiter.acquire()
            if slept > 0:
                logger.info("Rate limiter slept %.1f s", slept)
            raw = self._transport(request_class, page_predicates)

            try:
                page = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                raise HistoryDownloadError(
                    f"Non-JSON response from Space-Track (first 200 chars): {raw[:200]!r}"
                ) from exc
            if not isinstance(page, list):
                raise HistoryDownloadError(f"Unexpected response shape: {type(page)}")

            rows.extend(page)
            logger.info(
                "%s: page at offset %d -> %d rows (total %d)",
                request_class, offset, len(page), len(rows),
            )
            if len(page) < self._page_size:
                return rows
            offset += self._page_size

    # ------------------------------------------------------------ snapshots
    def fetch_snapshot(self, snapshot: Snapshot) -> list[GPRecord]:
        """Full-LEO-catalog elsets in the snapshot window, deduped to one
        nearest-to-target elset per object (the documented policy)."""
        predicates = {
            "epoch": snapshot.spacetrack_epoch_range,
            "mean_motion": LEO_MEAN_MOTION_PREDICATE,
            "eccentricity": "<0.25",  # match operational ingestion cap
        }
        rows = self._fetch_pages("gp_history", predicates)
        fetched_at = datetime.now(timezone.utc)
        records = [gp_record_from_omm_json(r, fetched_at) for r in rows]
        deduped = nearest_per_object(records, snapshot.target)
        logger.info(
            "Snapshot %s: %d raw elsets -> %d objects after nearest-epoch dedupe",
            snapshot.label, len(records), len(deduped),
        )
        return deduped

    # ------------------------------------------------------------ primaries
    def fetch_object_history(
        self,
        norad_ids: Sequence[int],
        epoch_start: str,  # "YYYY-MM-DD"
        epoch_end: str,
        chunk_months_hint: str | None = None,  # documentation only
    ) -> list[GPRecord]:
        """Complete elset history for a small object set (Indian primaries).

        One query per call — pass a comma-list of NORAD IDs, never loop
        per-object. Callers chunk the date range by year to keep individual
        responses modest (see downloader.plan_primary_chunks).
        """
        predicates = {
            "norad_cat_id": ",".join(str(n) for n in norad_ids),
            "epoch": f"{epoch_start}--{epoch_end}",
        }
        rows = self._fetch_pages("gp_history", predicates)
        fetched_at = datetime.now(timezone.utc)
        return [gp_record_from_omm_json(r, fetched_at) for r in rows]
