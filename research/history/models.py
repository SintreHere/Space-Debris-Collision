"""
Phase 2 — historical GP record model.

OMM/JSON-native (per plan Recommendation 6): the record is built from
Space-Track `gp_history` JSON fields, NOT from fixed-width TLE parsing, so it
survives the July 2026 catalog-number rollover — objects with NORAD IDs
>= 100000 have no TLE representation (`TLE_LINE1/2` will be null in the feed)
but carry full mean elements, which is all SGP4 needs (Phase 3 initializes
Satrec objects from OMM fields via `sgp4.omm` when TLE lines are absent).

We also capture OBJECT_TYPE and COUNTRY_CODE *now*, even though they are not
needed until Phase 4 (threat attribution), so attribution never requires a
second multi-week download pass.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_validator

from conjunction.ingestion.altitude import perigee_apogee_altitude_km


class GPRecord(BaseModel):
    norad_id: int  # int, unbounded — 6/9-digit safe by construction
    object_name: str | None = None
    object_type: str | None = None  # PAYLOAD / ROCKET BODY / DEBRIS / UNKNOWN (Phase 4)
    country_code: str | None = None  # Phase 4 attribution
    intl_designator: str | None = None
    epoch: datetime
    mean_motion: float  # rev/day
    eccentricity: float
    inclination_deg: float | None = None
    raan_deg: float | None = None
    arg_pericenter_deg: float | None = None
    mean_anomaly_deg: float | None = None
    bstar: float | None = None
    perigee_altitude_km: float
    apogee_altitude_km: float
    tle_line1: str | None = None  # null for 100000+ objects — do not require
    tle_line2: str | None = None
    source: str = "spacetrack_gp_history"
    fetched_at: datetime

    @field_validator("epoch", "fetched_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def gp_record_from_omm_json(row: dict, fetched_at: datetime | None = None) -> GPRecord:
    """Build a GPRecord from one Space-Track gp/gp_history JSON object.

    Space-Track returns all values as strings; missing values are None or "".
    Altitudes are derived locally from mean motion + eccentricity using the
    repo's altitude.py (same policy as the operational ingestion layer).
    """
    mm = float(row["MEAN_MOTION"])
    ecc = float(row["ECCENTRICITY"])
    perigee, apogee = perigee_apogee_altitude_km(mm, ecc)

    def _f(key: str) -> float | None:
        v = row.get(key)
        return float(v) if v not in (None, "") else None

    def _s(key: str) -> str | None:
        v = row.get(key)
        return v if v not in (None, "") else None

    epoch_raw = row["EPOCH"]
    epoch = datetime.fromisoformat(epoch_raw)
    if epoch.tzinfo is None:
        epoch = epoch.replace(tzinfo=timezone.utc)

    return GPRecord(
        norad_id=int(row["NORAD_CAT_ID"]),
        object_name=_s("OBJECT_NAME"),
        object_type=_s("OBJECT_TYPE"),
        country_code=_s("COUNTRY_CODE"),
        intl_designator=_s("OBJECT_ID"),
        epoch=epoch,
        mean_motion=mm,
        eccentricity=ecc,
        inclination_deg=_f("INCLINATION"),
        raan_deg=_f("RA_OF_ASC_NODE"),
        arg_pericenter_deg=_f("ARG_OF_PERICENTER"),
        mean_anomaly_deg=_f("MEAN_ANOMALY"),
        bstar=_f("BSTAR"),
        perigee_altitude_km=perigee,
        apogee_altitude_km=apogee,
        tle_line1=_s("TLE_LINE1"),
        tle_line2=_s("TLE_LINE2"),
        fetched_at=fetched_at or datetime.now(timezone.utc),
    )
