"""
Derive orbital altitude band (perigee/apogee) from classic TLE mean elements.

Space-Track's GP class and CelesTrak's GP feed don't let you query directly
by "altitude" — you query by orbital elements. Mean motion (revs/day) and
eccentricity are always present on every TLE, so we compute semi-major axis
via Kepler's third law and derive perigee/apogee altitude from that. This is
standard orbital mechanics, not a simplifying hack.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6378.137  # WGS84 equatorial radius
EARTH_MU_KM3_S2 = 398600.4418  # standard gravitational parameter, km^3/s^2
SECONDS_PER_DAY = 86400.0


def semi_major_axis_km(mean_motion_rev_per_day: float) -> float:
    """Kepler's third law: a = (mu / n^2)^(1/3), with n in rad/s."""
    n_rad_per_s = mean_motion_rev_per_day * 2 * math.pi / SECONDS_PER_DAY
    return (EARTH_MU_KM3_S2 / (n_rad_per_s**2)) ** (1.0 / 3.0)


def perigee_apogee_altitude_km(
    mean_motion_rev_per_day: float, eccentricity: float
) -> tuple[float, float]:
    """Returns (perigee_altitude_km, apogee_altitude_km) above the WGS84 surface."""
    a = semi_major_axis_km(mean_motion_rev_per_day)
    perigee_radius = a * (1 - eccentricity)
    apogee_radius = a * (1 + eccentricity)
    return (perigee_radius - EARTH_RADIUS_KM, apogee_radius - EARTH_RADIUS_KM)


def in_altitude_band(
    mean_motion_rev_per_day: float,
    eccentricity: float,
    band_min_km: float,
    band_max_km: float,
) -> bool:
    """
    True if the object's orbit overlaps the given altitude band at any point
    (i.e. perigee or apogee — or the whole range — falls inside the band).
    Using overlap rather than strict containment because a conjunction can
    happen anywhere the orbit passes through the band, not just at perigee/apogee.
    """
    perigee_alt, apogee_alt = perigee_apogee_altitude_km(mean_motion_rev_per_day, eccentricity)
    return perigee_alt <= band_max_km and apogee_alt >= band_min_km
