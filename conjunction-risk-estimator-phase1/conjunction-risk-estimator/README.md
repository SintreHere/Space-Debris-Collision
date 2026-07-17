# Conjunction & Collision Risk Estimator — Algorithmic Core

Predicts and ranks upcoming close-approach ("conjunction") events between
tracked LEO objects, with a risk score, so an operator could act on it —
the same operational function as ISRO's IS4OM or Digantara's tracking service.

**Current phase:** Phase 1 — Data Ingestion. The SaaS layer (auth, API,
frontend, deployment) is deliberately deferred until the algorithmic core
(ingestion → propagation → conjunction detection → risk scoring) is proven
correct.

## Setup

1. **Get Space-Track credentials** (free): register at https://www.space-track.org
2. **Clone this repo and set up the environment:**

   ```bash
   git clone <your-repo-url>
   cd conjunction-risk-estimator
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

3. **Configure credentials:**

   ```bash
   cp .env.example .env
   # edit .env and fill in SPACETRACK_USERNAME / SPACETRACK_PASSWORD
   ```

4. **Run the tests** (no network required — pure orbital-mechanics math):

   ```bash
   pytest tests/ -v
   ```

## Usage — Phase 1: Fetch TLEs for an altitude band

```bash
# Primary path: Space-Track (needs credentials in .env)
python scripts/fetch_tles.py --min-alt 700 --max-alt 900

# No credentials yet? Use the no-auth fallback:
python scripts/fetch_tles.py --min-alt 700 --max-alt 900 --use-celestrak

# Cap the result set while iterating:
python scripts/fetch_tles.py --min-alt 700 --max-alt 900 --limit 50
```

This fetches current TLEs, computes each object's perigee/apogee altitude
from its orbital elements (Kepler's third law — see
`src/conjunction/ingestion/altitude.py`), keeps only objects whose orbit
overlaps the requested band, and caches everything to a local SQLite
database at `data/tle_cache.db`.

## Design notes / simplifying assumptions

- **Altitude filtering is done client-side**, not via a Space-Track server-side
  predicate. Space-Track's exact predicate names have changed over the years
  (`tle_latest` → `gp`), but mean motion and eccentricity are always present
  on every TLE and are physically sufficient to compute altitude — so
  filtering locally is more robust than depending on a specific query syntax.
- **Space-Track is primary, CelesTrak is fallback.** If Space-Track auth
  fails or credentials aren't configured, ingestion automatically falls back
  to CelesTrak's no-auth feed.
- **SQLite for now, not Postgres.** This is intentional for the core-first
  phase — we don't want infrastructure (Docker, Postgres, Celery) in the way
  while validating the algorithm. The storage interface
  (`init_db` / `upsert_tles` / `get_latest_tles`) is written so it can be
  swapped for a Postgres/TimescaleDB-backed implementation later without
  changing any caller code.
- **Only current-orbit objects are considered** (`decay_date` filtered out,
  eccentricity capped at 0.25 to exclude highly elliptical/GEO-transfer
  orbits that aren't relevant to LEO congestion).

## Project structure

```
src/conjunction/
├── config.py                    # environment/settings
└── ingestion/
    ├── models.py                 # TLERecord (pydantic)
    ├── parsing.py                 # raw TLE line-2 field parsing
    ├── altitude.py                # orbital mechanics: mean motion -> altitude
    ├── spacetrack_client.py       # primary data source
    ├── celestrak_client.py        # fallback data source
    ├── storage.py                 # SQLite cache
    └── service.py                 # orchestration + fallback logic
scripts/
└── fetch_tles.py                  # Phase 1 CLI entry point
tests/
└── test_altitude.py               # orbital mechanics sanity checks
```

## Roadmap

- [x] **Phase 1 — Data ingestion**: fetch + cache TLEs for a defined altitude band
- [ ] **Phase 2 — Propagation**: SGP4 position vectors over a 72-hour window, ECI frame
- [ ] **Phase 3 — Conjunction detection**: minimum separation per object pair, screening thresholds
- [ ] **Phase 4 — Risk scoring**: simplified probability-of-collision
- [ ] **Phase 5 — Visualization**: 3D trajectory plots, altitude-band density
- [ ] **SaaS layer**: FastAPI + Next.js + Postgres/TimescaleDB + auth + deployment
