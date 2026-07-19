"""
Phase 1 verification harness — cross-check the curated Indian asset registry
against live CelesTrak GP data.

For every asset in indian_leo_assets.csv this script:
  1. fetches the current GP record by NORAD ID (CelesTrak, no auth needed),
  2. checks the catalog name matches (loose containment, since CelesTrak
     names differ cosmetically: "CARTOSAT-2F" vs "CARTOSAT 2F"),
  3. recomputes perigee/apogee with the repo's own altitude.py and compares
     against the registry's nominal altitude (±75 km band — generous, since
     nominal values are launch-era and orbits decay/drift),
  4. flags stale TLEs (epoch older than STALE_DAYS) — the plan's Phase 1
     risk indicator for defence assets with degraded tracking,
  5. flags registry assets marked active that CelesTrak has no GP for
     (candidate decays => fix ops_end), and vice versa.

Run from repo root (needs network access to celestrak.org):

    PYTHONPATH=src:. python research/assets/verify_assets.py

Writes a machine-readable report to research/assets/verification_report.csv
and prints a human summary. Exit code 1 if any HARD mismatch (wrong name or
missing GP for an 'active' asset) is found.

Rate-limit etiquette: one query per NORAD ID with a delay, well under
CelesTrak's error-firewall thresholds; 404s are handled without retry storms.
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Repo modules (PYTHONPATH must include src/ and repo root)
from conjunction.ingestion.altitude import perigee_apogee_altitude_km
from research.assets.registry import load_assets

GP_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=json"
STALE_DAYS = 7.0
ALT_TOLERANCE_KM = 75.0
REPORT_PATH = Path(__file__).parent / "verification_report.csv"


def _norm(name: str) -> str:
    return "".join(ch for ch in name.upper() if ch.isalnum())


def fetch_gp(client: httpx.Client, norad_id: int) -> dict | None:
    resp = client.get(GP_URL.format(norad=norad_id))
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if not data or (isinstance(data, dict) and "error" in str(data).lower()):
        return None
    return data[0] if isinstance(data, list) else data


def verify() -> int:
    assets = load_assets()
    rows, hard_failures = [], 0
    now = datetime.now(timezone.utc)

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for a in assets:
            time.sleep(2.0)  # polite spacing; ~27 assets => ~1 minute total
            try:
                gp = fetch_gp(client, a.norad_id)
            except httpx.HTTPError as exc:
                rows.append({"norad_id": a.norad_id, "name": a.name,
                             "check": "fetch", "result": f"ERROR: {exc}"})
                hard_failures += 1
                continue

            if gp is None:
                expected_gone = a.status in ("decayed", "deorbited")
                result = "OK (no GP, matches decayed status)" if expected_gone \
                    else "HARD FAIL: no GP data but registry says " + a.status
                if not expected_gone:
                    hard_failures += 1
                rows.append({"norad_id": a.norad_id, "name": a.name,
                             "check": "existence", "result": result})
                continue

            checks = []

            # 1. Name cross-check
            cat_name = gp.get("OBJECT_NAME", "")
            if _norm(a.name) in _norm(cat_name) or (
                a.aka and _norm(a.aka) in _norm(cat_name)
            ):
                checks.append(("name", f"OK ({cat_name})"))
            else:
                checks.append(("name", f"HARD FAIL: catalog says '{cat_name}'"))
                hard_failures += 1

            # 2. Altitude cross-check via the repo's own math (reuse, per plan)
            try:
                mm = float(gp["MEAN_MOTION"])
                ecc = float(gp["ECCENTRICITY"])
                perigee, apogee = perigee_apogee_altitude_km(mm, ecc)
                mid = (perigee + apogee) / 2.0
                delta = mid - a.nominal_alt_km
                verdict = "OK" if abs(delta) <= ALT_TOLERANCE_KM else "WARN drift"
                checks.append(
                    ("altitude",
                     f"{verdict}: current ~{mid:.0f} km vs nominal "
                     f"{a.nominal_alt_km:.0f} km (delta {delta:+.0f})")
                )
            except (KeyError, ValueError) as exc:
                checks.append(("altitude", f"WARN: could not compute ({exc})"))

            # 3. Inclination cross-check
            try:
                inc = float(gp["INCLINATION"])
                d = abs(inc - a.inclination_deg)
                checks.append(("inclination",
                               f"{'OK' if d <= 1.5 else 'WARN'}: {inc:.2f} deg"))
            except (KeyError, ValueError):
                checks.append(("inclination", "WARN: missing"))

            # 4. TLE staleness (Phase 1 risk flag for defence assets)
            epoch_str = gp.get("EPOCH")
            if epoch_str:
                epoch = datetime.fromisoformat(epoch_str).replace(tzinfo=timezone.utc)
                age = (now - epoch).total_seconds() / 86400.0
                verdict = "OK" if age <= STALE_DAYS else "WARN stale"
                checks.append(("tle_age", f"{verdict}: {age:.1f} days"))

            for check, result in checks:
                rows.append({"norad_id": a.norad_id, "name": a.name,
                             "check": check, "result": result})

    with open(REPORT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["norad_id", "name", "check", "result"])
        writer.writeheader()
        writer.writerows(rows)

    fails = [r for r in rows if "FAIL" in r["result"] or "ERROR" in r["result"]]
    warns = [r for r in rows if "WARN" in r["result"]]
    print(f"Verified {len(assets)} assets -> {REPORT_PATH.name}")
    print(f"  hard failures: {len(fails)}")
    for r in fails:
        print(f"    {r['norad_id']} {r['name']}: {r['result']}")
    print(f"  warnings: {len(warns)}")
    for r in warns:
        print(f"    {r['norad_id']} {r['name']} [{r['check']}]: {r['result']}")
    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(verify())
