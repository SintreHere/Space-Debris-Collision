"""
Phase 3 API layer — thin FastAPI wrapper around the existing ingestion,
propagation, and risk-scoring modules. This is deliberately NOT the full
SaaS backend (no auth, no Postgres, no background workers) — it exists so
the dashboard can consume real propagated catalog data and real risk
scores instead of a static snapshot, while we're still in the core-first
phase. Swapping this for the production FastAPI service later is a matter
of adding auth/persistence around the same endpoints, not rewriting them.

Run locally with:
    uvicorn conjunction.api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from conjunction.config import settings
from conjunction.ingestion.service import ingest_altitude_band
from conjunction.propagation.catalog import load_catalog, propagate_catalog
from conjunction.propagation.sgp4_propagator import load_satellite, propagate_all_at
from conjunction.risk.geodesy import teme_to_geodetic, teme_to_geodetic_batch
from conjunction.risk.pairwise import screen_catalog
from conjunction.risk.pc import probability_of_collision
from conjunction.risk.proximity import RED_KM, YELLOW_KM, compute_proximity

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Deployments without a filesystem-shared cron job (e.g. Railway, where a
# volume attaches to one service only) refresh the TLE cache from inside
# the API process instead. Sync httpx clients under the hood, so the fetch
# runs in a worker thread and never blocks request handling.
REFRESH_INTERVAL_SECONDS = int(os.getenv("TLE_REFRESH_INTERVAL_SECONDS", str(6 * 3600)))
REFRESH_MIN_ALT_KM = float(os.getenv("TLE_REFRESH_MIN_ALT_KM", "350"))
REFRESH_MAX_ALT_KM = float(os.getenv("TLE_REFRESH_MAX_ALT_KM", "1250"))

# Pairwise screening (Phase 3b/4) runs after each refresh over a bounded
# candidate set — full all-pairs over the ~8K-object catalog would be ~34M
# pairs, far beyond what "keep it simple" warrants.
CONJUNCTION_MAX_OBJECTS = int(os.getenv("CONJUNCTION_MAX_OBJECTS", "400"))
CONJUNCTION_WINDOW_HOURS = float(os.getenv("CONJUNCTION_WINDOW_HOURS", "6"))
CONJUNCTION_STEP_SECONDS = float(os.getenv("CONJUNCTION_STEP_SECONDS", "30"))
CONJUNCTION_THRESHOLD_KM = float(os.getenv("CONJUNCTION_THRESHOLD_KM", str(YELLOW_KM)))

# In-memory cache of the latest screening report. Derived data, cheaply
# reconstructable from the SQLite TLE cache — deliberately not persisted.
_conjunction_report: dict | None = None


def _run_conjunction_screening() -> dict:
    """Sync — runs in a worker thread from _refresh_loop after each ingest.
    Candidate set is the first CONJUNCTION_MAX_OBJECTS catalog objects
    (norad_id-ordered from SQL; deterministic, no prioritization)."""
    catalog = load_catalog()[:CONJUNCTION_MAX_OBJECTS]
    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=CONJUNCTION_WINDOW_HOURS)
    window = propagate_catalog(catalog, start, end, CONJUNCTION_STEP_SECONDS)

    events = screen_catalog(catalog, window, threshold_km=CONJUNCTION_THRESHOLD_KM)
    events.sort(key=lambda e: e.miss_distance_km)

    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "params": {
            "max_objects": CONJUNCTION_MAX_OBJECTS,
            "window_hours": CONJUNCTION_WINDOW_HOURS,
            "step_seconds": CONJUNCTION_STEP_SECONDS,
            "threshold_km": CONJUNCTION_THRESHOLD_KM,
        },
        "count": len(events),
        "events": [
            {
                **{k: v for k, v in asdict(e).items() if k != "tca"},
                "tca": e.tca.isoformat(),
                "probability_of_collision": probability_of_collision(e.miss_distance_km),
            }
            for e in events
        ],
    }


async def _refresh_loop() -> None:
    global _conjunction_report
    while True:
        try:
            records = await asyncio.to_thread(
                ingest_altitude_band, REFRESH_MIN_ALT_KM, REFRESH_MAX_ALT_KM
            )
            logger.info("Background refresh cached %d TLE records", len(records))
        except Exception:  # noqa: BLE001
            logger.exception("Background TLE refresh failed; will retry next interval")

        try:
            _conjunction_report = await asyncio.to_thread(_run_conjunction_screening)
            logger.info(
                "Conjunction screening cached %d events", _conjunction_report["count"]
            )
        except Exception:  # noqa: BLE001
            logger.exception("Conjunction screening failed; will retry next interval")

        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_refresh_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Conjunction & Collision Risk Estimator API", version="0.1.0", lifespan=lifespan
)

# Origins come from CORS_ORIGINS (comma-separated) in production; defaults
# to "*" for local dev, where the dashboard runs on a different Vite port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _guess_kind(name: str) -> str:
    """Real Space-Track data has an OBJECT_TYPE field we don't currently
    ingest (see roadmap); this is a placeholder heuristic from the object
    name until that field is added to the ingestion model."""
    upper = name.upper()
    if "DEB" in upper:
        return "debris"
    if "R/B" in upper or "ROCKET BODY" in upper:
        return "rocket_body"
    return "satellite"


# ---------------------------------------------------------------------------
# Propagated-snapshot cache.
#
# The dashboard polls /api/proximity every ~10s and /api/catalog every ~60s,
# potentially from several browsers at once. Recomputing 26k+ TLE parses and
# SGP4 calls per request saturated the CPU and OOM-killed small containers
# (the original per-request loop was written for a ~400-object cache). Two
# cache layers fix it:
#   1. Parsed Satrec objects, keyed by the TLE db's mtime — reparsed only
#      after a background refresh rewrites the cache.
#   2. A propagated geodetic snapshot, shared by every request within a
#      SNAPSHOT_TTL_SECONDS bucket, computed once (single-flight lock) via
#      vectorized SatrecArray + batch geodetic conversion (~tens of ms).
# ---------------------------------------------------------------------------
SNAPSHOT_TTL_SECONDS = int(os.getenv("SNAPSHOT_TTL_SECONDS", "10"))

_satcache_lock = threading.Lock()
_satcache: dict = {"mtime": None, "entries": None}  # entries: list[(CatalogObject, Satrec)]

_snapshot_lock = threading.Lock()
_snapshot: dict = {"bucket": None, "objects": None}


def _load_satellites() -> list:
    """Catalog rows + parsed Satrecs, reloaded only when the TLE db changes."""
    try:
        mtime = os.path.getmtime(settings.tle_db_path)
    except OSError:
        mtime = None
    with _satcache_lock:
        if _satcache["mtime"] != mtime or _satcache["entries"] is None:
            catalog = load_catalog()
            entries = []
            for obj in catalog:
                try:
                    entries.append((obj, load_satellite(obj.line1, obj.line2)))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipping NORAD %d (%s): %s", obj.norad_id, obj.name, exc)
            _satcache["mtime"] = mtime
            _satcache["entries"] = entries
            logger.info("Satrec cache rebuilt: %d objects", len(entries))
        return _satcache["entries"]


def _compute_snapshot(at: datetime) -> list[dict]:
    entries = _load_satellites()
    if not entries:
        return []
    positions, error_codes = propagate_all_at([s for _, s in entries], at)
    lats, lons, alts = teme_to_geodetic_batch(positions, at)

    results = []
    for i, (obj, _sat) in enumerate(entries):
        if error_codes[i] != 0:
            continue
        results.append(
            {
                "norad_id": obj.norad_id,
                "name": obj.name,
                "kind": _guess_kind(obj.name),
                "altitude_km": float(alts[i]),
                "lat": float(lats[i]),
                "lon": float(lons[i]),
            }
        )
    return results


def _propagate_catalog_now(at: datetime, min_alt: float | None, max_alt: float | None) -> list[dict]:
    """Geodetic positions for the whole catalog at `at`, served from the
    shared snapshot cache; only the altitude filter is per-request."""
    bucket = int(at.timestamp() // SNAPSHOT_TTL_SECONDS)
    with _snapshot_lock:
        if _snapshot["bucket"] != bucket:
            _snapshot["objects"] = _compute_snapshot(at)
            _snapshot["bucket"] = bucket
        objects = _snapshot["objects"]

    if not objects:
        raise HTTPException(
            status_code=404,
            detail="No cached objects found. Run scripts/fetch_tles.py first.",
        )

    results = []
    for entry in objects:
        alt_km = entry["altitude_km"]
        if min_alt is not None and alt_km < min_alt:
            continue
        if max_alt is not None and alt_km > max_alt:
            continue
        results.append(entry
        )
    return results


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/catalog")
def get_catalog(
    at: datetime | None = Query(None, description="ISO timestamp; defaults to now"),
    min_alt: float | None = Query(None, description="Minimum altitude, km"),
    max_alt: float | None = Query(None, description="Maximum altitude, km"),
):
    """Current propagated positions for every cached catalog object."""
    query_time = at or datetime.now(timezone.utc)
    if query_time.tzinfo is None:
        query_time = query_time.replace(tzinfo=timezone.utc)

    objects = _propagate_catalog_now(query_time, min_alt, max_alt)
    return {"epoch": query_time.isoformat(), "count": len(objects), "objects": objects}


class ProximityRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    altitude_km: float = Field(..., gt=0)
    at: datetime | None = None
    limit: int = Field(30, gt=0, le=500)


@app.post("/api/proximity")
def post_proximity(req: ProximityRequest):
    """
    Rank every cached catalog object by distance from the given simulated
    position, and return risk-scored results using the same logic
    (thresholds + scoring formula) the dashboard was previously computing
    client-side — this endpoint is now the single source of truth for it.
    """
    query_time = req.at or datetime.now(timezone.utc)
    if query_time.tzinfo is None:
        query_time = query_time.replace(tzinfo=timezone.utc)

    objects = _propagate_catalog_now(query_time, None, None)
    if not objects:
        raise HTTPException(status_code=404, detail="No propagatable objects in catalog.")

    ranked = compute_proximity(objects, req.lat, req.lon, req.altitude_km, query_time)
    nearest = ranked[0]

    return {
        "epoch": query_time.isoformat(),
        "user": {"lat": req.lat, "lon": req.lon, "altitude_km": req.altitude_km},
        "thresholds_km": {"red": RED_KM, "yellow": YELLOW_KM},
        "nearest": nearest.__dict__,
        "objects": [a.__dict__ for a in ranked[: req.limit]],
        "total_objects_considered": len(ranked),
    }


@app.get("/api/conjunctions")
def get_conjunctions():
    """Latest cached pairwise screening report (computed in the background
    after each TLE refresh — this endpoint never triggers propagation)."""
    if _conjunction_report is None:
        return {"computed_at": None, "status": "pending", "params": None, "count": 0, "events": []}
    return _conjunction_report


MAX_TRAJECTORY_OBJECTS = 30


@app.get("/api/trajectories")
def get_trajectories(
    norad_ids: str = Query(..., description="Comma-separated NORAD IDs"),
    hours: float = Query(6, gt=0, le=24),
    step_seconds: float = Query(60, gt=0, le=3600),
    start: datetime | None = Query(None, description="ISO timestamp; defaults to now"),
):
    """Propagated orbit paths (geodetic points over time) for a small set of
    objects — feeds the 3D trajectory view."""
    try:
        ids = [int(x) for x in norad_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="norad_ids must be comma-separated integers")
    if not ids:
        raise HTTPException(status_code=400, detail="norad_ids must contain at least one id")
    if len(ids) > MAX_TRAJECTORY_OBJECTS:
        raise HTTPException(
            status_code=400, detail=f"norad_ids cannot exceed {MAX_TRAJECTORY_OBJECTS} objects"
        )

    query_start = start or datetime.now(timezone.utc)
    if query_start.tzinfo is None:
        query_start = query_start.replace(tzinfo=timezone.utc)
    query_end = query_start + timedelta(hours=hours)

    wanted = set(ids)
    subset = [o for o in load_catalog() if o.norad_id in wanted]
    if not subset:
        raise HTTPException(
            status_code=404, detail="None of the requested norad_ids are in the cached catalog"
        )

    window = propagate_catalog(subset, query_start, query_end, step_seconds)
    name_by_id = {o.norad_id: o.name for o in subset}

    objects = []
    for i, nid in enumerate(window.norad_ids):
        points = []
        for t_idx, t in enumerate(window.times):
            if window.error_codes[i, t_idx] != 0:
                continue
            lat, lon, alt_km = teme_to_geodetic(tuple(window.positions_km[i, t_idx]), t)
            points.append({"t": t.isoformat(), "lat": lat, "lon": lon, "alt_km": alt_km})
        objects.append({"norad_id": nid, "name": name_by_id.get(nid, str(nid)), "points": points})

    return {
        "start": query_start.isoformat(),
        "end": query_end.isoformat(),
        "step_seconds": step_seconds,
        "objects": objects,
    }
