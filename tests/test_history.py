"""Phase 2 tests — historical acquisition layer (no network; fakes only)."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

from research.history.client import GPHistoryClient
from research.history.models import gp_record_from_omm_json
from research.history.ratelimit import RateLimiter
from research.history.snapshots import nearest_per_object, snapshot_plan
from research.history.store import (
    completed_snapshots,
    init_history_db,
    load_snapshot,
    store_snapshot,
)

# ---------------------------------------------------------------- fixtures

def _omm_row(norad, epoch, name="OBJ", mm="14.5", six_digit=False):
    row = {
        "NORAD_CAT_ID": str(norad),
        "OBJECT_NAME": name,
        "OBJECT_TYPE": "PAYLOAD",
        "COUNTRY_CODE": "IND",
        "OBJECT_ID": "2019-028A",
        "EPOCH": epoch,
        "MEAN_MOTION": mm,
        "ECCENTRICITY": "0.0012000",
        "INCLINATION": "97.5000",
        "RA_OF_ASC_NODE": "100.0",
        "ARG_OF_PERICENTER": "50.0",
        "MEAN_ANOMALY": "310.0",
        "BSTAR": "0.00012",
        "TLE_LINE1": None if six_digit else "1 44233U ...",
        "TLE_LINE2": None if six_digit else "2 44233 ...",
    }
    return row


# ---------------------------------------------------------------- snapshots

def test_snapshot_plan_quarterly_2019_to_mid_2026():
    plan = snapshot_plan(end=date(2026, 7, 1))
    assert plan[0].label == "2019Q1"
    assert plan[-1].label == "2026Q3"
    assert len(plan) == 31  # 2019Q1..2026Q3 inclusive
    assert plan[0].spacetrack_epoch_range == "2018-12-30--2019-01-03"


def test_snapshot_plan_annual_fallback():
    plan = snapshot_plan(end=date(2026, 7, 1), cadence="annual")
    assert [s.label for s in plan] == [f"{y}Q1" for y in range(2019, 2027)]


def test_nearest_per_object_policy():
    target = datetime(2019, 1, 1, tzinfo=timezone.utc)
    rows = [
        _omm_row(100, "2018-12-31T00:00:00"),  # 24h before target
        _omm_row(100, "2019-01-01T06:00:00"),  # 6h after -> winner
        _omm_row(200, "2019-01-02T00:00:00"),
    ]
    records = [gp_record_from_omm_json(r) for r in rows]
    chosen = nearest_per_object(records, target)
    assert len(chosen) == 2
    winner = next(r for r in chosen if r.norad_id == 100)
    assert winner.epoch.hour == 6


# --------------------------------------------------------------- ratelimit

def test_rate_limiter_blocks_at_minute_cap():
    fake_now = [0.0]
    slept = []

    def clock():
        return fake_now[0]

    def sleep(s):
        slept.append(s)
        fake_now[0] += s

    rl = RateLimiter(per_minute=3, per_hour=100, clock=clock, sleep=sleep)
    for _ in range(3):
        assert rl.acquire() == 0.0
    rl.acquire()  # 4th must wait out the 60s window
    assert slept and abs(sum(slept) - 60.0) < 1e-6


def test_rate_limiter_hour_cap_dominates():
    fake_now = [0.0]

    def clock():
        return fake_now[0]

    def sleep(s):
        fake_now[0] += s

    rl = RateLimiter(per_minute=100, per_hour=2, clock=clock, sleep=sleep)
    rl.acquire()
    rl.acquire()
    waited = rl.acquire()
    assert abs(waited - 3600.0) < 1e-6


# -------------------------------------------------------------------- OMM

def test_omm_parse_six_digit_id_without_tle_lines():
    r = gp_record_from_omm_json(
        _omm_row(100058, "2026-07-12T03:00:00", name="SARAMAGO-ERA OBJ", six_digit=True)
    )
    assert r.norad_id == 100058
    assert r.tle_line1 is None and r.tle_line2 is None
    assert r.perigee_altitude_km > 0  # altitude derived from elements, not TLE
    assert r.object_type == "PAYLOAD" and r.country_code == "IND"  # Phase 4 fields


def test_omm_altitude_matches_repo_math():
    from conjunction.ingestion.altitude import perigee_apogee_altitude_km

    r = gp_record_from_omm_json(_omm_row(1, "2020-01-01T00:00:00", mm="15.1"))
    expected = perigee_apogee_altitude_km(15.1, 0.0012)
    assert abs(r.perigee_altitude_km - expected[0]) < 1e-9


# ------------------------------------------------------------------ store

def test_store_roundtrip_and_resumability(tmp_path: Path):
    db = tmp_path / "hist.db"
    init_history_db(db)
    plan = snapshot_plan(end=date(2019, 4, 1))
    s1, s2 = plan[0], plan[1]

    recs = [gp_record_from_omm_json(_omm_row(100, "2019-01-01T01:00:00")),
            gp_record_from_omm_json(_omm_row(100058, "2019-01-01T02:00:00", six_digit=True))]
    assert store_snapshot(db, s1, recs) == 2

    assert completed_snapshots(db) == {s1.label}  # s2 not done -> resumable
    rows = load_snapshot(db, s1.label)
    assert [r["norad_id"] for r in rows] == [100, 100058]
    assert rows[1]["tle_line1"] is None

    store_snapshot(db, s2, recs[:1])
    assert completed_snapshots(db) == {s1.label, s2.label}


# ----------------------------------------------------------------- client

def test_client_paginates_and_dedupes():
    """Fake transport: 2 pages, duplicate elsets for one object across the
    window — the client must page until a short page and dedupe to nearest."""
    calls = []

    def fake_transport(request_class, predicates):
        calls.append(predicates)
        offset = int(predicates["limit"].split(",")[1])
        if offset == 0:
            page = [_omm_row(100, "2018-12-31T00:00:00"),
                    _omm_row(100, "2019-01-01T03:00:00")]
        else:
            page = [_omm_row(200, "2019-01-01T12:00:00")]
        return json.dumps(page)

    rl = RateLimiter(per_minute=1000, per_hour=10000,
                     clock=lambda: 0.0, sleep=lambda s: None)
    client = GPHistoryClient(transport=fake_transport, limiter=rl, page_size=2)
    snap = snapshot_plan(end=date(2019, 1, 2))[0]
    out = client.fetch_snapshot(snap)

    assert len(calls) == 2  # paged exactly until the short page
    assert calls[0]["epoch"] == snap.spacetrack_epoch_range
    assert [r.norad_id for r in out] == [100, 200]
    assert out[0].epoch.hour == 3  # nearest-to-target elset won


def test_client_object_history_single_query_for_many_ids():
    seen = {}

    def fake_transport(request_class, predicates):
        seen.update(predicates)
        return json.dumps([_omm_row(44233, "2019-06-02T00:00:00")])

    rl = RateLimiter(per_minute=1000, per_hour=10000,
                     clock=lambda: 0.0, sleep=lambda s: None)
    client = GPHistoryClient(transport=fake_transport, limiter=rl)
    out = client.fetch_object_history([44233, 44078], "2019-06-01", "2019-07-01")
    assert seen["norad_cat_id"] == "44233,44078"  # one comma-list query, no loops
    assert out[0].norad_id == 44233
