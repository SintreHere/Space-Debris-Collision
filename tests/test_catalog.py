from datetime import datetime, timezone

from conjunction.ingestion import storage
from conjunction.ingestion.models import TLERecord
from conjunction.propagation.catalog import load_catalog


def test_load_catalog_carries_altitude_band_fields(tmp_path):
    db_path = tmp_path / "tle_cache.db"
    storage.init_db(db_path)
    now = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
    storage.upsert_tles(
        db_path,
        [
            TLERecord(
                norad_id=25544,
                name="ISS (ZARYA)",
                line1="1 25544U 98067A   26199.50000000  .00016717  00000-0  10270-3 0  9000",
                line2="2 25544  51.6400 208.9163 0006317  69.9862 290.2000 15.49000000000000",
                epoch=now,
                mean_motion=15.49,
                eccentricity=0.0006317,
                perigee_altitude_km=415.3,
                apogee_altitude_km=424.8,
                source="test",
                fetched_at=now,
            )
        ],
    )

    catalog = load_catalog(db_path)
    assert len(catalog) == 1
    obj = catalog[0]
    assert obj.norad_id == 25544
    assert obj.perigee_altitude_km == 415.3
    assert obj.apogee_altitude_km == 424.8
