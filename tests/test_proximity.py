from datetime import datetime, timezone

from conjunction.risk.proximity import RED_KM, YELLOW_KM, compute_proximity, risk_from_distance


def test_risk_thresholds():
    score, level = risk_from_distance(0)
    assert level == "red"
    assert score > 0.99

    score, level = risk_from_distance(RED_KM + 0.1)
    assert level == "yellow"

    score, level = risk_from_distance(YELLOW_KM + 0.1)
    assert level == "green"
    assert score < 0.2


def test_compute_proximity_ranks_nearest_first_and_matches_exact_position():
    dt = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
    objects = [
        {"norad_id": 1, "name": "NEAR", "kind": "debris", "altitude_km": 800, "lat": 10.0, "lon": 20.0},
        {"norad_id": 2, "name": "FAR", "kind": "debris", "altitude_km": 800, "lat": -40.0, "lon": 120.0},
    ]

    # Querying exactly at NEAR's position should put it first with ~0 distance
    ranked = compute_proximity(objects, user_lat=10.0, user_lon=20.0, user_altitude_km=800, at=dt)

    assert ranked[0].name == "NEAR"
    assert ranked[0].distance_km < 0.001
    assert ranked[0].risk_level == "red"
    assert ranked[1].name == "FAR"
    assert ranked[1].distance_km > ranked[0].distance_km
