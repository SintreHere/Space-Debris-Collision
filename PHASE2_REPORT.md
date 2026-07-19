# Phase 2 Status Report — Historical Data Acquisition (`gp_history`)

**Date:** 2026-07-19 · **Runbook:** [PHASE2_RUNBOOK.md](PHASE2_RUNBOOK.md) · **Status: BULK DOWNLOAD IN PROGRESS** (all gates passed)

## 1. Delivered & integrated

`research/history/` package (7 modules) + `tests/test_history.py`, merged from
the Phase 2 staging drop:

| Module | Role |
|---|---|
| `models.py` | `GPRecord` — OMM/JSON-native, 6-digit-ID safe, carries OBJECT_TYPE / COUNTRY_CODE for Phase 4 |
| `snapshots.py` | Quarterly snapshot plan + epoch-selection policy (nearest-TLE-to-target, ±2-day window) |
| `ratelimit.py` | Sliding-window governor: 20/min, 250/hr (margin under Space-Track's 30/300) |
| `client.py` | Paginated full-catalog window pulls + comma-list primary histories |
| `store.py` | `data/gp_history.db` — epoch-indexed SQLite with `snapshot_meta` resumability ledger |
| `downloader.py` | CLI orchestrator with `--dry-run`, oldest-first ordering |
| `probe_2019_depth.py` | 3-request go/no-go probe |

**Tests: 42/42** (10 new, all offline) · ruff clean — matching runbook predictions exactly.

## 2. Step 1 — Dry run ✅

Request plan verified offline: **31 quarterly snapshots** (2019Q1–2026Q3) +
**8 primary-history year-chunks** covering all 26 registry objects = 39
requests minimum before pagination.

## 3. Step 2 — De-risk probe ✅ (3 live requests)

| Question | Result |
|---|---|
| Q1 — does `gp_history` reach Jan 2019? | **CONFIRMED** — 22 elsets for Cartosat-2F (43111) in the first week of 2019 |
| Q2 — full-catalog window volume | **88,330 elset rows / 13,382 distinct LEO objects** in the 2019Q1 ±2-day window → ~2.74M rows extrapolated across 31 snapshots (higher with 2026-era growth) |
| Q3 — defence primaries at depth | **Present** — EMISAT (44078): 122 elsets; RISAT-2B (44233): 83 elsets, June 2019 |

## 4. Cadence decision — QUARTERLY (recorded per decision rule)

At the client's 50,000-row page size, ~2.7–5M total rows ≈ **60–100 paginated
requests**, far inside the 250/hr limiter cap → implied wall time is **hours,
not weeks**. The ~2-week annual-fallback threshold is not approached.
**Quarterly cadence locked.**

## 5. Step 3 — Bulk download (running)

Started 2026-07-19 18:50 IST, oldest-first, logging to `data/gp_download.log`,
resumable via the `snapshot_meta` ledger. Early progress confirms the
runbook's sanity expectations (8–12k objects for early 2019):

| Snapshot | Raw elsets | Objects after nearest-epoch dedupe |
|---|---|---|
| 2019Q1 | 88,330 | 13,382 |
| 2019Q2 | 67,421 | 12,773 |

Observed pace ≈ 1 snapshot/minute → full plan expected in well under 2 hours.
A monitor is armed on the log for per-snapshot completions and failures.

## 6. Remaining (exit checklist)

- [x] Probe run; 2019 depth confirmed; cadence decision recorded with Q2 numbers
- [ ] Bulk download complete (`completed_snapshots()` returns all 31 labels)
- [ ] Primary histories present (`__primary_history__` rows > 0)
- [ ] Snapshot growth trend eyeballed (no empty/tiny epochs)
- [ ] EOS-07 / SCATSAT-1 `ops_end` refined from last-elset dates; Phase 1 tests re-run
- [ ] Commit + push (push additionally gated on GitHub signing-key registration — see Phase 1 report)

Then Phase 3: the staged filter cascade over these snapshots.
