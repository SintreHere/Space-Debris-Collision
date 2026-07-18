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
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from conjunction.config import settings
from conjunction.ingestion.service import ingest_altitude_band
from conjunction.propagation.catalog import load_catalog
from conjunction.propagation.sgp4_propagator import load_satellite, propagate_at
from conjunction.risk.geodesy import teme_to_geodetic
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


async def _refresh_loop() -> None:
    while True:
        try:
            records = await asyncio.to_thread(
                ingest_altitude_band, REFRESH_MIN_ALT_KM, REFRESH_MAX_ALT_KM
            )
            logger.info("Background refresh cached %d TLE records", len(records))
        except Exception:  # noqa: BLE001
            logger.exception("Background TLE refresh failed; will retry next interval")
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


def _propagate_catalog_now(at: datetime, min_alt: float | None, max_alt: float | None) -> list[dict]:
    """Load the cached catalog and propagate every object to `at`, returning
    geodetic positions. This recomputes SGP4 on every call rather than
    caching — fine at the scale of a few hundred cached objects; add
    caching here first if this ever becomes a bottleneck."""
    catalog = load_catalog()
    if not catalog:
        raise HTTPException(
            status_code=404,
            detail="No cached objects found. Run scripts/fetch_tles.py first.",
        )

    results = []
    for obj in catalog:
        try:
            satrec = load_satellite(obj.line1, obj.line2)
            state = propagate_at(satrec, at)
            if state.error_code != 0:
                continue
            lat, lon, alt_km = teme_to_geodetic(tuple(state.position_km), at)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping NORAD %d (%s): %s", obj.norad_id, obj.name, exc)
            continue

        if min_alt is not None and alt_km < min_alt:
            continue
        if max_alt is not None and alt_km > max_alt:
            continue

        results.append(
            {
                "norad_id": obj.norad_id,
                "name": obj.name,
                "kind": _guess_kind(obj.name),
                "altitude_km": alt_km,
                "lat": lat,
                "lon": lon,
            }
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
