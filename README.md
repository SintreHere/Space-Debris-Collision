# Conjunction & Collision Risk Estimator — Algorithmic Core

Predicts and ranks upcoming close-approach ("conjunction") events between
tracked LEO objects, with a risk score, so an operator could act on it —
the same operational function as ISRO's IS4OM or Digantara's tracking service.

**Current phase:** Phase 3 complete — real ingestion, propagation, risk
scoring, a FastAPI backend, and a live React dashboard are all wired
together. The full SaaS layer (auth, persistence beyond SQLite, multi-user
deployment) is still deliberately deferred — this is a real working tool,
just a single-user/local one so far.

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

## Usage — Phase 3: Run the API + dashboard together

This is the full loop: real cached TLEs → SGP4 propagation → risk scoring →
live dashboard.

**1. Start the backend** (from the project root):

```bash
pip install -e ".[dev]"          # picks up fastapi/uvicorn
uvicorn conjunction.api.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive API docs (auto-generated
by FastAPI). Two endpoints matter here:
- `GET /api/catalog` — every cached object, propagated to right now, as geodetic lat/lon/altitude
- `POST /api/proximity` — given `{lat, lon, altitude_km}`, ranks every object by distance and risk-scores them (this is `conjunction.risk.proximity`, the same module the tests exercise)

**2. Start the frontend** (in a second terminal):

```bash
cd apps/web
npm install
npm run dev
```

Open the URL Vite prints (typically `http://localhost:5173`). The dashboard
loads in **Demo Snapshot** mode by default (74 simulated objects, no backend
needed) — click **LIVE API** to switch it to your running backend. If the
API base shown doesn't match where uvicorn is listening, edit the input
next to the toggle.

**3. Make sure there's actually data to look at:**

```bash
python scripts/fetch_tles.py --min-alt 350 --max-alt 1250
```

The dashboard reads whatever is in `data/tle_cache.db` — an empty cache
means `/api/catalog` and `/api/proximity` will 404 with a message telling
you to run this.

### What moved server-side in Phase 3

The dashboard's status card, radar scope, altitude chart, and ranked table
all originally computed distance/bearing/risk in the browser against a
static snapshot. In Live mode, `conjunction.risk.proximity` (backed by
`conjunction.risk.geodesy` for the TEME↔geodetic conversions) now does that
computation server-side, against your real propagated catalog. The
thresholds and scoring formula are unchanged — verified identical in
`tests/test_proximity.py` — so switching between Demo and Live shouldn't
change how a given position is classified, only whether the objects behind
it are simulated or real.

## Usage — Phase 2: Propagate the catalog forward in time

```bash
# Batch mode: propagate everything in the cache over the default 72h window
python scripts/propagate_catalog.py

# Custom window / step size
python scripts/propagate_catalog.py --hours 72 --step-seconds 300

# Single object, verbose output (position + altitude at start/mid/end)
python scripts/propagate_catalog.py --norad-id 25544
```

This uses SGP4's vectorized multi-object API (`SatrecArray.sgp4`) to
propagate every cached object over the same time grid in one call, returning
a `(n_objects, n_times, 3)` position array — the exact shape Phase 3's
pairwise minimum-distance search will consume.

**Frame note:** positions/velocities are in TEME (SGP4's native output
frame), not converted to J2000/GCRS. This is intentional, not an oversight —
every object is propagated into the same TEME frame at the same timestamps,
so *relative* distances between objects (all conjunction detection needs)
are correct without a frame conversion. The conversion gets added in Phase 5
for visualization, via astropy.

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

## Usage — Phase 2: Propagate cached objects forward in time

```bash
python scripts/propagate_demo.py --hours 72 --step-seconds 300 --limit 10
```

Loads the most recent TLE per object from the Phase 1 cache, propagates each
one forward using SGP4, and prints altitude sanity stats. The core functions
you'll build on in Phase 3:

- `propagate_at(satrec, dt)` — position/velocity for one object at one instant
- `propagate_window(satrec, start, end, step_seconds)` — one object over a time grid
- `propagate_many(satellites, start, end, step_seconds)` — **all** objects over
  the same time grid, vectorized, returning a `(n_objects, n_times, 3)` array —
  this is the shape Phase 3's pairwise minimum-distance search will consume directly

All outputs are in the TEME frame (SGP4's native frame). No conversion to
another frame (e.g. J2000/GCRF) is needed since every object is propagated
in the same frame — relative distances between objects are valid as-is.

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
└── propagation/
    ├── models.py                  # PropagatedState / PropagationWindow / MultiObjectPropagationWindow
    ├── sgp4_propagator.py         # SGP4 wrapper: single, windowed, and multi-object propagation
    └── catalog.py                 # bridges cached TLEs -> batch propagation
└── risk/
    ├── geodesy.py                  # TEME<->geodetic conversion, GMST, bearing
    └── proximity.py                 # ranking + simplified risk scoring (RED/YELLOW/GREEN)
└── api/
    └── main.py                     # FastAPI: /api/catalog, /api/proximity
apps/web/                           # Vite + React dashboard
├── package.json
├── index.html
├── src/
│   ├── main.jsx
│   └── components/
│       └── OrbitalProximityMonitor.jsx   # Demo/Live toggle, radar scope, risk table
└── data/debris_snapshot.json        # physically-grounded demo fallback data
scripts/
├── fetch_tles.py                  # Phase 1 CLI entry point
└── propagate_catalog.py           # Phase 2 CLI entry point
tests/
├── test_altitude.py               # orbital mechanics sanity checks
├── test_propagation.py            # SGP4 propagation sanity checks (real ISS TLE)
├── test_geodesy.py                # TEME<->geodetic round-trip, bearing correctness
└── test_proximity.py              # risk thresholds, ranking correctness
```

## Roadmap

- [x] **Phase 1 — Data ingestion**: fetch + cache TLEs for a defined altitude band
- [x] **Phase 2 — Propagation**: SGP4 position vectors over a 72-hour window (vectorized, multi-object)
- [x] **Phase 3 — Conjunction detection (single-point) + API + dashboard**: proximity search, simplified risk scoring, FastAPI backend, live React dashboard
- [x] **Phase 3b — True pairwise conjunction detection**: minimum separation between *every pair* of catalog objects (not just user-vs-catalog), over the full propagation window — `risk/pairwise.py`, surfaced at `GET /api/conjunctions`
- [x] **Phase 4 — Pc calculation**: closed-form isotropic-covariance probability of collision — `risk/pc.py` (documented simplification: generic combined covariance, no per-object covariance in TLE data)
- [x] **Phase 5 — 3D trajectory visualization**: true orbit paths via three.js — `GET /api/trajectories` + `OrbitViewer3D.jsx`
- [ ] **SaaS layer**: Postgres/TimescaleDB, auth, multi-user deployment, Next.js migration
