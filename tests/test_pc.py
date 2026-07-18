import math

import pytest

from conjunction.risk.pc import (
    DEFAULT_COMBINED_SIGMA_KM,
    DEFAULT_HBR_KM,
    probability_of_collision,
)


def test_pc_bounds():
    for d in [0.0, 0.5, 1.0, 5.0, 25.0, 100.0]:
        pc = probability_of_collision(d)
        assert 0.0 <= pc <= 1.0


def test_pc_decreases_with_miss_distance():
    distances = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0]
    pcs = [probability_of_collision(d) for d in distances]
    assert all(a >= b for a, b in zip(pcs, pcs[1:]))


def test_pc_exact_at_zero_miss_distance():
    # At d=0 the noncentral chi-square reduces to central: Pc = 1 - exp(-x/2)
    # with x = (hbr/sigma)^2.
    x = (DEFAULT_HBR_KM / DEFAULT_COMBINED_SIGMA_KM) ** 2
    expected = 1 - math.exp(-x / 2)
    assert abs(probability_of_collision(0.0) - expected) < 1e-12


def test_pc_rejects_nonpositive_sigma():
    with pytest.raises(ValueError):
        probability_of_collision(1.0, combined_sigma_km=0.0)
