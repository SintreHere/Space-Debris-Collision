"""
Phase 3/4 — Conjunction detection (single-point form) & risk scoring.

Given a user-simulated position and a set of propagated catalog objects at
the same instant, rank objects by distance and assign a simplified risk
score/level. This is the single-point version of what full pairwise
conjunction detection does between two orbiting objects — here one "object"
is the user-simulated position instead of a second TLE.

Thresholds and scoring formula match the dashboard's original client-side
implementation exactly, so results are identical whether computed here
(now the source of truth) or previously in the browser.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from conjunction.risk.geodesy import bearing_deg, geodetic_to_teme

# Real operators use ~1km as a serious-attention threshold and up to ~25km
# as a NASA/ESA-style screening volume — see project README. RED_KM is set
# slightly above the 1km serious-attention point to keep the demo's "close
# encounter" presets comfortably inside the red band.
RED_KM = 5.0
YELLOW_KM = 25.0
RISK_DECAY_KM = 15.0  # controls how fast the score falls off with distance


@dataclass
class RiskAssessment:
    norad_id: int
    name: str
    kind: str
    altitude_km: float
    lat: float
    lon: float
    distance_km: float
    bearing_deg: float
    alt_diff_km: float
    risk_score: float
    risk_level: str  # "red" | "yellow" | "green"


def risk_from_distance(distance_km: float) -> tuple[float, str]:
    score = math.exp(-distance_km / RISK_DECAY_KM)
    level = "red" if distance_km < RED_KM else "yellow" if distance_km < YELLOW_KM else "green"
    return score, level


def _distance_km(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def compute_proximity(
    objects: list[dict],
    user_lat: float,
    user_lon: float,
    user_altitude_km: float,
    at: datetime,
) -> list[RiskAssessment]:
    """
    `objects` is a list of dicts with at least:
        norad_id, name, kind, altitude_km, lat, lon
    (i.e. already-propagated, geodetic-converted positions — see
    conjunction.api.main for how the catalog is prepared).

    Returns all objects ranked nearest-first.
    """
    user_teme = geodetic_to_teme(user_lat, user_lon, user_altitude_km, at)

    assessments = []
    for obj in objects:
        obj_teme = geodetic_to_teme(obj["lat"], obj["lon"], obj["altitude_km"], at)
        dist = _distance_km(user_teme, obj_teme)
        bearing = bearing_deg(user_lat, user_lon, obj["lat"], obj["lon"])
        score, level = risk_from_distance(dist)

        assessments.append(
            RiskAssessment(
                norad_id=obj["norad_id"],
                name=obj["name"],
                kind=obj.get("kind", "tracked_object"),
                altitude_km=obj["altitude_km"],
                lat=obj["lat"],
                lon=obj["lon"],
                distance_km=dist,
                bearing_deg=bearing,
                alt_diff_km=obj["altitude_km"] - user_altitude_km,
                risk_score=score,
                risk_level=level,
            )
        )

    assessments.sort(key=lambda a: a.distance_km)
    return assessments
