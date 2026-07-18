"""Normalized TLE record — the common shape both data sources get converted into."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_validator


class TLERecord(BaseModel):
    norad_id: int
    name: str
    line1: str
    line2: str
    epoch: datetime  # TLE epoch (when these elements were valid)
    mean_motion: float  # revs/day, parsed from line2
    eccentricity: float  # parsed from line2
    perigee_altitude_km: float
    apogee_altitude_km: float
    source: str  # "spacetrack" or "celestrak"
    fetched_at: datetime

    @field_validator("line1", "line2")
    @classmethod
    def strip_lines(cls, v: str) -> str:
        return v.strip()

    @classmethod
    def now(cls) -> datetime:
        return datetime.now(timezone.utc)
