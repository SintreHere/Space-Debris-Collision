# Phase 1 Runbook — Indian LEO Asset Registry

Step-by-step instructions to set up, run, and verify everything delivered in
Phase 1 of the India LEO conjunction-exposure study, on your own machine.

---

## 1. Prerequisites

- **Python 3.11+** (repo requirement; 3.12 also works)
- **Git**
- Network access to `celestrak.org` (only needed for the verification script
  in Step 6 — everything else runs offline)

Check your Python version:

```bash
python --version
```

---

## 2. Get the code

If you don't have the repo cloned yet:

```bash
git clone https://github.com/SintreHere/Space-Debris-Collision.git
cd Space-Debris-Collision
```

Then unzip `phase1_indian_asset_registry.zip` **at the repo root**. It adds:

```
Space-Debris-Collision/
├── research/
│   ├── __init__.py
│   └── assets/
│       ├── __init__.py
│       ├── README.md                 # provenance, exclusions, risk register
│       ├── indian_leo_assets.csv     # the curated asset catalog (27 objects)
│       ├── registry.py               # loader + primaries_at() + ISSAR check
│       └── verify_assets.py          # live CelesTrak cross-check
└── tests/
    └── test_asset_registry.py        # 8 new tests
```

On Linux/macOS, from the directory containing the zip:

```bash
unzip phase1_indian_asset_registry.zip -d .
# The zip contains the Space-Debris-Collision/ prefix, so extract next to
# (not inside) your clone, or merge the extracted folder into your clone:
cp -r Space-Debris-Collision/research /path/to/your/clone/
cp Space-Debris-Collision/tests/test_asset_registry.py /path/to/your/clone/tests/
```

---

## 3. Set up the environment

From the repo root, using a virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .                   # installs the repo package + deps
pip install pytest httpx pydantic  # if not already pulled in by the above
```

If `pip install -e .` gives trouble, the minimal dependency set for Phase 1 is:

```bash
pip install pydantic httpx pytest sgp4 numpy
```

---

## 4. Set PYTHONPATH

The `research/` package lives at the repo root and imports from
`src/conjunction/`, so both must be on the path. All commands below assume
you are **in the repo root**.

Linux/macOS:

```bash
export PYTHONPATH=src:.
```

Windows (PowerShell):

```powershell
$env:PYTHONPATH = "src;."
```

(Alternatively, prefix each command with `PYTHONPATH=src:.` as shown below.)

---

## 5. Run the tests (offline)

Run just the new Phase 1 tests:

```bash
PYTHONPATH=src:. python -m pytest tests/test_asset_registry.py -v
```

Expected: **8 passed**. These check catalog integrity (unique NORAD IDs, LEO
altitude bounds), epoch-awareness (Cartosat-2 deorbit, RISAT-2 decay, NISAR
arrival), the `uncertain`-status exclusion rule, scope and defence toggles,
and the ISSAR 2025 sanity bound.

Run the full suite (existing repo tests + Phase 1):

```bash
PYTHONPATH=src:. python -m pytest -q
```

Expected: **32 passed**.

---

## 6. Run the live verification script (needs network)

This cross-checks every registry entry against current CelesTrak GP data:
name match, current altitude (recomputed with the repo's own `altitude.py`),
inclination, and TLE staleness. It is rate-limit polite (one query per object,
2-second spacing, ~1 minute total for 27 objects).

```bash
PYTHONPATH=src:. python research/assets/verify_assets.py
```

Outputs:

- A human-readable summary printed to the terminal
- A machine-readable report at `research/assets/verification_report.csv`
- **Exit code 0** if clean, **1** if any hard failure

How to read the results:

| Result | Meaning | Action |
|---|---|---|
| `OK` | Registry entry matches the live catalog | None |
| `WARN drift` | Current altitude differs from nominal by >75 km | Usually natural decay/drift; update `nominal_alt_km` if large |
| `WARN stale` | TLE epoch older than 7 days | The plan's degraded-tracking flag — expected occasionally for defence assets; note it in the risk register |
| `HARD FAIL: catalog says '...'` | Name mismatch — possible wrong NORAD ID | Fix the CSV row before proceeding to Phase 2 |
| `HARD FAIL: no GP data but registry says active` | Object missing from catalog | Likely decayed — set `ops_end` and `status` in the CSV |
| `OK (no GP, matches decayed status)` | Decayed object correctly absent | None |

After fixing any CSV rows, re-run Step 5 to confirm tests still pass.

---

## 7. Use the registry (quick sanity demo)

Print the primary set at any study epoch:

```bash
PYTHONPATH=src:. python -c "
from datetime import date
from research.assets.registry import primaries_at
for y in (2019, 2021, 2023, 2026):
    ps = primaries_at(date(y, 7, 1), scope='all_leo')
    print(y, len(ps), [a.name for a in ps])
"
```

Key API (this is what Phase 3 screening jobs will call):

```python
from datetime import date
from research.assets.registry import primaries_at, norad_ids_at, issar_sanity_check

# Epoch-correct primary set
assets = primaries_at(date(2023, 7, 1))                     # EO fleet, defence included
ids    = norad_ids_at(date(2023, 7, 1), scope="all_leo")    # just the NORAD IDs
eo_civ = primaries_at(date(2023, 7, 1), include_defence=False)

# ISSAR corroboration
ok, msg = issar_sanity_check(date(2025, 12, 31), issar_operational_leo_count=22)
print(msg)
```

Notes:
- `scope="eo_fleet"` (default) excludes science satellites (AstroSat, XPoSat);
  `scope="all_leo"` includes them. **Pick one and freeze it in the scope doc.**
- Assets with `status = uncertain` (Cartosat-2A/2B, Oceansat-2, EOS-08) are
  never returned. To include one, verify its status first, then change its
  `status` in the CSV and re-run the tests.

---

## 8. Lint (repo convention)

```bash
pip install ruff
python -m ruff check research/ tests/test_asset_registry.py
```

Expected: no errors.

---

## 9. Phase 1 exit checklist

- [ ] Full test suite passes (32 tests)
- [ ] `verify_assets.py` run with exit code 0; `verification_report.csv` reviewed
- [ ] Any `WARN stale` defence assets noted in the risk register
- [ ] Scope decision frozen: `eo_fleet` vs `all_leo` (AstroSat/XPoSat in or out)
- [ ] `uncertain` assets resolved or explicitly documented as excluded
- [ ] Approximate `ops_end` dates (EOS-07, SCATSAT-1) flagged for refinement
      from `gp_history` in Phase 2
- [ ] Changes committed: `git add research/ tests/test_asset_registry.py && git commit -m "Phase 1: Indian LEO asset registry"`

Once checked, you're clear to start Phase 2 (historical `gp_history`
acquisition — the schedule-critical item).

---

## Troubleshooting

- **`ModuleNotFoundError: conjunction` or `research`** — PYTHONPATH isn't set
  or you're not in the repo root. See Step 4.
- **`ValidationError` when loading the CSV** — a row was edited with a bad
  date format. Dates must be `YYYY-MM-DD`; empty means "still operational".
- **`httpx.HTTPError` / timeouts in verify_assets.py** — CelesTrak may be
  rate-limiting or down. Wait and retry; do not loop retries (CelesTrak
  blocks IPs after repeated errors in a 2-hour window).
- **Verification says an "active" asset has no GP data** — it probably
  decayed after the catalog was compiled. Set `status` to `decayed` and
  `ops_end` to the decay date (Phase 2 tooling will pin this precisely).
