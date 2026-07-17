"""Sanity-check the altitude math against known real objects."""

from conjunction.ingestion.altitude import in_altitude_band, perigee_apogee_altitude_km


def test_iss_altitude_is_roughly_correct():
    # ISS TLE circa 2024: mean motion ~15.5 rev/day, eccentricity ~0.0003
    perigee_alt, apogee_alt = perigee_apogee_altitude_km(15.5, 0.0003)
    # ISS orbits at roughly 400-420 km — allow generous tolerance since this
    # is a spot-check, not a precision requirement.
    assert 350 < perigee_alt < 450
    assert 350 < apogee_alt < 450


def test_geo_object_altitude_is_roughly_correct():
    # Geostationary: mean motion = 1 rev/day, near-circular
    perigee_alt, apogee_alt = perigee_apogee_altitude_km(1.0, 0.0001)
    # GEO altitude is ~35,786 km
    assert 35000 < perigee_alt < 36500
    assert 35000 < apogee_alt < 36500


def test_in_altitude_band_circular_orbit_inside_band():
    # Circular-ish orbit near 800 km should be inside a 700-900 km band
    assert in_altitude_band(mean_motion_rev_per_day=14.32, eccentricity=0.001,
                             band_min_km=700, band_max_km=900) is True


def test_in_altitude_band_iss_outside_band():
    # ISS (~400km) should NOT be inside a 700-900 km band
    assert in_altitude_band(mean_motion_rev_per_day=15.5, eccentricity=0.0003,
                             band_min_km=700, band_max_km=900) is False
