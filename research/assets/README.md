# Phase 1 — Indian LEO Asset Registry

Authoritative NORAD-ID list for Indian LEO primaries, 2019–present, per the
phased implementation plan. This directory is the single source of truth for
"which satellites are ours at epoch T" for every downstream screening run.

## Files
- `indian_leo_assets.csv` — curated catalog (27 objects) with operational
  windows, regime, category, defence/joint-mission flags, and per-row notes.
- `registry.py` — typed loader; `primaries_at(date, scope, include_defence)`
  returns the epoch-correct primary set; `issar_sanity_check()` compares the
  active count against ISSAR's published operational-LEO figure.
- `verify_assets.py` — live cross-check against CelesTrak GP data (name,
  altitude via the repo's own `altitude.py`, inclination, TLE staleness).
  Requires network; run before freezing the catalog:
  `PYTHONPATH=src:. python research/assets/verify_assets.py`
- `../../tests/test_asset_registry.py` — 8 tests covering integrity,
  epoch-awareness, scope/defence toggles, and the ISSAR sanity bound.

## Key design decision: operational windows, not a flat list
Because the study is longitudinal (Jan 2019 → present), the primary set is a
function of the snapshot date. Fleet changes captured:
- **Cartosat-2** (29710): controlled deorbit completed 2024-02-14.
- **RISAT-2** (34807): uncontrolled reentry 2022-10-30.
- **SCATSAT-1** (41790): mission ended ~Feb 2021 (verify exact date).
- **EOS-07** (55562): deactivated late 2024 (approx; verify decay epoch).
- **NISAR** (65053, 2025-163A): launched 2025-07-30, 747 km SSO, 98.4°.
- **EOS-08** (60454, 2024-147A): note the correct SATCAT is **60454**;
  1-year design life expired Aug 2025, status flagged `uncertain`.

## Explicit exclusions (state these in the paper's Data section)
- **GEO/GSO**: all GSAT/INSAT and NavIC/IRNSS — out of LEO scope.
- **EOS-02**: lost on SSLV-D1 failure (Aug 2022); never cataloged operational.
- **EOS-09 / RISAT-1B**: lost on PSLV-C61 failure (May 2025).
- **Microsat-R**: destroyed March 2019 (Mission Shakti target).
- **RISAT-1**: power failure 2016; non-operational before the study window.
- **SPADEX A/B and other short-lived tech demos**: sub-quarter mission
  durations, negligible exposure contribution; document if reviewers ask.

## `uncertain` status (excluded from primaries by default)
- **Cartosat-2A (32783) / Cartosat-2B (36795)**: in orbit, but operational
  status through the study window is not publicly confirmed.
- **Oceansat-2 (35931)**: scatterometer failed 2014; residual operations unclear.
- **EOS-08 (60454)**: design life expired; mid-2026 status unconfirmed.
Resolve these against ISSAR aggregate counts and, if possible, ISRO/IS4OM
correspondence, then flip status and re-run tests.

## Sanity bound vs ISSAR
ISSAR 2025 reports 22 operational Indian LEO satellites (with 31 GEO); note
some secondary summaries of ISSAR 2025 cite 27 operational of 86 total Indian
LEO objects — the discrepancy likely reflects differing inclusion rules
(student/commercial/defence payloads). Our all-LEO active set at 2025-12-31 is
18, within the ±6 tolerance of the 22 figure. Treat this as corroboration,
not calibration, per plan Recommendation 3. The gap is consistent with our
deliberate `uncertain` exclusions plus commercial/student satellites we do
not model as primaries.

## Phase 1 risk register (carried forward)
- Defence assets (EMISAT, RISAT-2B family, Cartosat-2C) have public TLEs but
  unconfirmed ops status; `verify_assets.py` flags TLE staleness > 7 days as
  the degradation indicator the plan calls for.
- Several ops_end dates are approximate (month precision). Phase 2's
  `gp_history` pulls should refine EOS-07 and SCATSAT-1 end dates from the
  TLE record itself (decay epoch / last-elset date).
- NISAR is jointly operated (NASA/ISRO); include as an Indian-operated
  primary with an explicit caveat, or run results with/without it as a
  robustness check.
- Verification findings, 2026-07-19 run (`verification_report.csv`):
  - OCEANSAT-2 (35931): live altitude ~895 km vs nominal 720 km (+175).
    Upward drift is not physical for a passive LEO object — possible catalog
    anomaly or registry nominal error; resolve via gp_history in Phase 2.
    Asset is already `uncertain`/excluded, so no primary-set impact.
  - SCATSAT-1 (41790): ~631 km vs nominal 720 km (−89) — natural post-EOL
    decay, consistent with retired-2021 status; refine ops_end in Phase 2.
  - XPOSAT (58694): TLE 9.7 days stale at run time — the degraded-tracking
    flag; transient, re-check on the next verification run.
  - EOS-07 (55562): absent from live catalog — status corrected retired →
    decayed in this run; decay epoch to be pinned from gp_history (Phase 2).
