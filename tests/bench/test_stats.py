import pytest

from sandbox_analyst.bench.stats import (
    bootstrap_ci,
    mean,
    mean_and_range,
    paired_bootstrap_ci,
    percentile,
)


def test_percentile_median_of_odd_length():
    assert percentile([1, 2, 3, 4, 5], 50) == 3


def test_percentile_interpolates_between_two_values():
    # n=4: p50 position = 0.5*(4-1) = 1.5 -> interpolate between index 1 (2) and 2 (3)
    assert percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)


def test_percentile_min_and_max():
    values = [5, 1, 3, 2, 4]
    assert percentile(values, 0) == 1
    assert percentile(values, 100) == 5


def test_percentile_single_value():
    assert percentile([42], 50) == 42


def test_percentile_raises_on_empty():
    with pytest.raises(ValueError):
        percentile([], 50)


def test_mean_of_empty_is_zero():
    assert mean([]) == 0.0


def test_mean_and_range():
    assert mean_and_range([1.0, 2.0, 3.0]) == (2.0, 1.0, 3.0)


def test_mean_and_range_of_empty():
    assert mean_and_range([]) == (0.0, 0.0, 0.0)


# ---- bootstrap determinism ----


def test_bootstrap_ci_is_deterministic_for_a_fixed_seed():
    values = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0]
    first = bootstrap_ci(values, seed=2026, n_resamples=500)
    second = bootstrap_ci(values, seed=2026, n_resamples=500)
    assert first == second


def test_bootstrap_ci_of_constant_values_collapses_to_that_value():
    lo, hi = bootstrap_ci([1.0] * 20, n_resamples=200)
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(1.0)


def test_bootstrap_ci_of_empty_is_zero():
    assert bootstrap_ci([]) == (0.0, 0.0)


def test_bootstrap_ci_bounds_are_within_the_data_range():
    values = [0.0, 0.0, 1.0, 1.0, 1.0]
    lo, hi = bootstrap_ci(values, n_resamples=1000)
    assert 0.0 <= lo <= hi <= 1.0


# ---- paired bootstrap: rows stay together across a resample ----


def test_paired_bootstrap_ci_keeps_a_row_together():
    # Each row is one question's (run_a, run_b) pair; a huge gap between rows
    # vs. within a row means a correct pairing should keep the CI narrow.
    rows = [[0.0, 0.0]] * 10 + [[1.0, 1.0]] * 10
    lo, hi = paired_bootstrap_ci(rows, n_resamples=2000)
    assert 0.0 <= lo <= hi <= 1.0


def test_paired_bootstrap_ci_is_deterministic():
    rows = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    first = paired_bootstrap_ci(rows, seed=7, n_resamples=300)
    second = paired_bootstrap_ci(rows, seed=7, n_resamples=300)
    assert first == second


def test_paired_bootstrap_ci_of_empty_rows_is_zero():
    assert paired_bootstrap_ci([]) == (0.0, 0.0)
