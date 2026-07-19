"""Phase 1 tests — Indian LEO asset registry integrity and epoch-awareness."""

from datetime import date

from research.assets.registry import (
    issar_sanity_check,
    load_assets,
    norad_ids_at,
)


def test_catalog_loads_and_ids_are_unique():
    assets = load_assets()
    assert len(assets) >= 20
    ids = [a.norad_id for a in assets]
    assert len(ids) == len(set(ids))


def test_all_leo_altitudes_within_leo_band():
    for a in load_assets():
        assert 300 <= a.nominal_alt_km <= 900, a.name


def test_epoch_awareness_cartosat2_deorbit():
    """Cartosat-2 (29710) must appear in 2020 primaries but not 2025."""
    assert 29710 in norad_ids_at(date(2020, 1, 1))
    assert 29710 not in norad_ids_at(date(2025, 1, 1))


def test_epoch_awareness_risat2_decay_and_nisar_arrival():
    ids_2019 = norad_ids_at(date(2019, 7, 1))
    ids_2026 = norad_ids_at(date(2026, 7, 1))
    assert 34807 in ids_2019 and 34807 not in ids_2026  # RISAT-2 decayed 2022
    assert 65053 not in ids_2019 and 65053 in ids_2026  # NISAR launched 2025


def test_uncertain_assets_excluded_by_default():
    """Assets flagged 'uncertain' (e.g. Cartosat-2A/2B, Oceansat-2) must not
    silently enter the primary set — inclusion requires explicit verification."""
    for epoch in (date(2019, 6, 1), date(2023, 6, 1), date(2026, 6, 1)):
        ids = norad_ids_at(epoch)
        assert 32783 not in ids and 36795 not in ids and 35931 not in ids


def test_scope_all_leo_includes_science_eo_fleet_does_not():
    when = date(2026, 1, 1)
    eo = norad_ids_at(when, scope="eo_fleet")
    all_leo = norad_ids_at(when, scope="all_leo")
    assert 40930 not in eo and 40930 in all_leo  # AstroSat
    assert set(eo) <= set(all_leo)


def test_defence_toggle():
    when = date(2026, 1, 1)
    with_def = norad_ids_at(when, include_defence=True)
    without = norad_ids_at(when, include_defence=False)
    assert 44078 in with_def and 44078 not in without  # EMISAT
    assert set(without) <= set(with_def)


def test_issar_2025_sanity_bound():
    """ISSAR 2025 reports 22 operational Indian LEO satellites (end-2025).
    Our all-LEO active count at that date should land in the same range;
    exact equality is not expected (ISSAR inclusion rules are unpublished)."""
    ok, msg = issar_sanity_check(date(2025, 12, 31), issar_operational_leo_count=22)
    assert ok, msg
