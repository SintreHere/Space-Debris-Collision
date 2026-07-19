# SAKLE — Space Analytics & Kinetic Location Engine

A production-grade conjunction screening and orbital situational-awareness platform for low Earth orbit. SAKLE ingests the live public satellite catalog, propagates every object with SGP4, screens all object pairs for close approaches, estimates collision probability, and renders it all in a real-time mission-control dashboard — the same operational function class as ISRO's IS4OM or commercial SSA services.

## Features

- **Live catalog ingestion** — current TLEs from Space-Track (primary) with automatic no-auth CelesTrak fallback, filtered by altitude band, cached in SQLite, refreshed on a background schedule inside the API process
- **Vectorized SGP4 propagation** — the entire catalog (20k+ objects) propagated over multi-hour windows in a single `SatrecArray` call
- **Proximity monitor** — rank every tracked object by distance from a simulated asset position, with distance-banded risk levels (RED < 5 km, YELLOW < 25 km)
- **True pairwise conjunction screening** — minimum separation between every pair of catalog objects over the propagation window, reported with time of closest approach and relative velocity
- **Collision probability (Pc)** — closed-form isotropic-covariance estimate for each screened event
- **3D orbital tracker** — three.js globe with real terrain textures, a day/night terminator computed from the actual sun position, NASA Black Marble city lights on the night side, fading orbit trails, and per-object visibility toggles
- **Mission-control UI** — ISRO-themed dashboard with a sweeping radar scope, live IST/UTC clock, analytics tiles, and auto-refreshing telemetry

## Architecture

```
Space-Track ──┐
              ├─► ingestion ─► SQLite TLE cache ─► SGP4 propagation ─► risk engine ─► FastAPI ─► React dashboard
CelesTrak  ───┘   (httpx)      (data/*.db)         (sgp4, numpy)       proximity          │        radar scope
                                    ▲                                  pairwise + Pc      │        analytics
                                    └── background refresh (6h) ───────────────────────────┘        three.js globe
```

Backend: **Python 3.11+ · FastAPI · sgp4 · NumPy · SciPy · SQLite**
Frontend: **React 18 · Vite · three.js · lucide-react**

## Quick start

Prerequisites: Python 3.11+, Node 20+, and (optionally) a free [Space-Track](https://www.space-track.org) account.

```bash
git clone https://github.com/SintreHere/Space-Debris-Collision.git
cd Space-Debris-Collision

# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add Space-Track credentials (optional)
python scripts/fetch_tles.py --min-alt 350 --max-alt 1250   # seed the cache
uvicorn conjunction.api.main:app --reload --port 8000

# Frontend (second terminal)
cd apps/web
npm install
npm run dev                   # open the printed URL (default http://localhost:5173)
```

Interactive API docs are auto-generated at `http://localhost:8000/docs`.

The manual seed step is only needed on a fresh local setup — in production the API refreshes the TLE cache itself on a background schedule.

## Configuration

All configuration is via environment variables (loaded from `.env` locally — see [.env.example](.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `SPACETRACK_USERNAME` / `SPACETRACK_PASSWORD` | — | Space-Track credentials; without them ingestion falls back to CelesTrak |
| `TLE_DB_PATH` | `data/tle_cache.db` | SQLite cache location (mount a volume here in production) |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins — set to your frontend domain in production |
| `TLE_REFRESH_INTERVAL_SECONDS` | `21600` | Background catalog refresh cadence |
| `TLE_REFRESH_MIN_ALT_KM` / `TLE_REFRESH_MAX_ALT_KM` | `350` / `1250` | Altitude band the refresh ingests |
| `VITE_API_BASE` (frontend, build-time) | `http://localhost:8000` | API URL baked into the frontend bundle |

## API

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness probe |
| `GET /api/catalog` | Every cached object propagated to now, as geodetic lat/lon/altitude |
| `POST /api/proximity` | Rank all objects by distance from `{lat, lon, altitude_km}`, with risk scores |
| `GET /api/conjunctions` | Pairwise close-approach events over the screening window, with TCA, miss distance, relative velocity, and Pc |
| `GET /api/trajectories` | Time-series geodetic tracks for selected NORAD IDs (drives the 3D viewer) |

## Testing

```bash
PYTHONPATH=src:. pytest tests/ -q      # 42 tests, no network required
ruff check src/ scripts/ tests/ research/
```

The test suite covers Kepler-derived altitude math, SGP4 propagation against a real ISS TLE, TEME↔geodetic round-trips, proximity ranking/thresholds, pairwise screening, the Pc formula, the Indian LEO asset registry (epoch-awareness, exclusion rules), and the historical-data acquisition layer (offline, via fake transports).

## Deployment

Both services ship with Dockerfiles and deploy cleanly to Railway (or any container host):

- **Backend** — root [Dockerfile](Dockerfile); mount a persistent volume and set `TLE_DB_PATH` onto it, set `CORS_ORIGINS` to the frontend domain. The in-process scheduler keeps TLEs fresh, so no external cron is needed.
- **Frontend** — [apps/web/Dockerfile](apps/web/Dockerfile); set `VITE_API_BASE` to the backend URL **before build** (it is baked into the bundle at build time).

For a single-VPS deployment (nginx + systemd + certbot), serve `apps/web/dist` statically and reverse-proxy `/api/` to uvicorn on localhost.

## Project structure

```
src/conjunction/
├── config.py                  # environment/settings
├── ingestion/                 # TLE fetch + cache
│   ├── models.py              #   TLERecord (pydantic)
│   ├── parsing.py             #   raw TLE field parsing
│   ├── altitude.py            #   mean motion → perigee/apogee altitude
│   ├── spacetrack_client.py   #   primary source
│   ├── celestrak_client.py    #   no-auth fallback
│   ├── storage.py             #   SQLite cache
│   └── service.py             #   orchestration + fallback logic
├── propagation/
│   ├── models.py              #   propagation window dataclasses
│   ├── sgp4_propagator.py     #   single / windowed / multi-object SGP4
│   └── catalog.py             #   cached TLEs → batch propagation
├── risk/
│   ├── geodesy.py             #   TEME↔geodetic, GMST, bearing
│   ├── proximity.py           #   single-point ranking + risk levels
│   ├── pairwise.py            #   all-pairs conjunction screening
│   └── pc.py                  #   probability-of-collision estimate
└── api/
    └── main.py                # FastAPI app + background TLE refresh

apps/web/                      # SAKLE dashboard (Vite + React)
├── public/
│   ├── audio/                 #   background ambience
│   └── textures/              #   bundled Earth day/night textures (no CDN)
└── src/
    ├── components/
    │   ├── SakleDashboard.jsx #   radar scope, analytics, conjunction watch
    │   └── OrbitViewer3D.jsx  #   three.js orbital tracker
    └── three/
        ├── sceneSetup.js      #   textured Earth, sun terminator, starfield
        └── orbitPath.js       #   fading trails, markers, coordinate mapping

research/                      # India LEO conjunction-exposure study
├── assets/                    #   Phase 1 — curated Indian LEO asset registry
│   ├── indian_leo_assets.csv  #     27-object catalog (epoch-aware, provenance-documented)
│   ├── registry.py            #     primaries_at() selection API + ISSAR sanity check
│   └── verify_assets.py       #     live CelesTrak cross-check
└── history/                   #   Phase 2 — historical gp_history acquisition
    ├── snapshots.py           #     quarterly epoch-selection policy
    ├── client.py              #     rate-limited, paginated Space-Track puller
    ├── store.py               #     epoch-indexed SQLite + resumability ledger
    └── downloader.py          #     CLI orchestrator (--dry-run supported)

scripts/                       # CLI utilities (fetch_tles, propagate_catalog)
tests/                         # pytest suite (42 tests)
```

## Research: India LEO conjunction-exposure study

Alongside the operational dashboard, `research/` hosts a phased study of
Indian LEO assets' conjunction exposure (2019→2026). Each phase ships with a
runbook and a completion report at the repo root:

- **Phase 1 — asset registry** ([runbook](PHASE1_RUNBOOK.md) · [report](PHASE1_REPORT.md)): 27 curated ISRO LEO objects with epoch-aware primary-set selection, verified against the live CelesTrak catalog.
- **Phase 2 — historical data** ([runbook](PHASE2_RUNBOOK.md) · [report](PHASE2_REPORT.md)): quarterly `gp_history` snapshots 2019Q1–2026Q3 plus full elset histories for all primaries, rate-limit governed and resumable.
- **Phase 3 — screening cascade** (next): staged conjunction filter over the historical snapshots.

## Engineering notes

- **TEME frame throughout.** SGP4 natively outputs TEME; every object is propagated in the same frame at the same timestamps, so relative distances — all that conjunction screening needs — are valid without a J2000/GCRF conversion.
- **Altitude filtering is computed, not queried.** Perigee/apogee are derived locally from mean motion and eccentricity (Kepler's third law) rather than relying on Space-Track predicate syntax, which has changed over the years.
- **Pc is a documented simplification.** Public TLEs carry no per-object covariance, so `risk/pc.py` uses a closed-form isotropic combined-covariance model — the standard screening-level approach when covariance data is unavailable.
- **SQLite by design.** The storage interface (`init_db` / `upsert_tles` / `get_latest_tles`) is deliberately narrow so a Postgres/TimescaleDB implementation can replace it without touching callers.
- **Screening scope.** Decayed objects are filtered out and eccentricity is capped at 0.25 to exclude GEO-transfer orbits irrelevant to LEO congestion.

## Roadmap

- [x] TLE ingestion with altitude-band filtering and fallback source
- [x] Vectorized multi-object SGP4 propagation
- [x] Proximity ranking + risk scoring, API, live dashboard
- [x] True pairwise conjunction screening (`/api/conjunctions`)
- [x] Closed-form Pc estimation
- [x] three.js 3D trajectory visualization
- [ ] Per-object covariance ingestion (CDM-style) for full 2D Pc
- [ ] Postgres/TimescaleDB, auth, multi-user SaaS layer
