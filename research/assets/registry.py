"""
Phase 1 — Indian LEO asset registry.

Loads the curated catalog of Indian LEO primaries (research/assets/
indian_leo_assets.csv) into typed records and answers the two questions the
downstream pipeline needs:

  1. Which NORAD IDs are Indian LEO primaries *at a given historical epoch*?
     (Longitudinal study => the primary set changes over 2019-present:
     Cartosat-2 deorbited 2024, RISAT-2 decayed 2022, SCATSAT-1 retired 2021,
     EOS-07 retired 2024, NISAR arrived 2025, ...)

  2. Does the active set at a reference date agree, to within a small margin,
     with ISSAR's published operational-LEO count? (Sanity bound, per plan.)

Deliberately mirrors src/conjunction conventions (pydantic models, pure
functions, no I/O side effects) so it composes with the existing ingestion
layer without touching it.

Scope notes (mirror these in the paper's Data section):
  - GEO/GSO assets (GSAT/INSAT, NavIC/IRNSS) are excluded by construction.
  - `status == "uncertain"` assets are excluded from the default primary set
    but retained in the registry so the exclusion is explicit and auditable.
  - `defence` assets have public TLEs but unconfirmed operational status;
    they are included by default with a flag, per the plan's Phase 1 risk note.
  - Science LEO (AstroSat, XPoSat) is included only when scope="all_leo",
    matching how ISSAR counts "operational LEO satellites" vs the narrower
    EO-fleet framing. Choose one scope and freeze it in the scope doc.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

ASSETS_CSV = Path(__file__).parent / "indian_leo_assets.csv"

Status = Literal["active", "retired", "decayed", "deorbited", "uncertain"]
Scope = Literal["eo_fleet", "all_leo"]

# Categories counted under the narrower Earth-observation scope.
_EO_CATEGORIES = {
    "EO_optical",
    "EO_ocean",
    "EO_hyperspectral",
    "EO_tech_demo",
    "SAR_EO",
    "altimetry",
    "scatterometry",
    "defence_ELINT",
}


class IndianAsset(BaseModel):
    norad_id: int
    cospar_id: str
    name: str
    aka: str | None = None
    launch_date: date
    ops_end: date | None = None  # None => still operational as of catalog freeze
    status: Status
    regime: Literal["SSO", "inclined_LEO"]
    nominal_alt_km: float
    inclination_deg: float
    category: str
    defence: bool
    joint_mission: str | None = None
    id_confidence: Literal["high", "medium"]
    notes: str | None = None

    @field_validator("aka", "joint_mission", "notes", "ops_end", mode="before")
    @classmethod
    def empty_to_none(cls, v):
        return v or None

    @field_validator("defence", mode="before")
    @classmethod
    def parse_bool(cls, v):
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() == "true"

    def operational_on(self, when: date) -> bool:
        """True if the asset was (plausibly) operational on the given date.

        `uncertain` assets return False: they must be opted into explicitly
        after verification, never silently included.
        """
        if self.status == "uncertain":
            return False
        if when < self.launch_date:
            return False
        if self.ops_end is not None and when > self.ops_end:
            return False
        return True


def load_assets(csv_path: Path = ASSETS_CSV) -> list[IndianAsset]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assets = [IndianAsset(**row) for row in rows]

    norad_ids = [a.norad_id for a in assets]
    if len(norad_ids) != len(set(norad_ids)):
        dupes = {n for n in norad_ids if norad_ids.count(n) > 1}
        raise ValueError(f"Duplicate NORAD IDs in asset catalog: {sorted(dupes)}")
    return assets


def primaries_at(
    when: date,
    scope: Scope = "eo_fleet",
    include_defence: bool = True,
    assets: list[IndianAsset] | None = None,
) -> list[IndianAsset]:
    """The Indian LEO primary set for a given historical epoch.

    This is the function every per-epoch screening run (Phase 3) calls to
    decide which satellites are 'ours' at that snapshot date.
    """
    assets = assets if assets is not None else load_assets()
    out = []
    for a in assets:
        if not a.operational_on(when):
            continue
        if scope == "eo_fleet" and a.category not in _EO_CATEGORIES:
            continue
        if not include_defence and a.defence:
            continue
        out.append(a)
    return sorted(out, key=lambda a: a.norad_id)


def norad_ids_at(when: date, **kwargs) -> list[int]:
    return [a.norad_id for a in primaries_at(when, **kwargs)]


def issar_sanity_check(
    reference_date: date,
    issar_operational_leo_count: int,
    tolerance: int = 6,
) -> tuple[bool, str]:
    """Compare our active all-LEO count against ISSAR's published figure.

    ISSAR counts are aggregate and their inclusion rules are not fully
    published (student/commercial sats, defence assets, science payloads),
    so this is an order-of-magnitude sanity bound, not an equality test —
    consistent with the plan's 'corroboration, not calibration' posture.
    """
    ours = len(primaries_at(reference_date, scope="all_leo"))
    ok = abs(ours - issar_operational_leo_count) <= tolerance
    msg = (
        f"registry active LEO count at {reference_date}: {ours}; "
        f"ISSAR reports {issar_operational_leo_count}; "
        f"|delta| {'<=' if ok else '>'} tolerance {tolerance}"
    )
    return ok, msg
