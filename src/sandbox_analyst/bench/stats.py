"""Small, dependency-free statistics helpers: percentiles and a paired bootstrap.

No numpy here (D-002: analysis libraries live only in the sandbox
image, not on the host) -- these are plain-Python reimplementations of
the two things this project's reports need: a percentile matching
numpy's default linear-interpolation method (used for p50/p95 latency,
and for D-056's timeout derivation), and a bootstrap confidence
interval that resamples QUESTIONS rather than individual data points,
so repeated runs of the same question stay paired together in every
resample (D-062).
"""

import math
import random
from collections.abc import Callable, Sequence

DEFAULT_N_RESAMPLES = 10_000
DEFAULT_SEED = 2026
DEFAULT_CONFIDENCE = 0.95


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile, matching numpy's default ("linear") method."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    k = (len(data) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[f] * (c - k) + data[c] * (k - f)


def mean_and_range(values: Sequence[float]) -> tuple[float, float, float]:
    """(mean, min, max) across a small set of per-run point estimates."""
    if not values:
        return (0.0, 0.0, 0.0)
    return (mean(values), min(values), max(values))


def paired_bootstrap_ci(
    rows: Sequence[Sequence[float]],
    statistic: Callable[[Sequence[float]], float] = mean,
    n_resamples: int = DEFAULT_N_RESAMPLES,
    seed: int = DEFAULT_SEED,
    confidence: float = DEFAULT_CONFIDENCE,
) -> tuple[float, float]:
    """A 95% CI for `statistic`, resampling ROWS (questions) with replacement.

    Each row holds every value that belongs to one question (one value
    for a single run, or one value per run when pooling several runs
    paired by question id -- D-062). Every resample draws `len(rows)`
    rows with replacement and flattens them before computing the
    statistic, so a question's several runs are always kept or dropped
    together, never resampled independently of each other.
    """
    n = len(rows)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    lo_pct = (1 - confidence) / 2 * 100
    hi_pct = 100 - lo_pct
    resample_stats = []
    for _ in range(n_resamples):
        flat: list[float] = []
        for _ in range(n):
            flat.extend(rows[rng.randrange(n)])
        resample_stats.append(statistic(flat))
    return (percentile(resample_stats, lo_pct), percentile(resample_stats, hi_pct))


def bootstrap_ci(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float] = mean,
    n_resamples: int = DEFAULT_N_RESAMPLES,
    seed: int = DEFAULT_SEED,
    confidence: float = DEFAULT_CONFIDENCE,
) -> tuple[float, float]:
    """A single-run bootstrap CI: each value is its own (unpaired) row."""
    return paired_bootstrap_ci(
        [[v] for v in values],
        statistic=statistic,
        n_resamples=n_resamples,
        seed=seed,
        confidence=confidence,
    )
