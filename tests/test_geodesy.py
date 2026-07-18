from datetime import datetime, timezone

from conjunction.risk.geodesy import bearing_deg, geodetic_to_teme, teme_to_geodetic


def test_geodetic_teme_round_trip():
    dt = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
    lat, lon, alt = 53.8861, 52.7993, 851.34

    teme = geodetic_to_teme(lat, lon, alt, dt)
    back_lat, back_lon, back_alt = teme_to_geodetic(teme, dt)

    assert abs(lat - back_lat) < 1e-6
    assert abs(lon - back_lon) < 1e-6
    assert abs(alt - back_alt) < 1e-6


def test_bearing_cardinal_directions():
    # From the equator/prime-meridian origin, due north and due east
    assert abs(bearing_deg(0, 0, 1, 0) - 0) < 0.5
    assert abs(bearing_deg(0, 0, 0, 1) - 90) < 0.5
    assert abs(bearing_deg(0, 0, -1, 0) - 180) < 0.5
    assert abs(bearing_deg(0, 0, 0, -1) - 270) < 0.5
