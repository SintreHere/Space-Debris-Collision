# Phase 2 Runbook — Historical Data Acquisition (`gp_history`)

The schedule-critical phase. Everything here is built, tested (10 new tests,
42 total), and dry-runnable offline — but the actual multi-day download runs
on **your** machine with **your** Space-Track credentials.

## What was added

```
research/history/
├── models.py            # GPRecord — OMM/JSON-native, 6-digit-ID safe,
│                        #   carries OBJECT_TYPE/COUNTRY_CODE for Phase 4
├── snapshots.py         # quarterly snapshot plan + THE epoch-selection
│                        #   policy (nearest-TLE-to-target, ±2-day window)
├── ratelimit.py         # sliding-window governor: 20/min, 250/hr
│                        #   (margin under Space-Track's 30/300 caps)
├── client.py            # GPHistoryClient — paginated full-catalog window
│                        #   pulls + comma-list primary histories; never
│                        #   per-object loops; injectable transport
├── store.py             # data/gp_history.db — epoch-indexed SQLite with
│                        #   snapshot_meta resumability ledger; optional
│                        #   parquet export (pandas+pyarrow)
├── downloader.py        # CLI orchestrator with --dry-run
└── probe_2019_depth.py  # 3-request go/no-go probe (Recommendation 2)
tests/test_history.py    # 10 tests, all offline (fake transports)
```

## Order of operations

### Step 1 — Dry run (offline, do this first)

```bash
PYTHONPATH=src:. python -m research.history.downloader --dry-run
```

Prints the full request plan: 31 quarterly snapshot windows (2019Q1–2026Q3)
plus 8 primary-history year-chunks covering all 26 registry objects —
39 requests minimum before pagination. No network, no writes.

### Step 2 — De-risk probe (3 requests, needs credentials)

Credentials go in `.env` at the repo root (same as the operational app):

```
SPACETRACK_USERNAME=you@example.com
SPACETRACK_PASSWORD=...
```

Then:

```bash
PYTHONPATH=src:. python -m research.history.probe_2019_depth
```

The probe answers the plan's go/no-go questions: (Q1) does `gp_history`
reach Jan 2019 (Cartosat-2F test), (Q2) how many rows is one full-catalog
snapshot window (columns restricted to keep the payload tiny), (Q3) are the
defence primaries (RISAT-2B, EMISAT) present at depth.

**Decision rule:** extrapolate Q2's row count × 31 snapshots. If the implied
rate-limited download exceeds ~2 weeks, fall back to annual cadence
(`--cadence annual`, 8 snapshots) — the plan's pre-committed degraded mode.

### Step 3 — Bulk download (budget days, not hours)

```bash
PYTHONPATH=src:. python -m research.history.downloader
```

Behavior you should expect:
- Snapshots run **oldest-first**, so the riskiest data (2019) is validated
  in the first hour, not on day three.
- The limiter blocks (it does not error) when the budget is spent; long
  silences in the log with "Rate limiter slept Ns" lines are normal.
- **Interruptions are safe.** Ctrl-C, network drop, laptop sleep — re-run the
  same command and completed snapshots are skipped via the `snapshot_meta`
  ledger. At most one snapshot is re-fetched.
- Useful flags: `--only 2019Q1 2019Q2` (subset), `--skip-primaries`,
  `--skip-snapshots`, `--cadence annual`, `--db path/to.db`.

### Step 4 — Verify what landed

```bash
PYTHONPATH=src:. python - <<'EOF'
from pathlib import Path
from research.history.store import completed_snapshots, load_snapshot
db = Path("data/gp_history.db")
done = sorted(completed_snapshots(db))
print(f"{len(done)} snapshots complete: {done}")
if done:
    rows = load_snapshot(db, done[0])
    print(f"{done[0]}: {len(rows)} objects, "
          f"IDs {rows[0]['norad_id']}..{rows[-1]['norad_id']}")
EOF
```

Sanity expectations: early-2019 snapshots should hold roughly 8–12k LEO
objects, growing steadily to ~25–35k+ by 2026 (Starlink era). If a snapshot
is suspiciously small, delete its row from `snapshot_meta` and re-run to
re-fetch it.

Optional parquet export for analysis notebooks:

```bash
pip install pandas pyarrow
PYTHONPATH=src:. python -c "
from pathlib import Path
from research.history.store import export_snapshot_parquet
print(export_snapshot_parquet(Path('data/gp_history.db'), '2019Q1', Path('data/parquet')))
"
```

## Design decisions locked in this phase (cite in the paper's Data section)

1. **Epoch-selection policy**: quarterly targets (Jan/Apr/Jul/Oct 1, 00:00
   UTC), ±2-day windows, one elset per object nearest to target, earlier
   elset on ties. Documented in `snapshots.py`'s module docstring verbatim.
2. **OMM/JSON throughout** (Recommendation 6): no fixed-width TLE parsing
   anywhere in the research layer. Objects ≥100000 (post 2026-07-11
   rollover) parse cleanly with null TLE lines; Phase 3 will initialize
   SGP4 from mean elements via `sgp4.omm` for those.
3. **Attribution fields captured now**: OBJECT_TYPE and COUNTRY_CODE ride
   along on every record, so Phase 4 needs zero re-downloading.
4. **Primaries get full histories**, not windowed snapshots — pulled as
   comma-list year-chunks. This also pins the approximate `ops_end` dates
   (EOS-07, SCATSAT-1) from the elset record itself, closing a Phase 1
   risk-register item.
5. **LEO net**: `MEAN_MOTION > 11`, `ECCENTRICITY < 0.25`, matching the
   operational ingestion layer's wide-net-then-filter-locally policy.

## Known limitations / carried risks

- Space-Track may throttle or 500 sporadically during multi-hour pulls even
  under the caps; the resumability ledger is the mitigation. Do not tighten
  the limiter above 25/min.
- CelesTrak SupGP integration for the current-state window (plan Phase 2,
  last item) is deliberately deferred to a small follow-up once the
  Space-Track backbone download is confirmed working — it's an accuracy
  enhancement for the "now" analysis, not a dependency of the historical RQs.
- The ±2-day window can miss sparsely-tracked *secondary* objects at a given
  snapshot; this is a documented completeness limitation, quantifiable later
  by comparing snapshot object counts against `satcat` decay-filtered counts.

## Exit checklist

- [ ] Probe run; 2019 depth confirmed; cadence decision recorded
      (quarterly vs annual) with the Q2 volume numbers pasted into the log
- [ ] Bulk download complete: `completed_snapshots()` returns all planned labels
- [ ] Primary histories present (`__primary_history__` label rows > 0)
- [ ] Snapshot object counts eyeballed for the growth trend (no empty/tiny epochs)
- [ ] EOS-07 / SCATSAT-1 `ops_end` refined in `indian_leo_assets.csv` from
      their last-elset dates; Phase 1 tests re-run green
- [ ] Commit + push

Then Phase 3: the staged filter cascade (coarse 60 s pre-filter → apogee/
perigee overlap → coarse min-distance → TCA refinement) wrapped as batch
jobs over these snapshots.
