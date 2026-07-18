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


def test_batch_matches_scalar_conversion():
    import numpy as np

    from conjunction.risk.geodesy import teme_to_geodetic, teme_to_geodetic_batch

    dt = datetime(2026, 7, 18, 6, 0, 0, tzinfo=timezone.utc)
    positions = np.array(
        [
            [7000.0, 0.0, 0.0],
            [-3000.0, 5500.0, 2000.0],
            [100.0, -6800.0, -900.0],
        ]
    )
    lats, lons, alts = teme_to_geodetic_batch(positions, dt)
    for i in range(positions.shape[0]):
        lat_s, lon_s, alt_s = teme_to_geodetic(tuple(positions[i]), dt)
        assert abs(lats[i] - lat_s) < 1e-9
        assert abs(lons[i] - lon_s) < 1e-9
        assert abs(alts[i] - alt_s) < 1e-9
