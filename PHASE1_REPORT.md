# Phase 1 Completion Report — Indian LEO Asset Registry

**Date:** 2026-07-19 · **Runbook:** [PHASE1_RUNBOOK.md](PHASE1_RUNBOOK.md) · **Status: COMPLETE** (commit signed locally; push pending GitHub signing-key registration)

## 1. Scope delivered

A curated, epoch-aware registry of Indian LEO assets (27 objects) to serve as
the primary set for the India LEO conjunction-exposure study, with programmatic
selection API, live-catalog verification tooling, and test coverage.

| Artifact | Location |
|---|---|
| Asset catalog (27 objects) | `research/assets/indian_leo_assets.csv` |
| Registry API (`primaries_at`, `norad_ids_at`, `issar_sanity_check`) | `research/assets/registry.py` |
| Live CelesTrak verification script | `research/assets/verify_assets.py` |
| Verification evidence | `research/assets/verification_report.csv` |
| Provenance / exclusions / risk register | `research/assets/README.md` |
| Test suite (8 tests) | `tests/test_asset_registry.py` |

## 2. Verification results

**Tests:** 8/8 Phase 1 tests pass · full repo suite **32/32** · ruff clean.

**Live CelesTrak cross-check** (26 fetchable assets, name/altitude/inclination/staleness):

*Run 1* surfaced 2 hard failures, both resolved as data corrections:

| Finding | Resolution |
|---|---|
| EOS-04 (51656): catalog names it `EOS-4` | Added `aka=EOS-4`; RISAT-1A designation moved to notes |
| EOS-07 (55562): no GP data but status said `retired` | Status corrected to `decayed` — object reentered from its 450 km orbit; decay epoch to be pinned from `gp_history` in Phase 2 |

*Run 2 (final):* **0 hard failures, exit code 0.** Three warnings remain, all
recorded in the risk register (`research/assets/README.md`):

- **OCEANSAT-2 (35931):** live ~895 km vs nominal 720 km (+175). Upward drift is
  unphysical for a passive object — flagged as possible catalog/registry anomaly
  for Phase 2; asset is `uncertain`/excluded, so no primary-set impact.
- **SCATSAT-1 (41790):** ~631 km vs nominal 720 km (−89) — natural post-EOL decay,
  consistent with retirement in 2021.
- **XPOSAT (58694):** TLE 9.7 days stale at run time — transient degraded-tracking flag.

## 3. Registry behaviour (epoch-awareness demo, `scope=all_leo`)

| Epoch | Primaries | Notable membership changes |
|---|---|---|
| 2019-07-01 | 14 | CARTOSAT-2 and RISAT-2 present; SCATSAT-1 active |
| 2021-07-01 | 16 | RISAT-2 still in; CARTOSAT-3 / RISAT-2BR1 / EOS-01 arrived; SCATSAT-1 retired |
| 2023-07-01 | 18 | EOS-04/-06/-07 in; RISAT-2 decayed out |
| 2026-07-01 | 18 | CARTOSAT-2 (deorbited 2024) and EOS-07 (decayed) out; XPOSAT and NISAR in |

`uncertain`-status assets (CARTOSAT-2A/2B, OCEANSAT-2, EOS-08) are never
returned, per the exclusion rule.

## 4. Exit checklist

- [x] Full test suite passes (32)
- [x] `verify_assets.py` exit code 0; `verification_report.csv` reviewed
- [x] `WARN stale` (XPOSAT) and drift warnings noted in risk register
- [ ] **OPEN — scope freeze:** `eo_fleet` vs `all_leo` (AstroSat/XPoSat in or out) — study-design decision, owner: you
- [x] `uncertain` assets explicitly documented as excluded
- [x] Approximate ops_end dates (EOS-07, SCATSAT-1) flagged for Phase 2 `gp_history` refinement
- [x] Committed: `7f15316` "Phase 1: Indian LEO asset registry" (SSH-signed) — **push pending** GitHub signing-key registration (repo ruleset requires verified signatures + PR flow)

## 5. Next

Phase 2 — historical `gp_history` acquisition (schedule-critical): refine
EOS-07 decay epoch and SCATSAT-1 EOL, resolve the OCEANSAT-2 altitude anomaly,
then the screening jobs consume `primaries_at()` for the frozen scope.
