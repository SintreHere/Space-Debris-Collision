"""
Geodesy helpers bridging SGP4's native TEME (True Equator, Mean Equinox)
output and Earth-fixed geodetic coordinates (lat/lon/altitude) — needed so
a user-simulated ground/orbit position (given in lat/lon/altitude) can be
compared against propagated TEME object positions.

Simplifying assumption (stated per project convention): Earth is treated
as a sphere of radius EARTH_RADIUS_KM, not the WGS84 ellipsoid. This is
the same assumption already used in ingestion/altitude.py for perigee/
apogee altitude, so it's consistent across the whole pipeline, not a new
approximation. It introduces at most ~0.3% radius error (the WGS84
flattening), which doesn't materially affect close-approach screening at
the km scale conjunction detection operates at.
"""

from __future__ import annotations

import math
from datetime import datetime

EARTH_RADIUS_KM = 6378.137


def gmst_deg(dt: datetime) -> float:
    """Greenwich Mean Sidereal Time, in degrees, via the standard IAU 1982
    approximation. This is what rotates the inertial TEME frame into the
    Earth-fixed ECEF frame at a given instant."""
    jd = (
        367 * dt.year
        - int(7 * (dt.year + int((dt.month + 9) / 12)) / 4)
        + int(275 * dt.month / 9)
        + dt.day
        + 1721013.5
    )
    jd += (dt.hour + dt.minute / 60 + dt.second / 3600) / 24
    t = (jd - 2451545.0) / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t**2
        - t**3 / 38710000.0
    )
    return gmst % 360.0


def teme_to_geodetic(position_km: tuple[float, float, float], dt: datetime) -> tuple[float, float, float]:
    """TEME position vector -> (lat_deg, lon_deg, altitude_km)."""
    x, y, z = position_km
    theta = math.radians(gmst_deg(dt))

    # Rotate TEME -> ECEF by -GMST about Z
    x_ecef = math.cos(theta) * x + math.sin(theta) * y
    y_ecef = -math.sin(theta) * x + math.cos(theta) * y
    z_ecef = z

    r = math.sqrt(x_ecef**2 + y_ecef**2 + z_ecef**2)
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z_ecef / r))))
    lon = math.degrees(math.atan2(y_ecef, x_ecef))
    alt = r - EARTH_RADIUS_KM
    return lat, lon, alt


def geodetic_to_teme(lat_deg: float, lon_deg: float, altitude_km: float, dt: datetime) -> tuple[float, float, float]:
    """(lat_deg, lon_deg, altitude_km) -> TEME position vector. Inverse of
    teme_to_geodetic — used to place a user-simulated position into the same
    frame the propagated catalog lives in, so distances are computed once,
    correctly, without repeated frame round-trips."""
    r = EARTH_RADIUS_KM + altitude_km
    lat_r, lon_r = math.radians(lat_deg), math.radians(lon_deg)
    x_ecef = r * math.cos(lat_r) * math.cos(lon_r)
    y_ecef = r * math.cos(lat_r) * math.sin(lon_r)
    z_ecef = r * math.sin(lat_r)

    theta = math.radians(gmst_deg(dt))
    x_teme = math.cos(theta) * x_ecef - math.sin(theta) * y_ecef
    y_teme = math.sin(theta) * x_ecef + math.cos(theta) * y_ecef
    z_teme = z_ecef
    return x_teme, y_teme, z_teme


def teme_to_geodetic_batch(positions_km, dt: datetime):
    """Vectorized teme_to_geodetic for an (n, 3) numpy array of positions at
    a single shared instant. Returns (lat_deg, lon_deg, alt_km) arrays.
    Same math as the scalar version — one GMST rotation, spherical Earth."""
    import numpy as np

    theta = math.radians(gmst_deg(dt))
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    x, y, z = positions_km[:, 0], positions_km[:, 1], positions_km[:, 2]

    x_ecef = cos_t * x + sin_t * y
    y_ecef = -sin_t * x + cos_t * y

    r = np.sqrt(x_ecef**2 + y_ecef**2 + z**2)
    lat = np.degrees(np.arcsin(np.clip(z / r, -1.0, 1.0)))
    lon = np.degrees(np.arctan2(y_ecef, x_ecef))
    alt = r - EARTH_RADIUS_KM
    return lat, lon, alt


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lon)
    theta = math.atan2(y, x)
    return (math.degrees(theta) + 360) % 360
