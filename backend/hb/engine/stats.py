"""Shared weighted-statistics helpers for the valuation engine.

The CMA estimate (docs/06 §4.4) and the overbid distribution (§5.3) both take
weighted quantiles of a small sample; keeping the convention in one place means
the golden gates ($2,198,766 ±1, p50_final 1.106 ±0.001) never drift on a
quantile-interpolation detail. Pure numpy — no DB, no session.
"""

from collections.abc import Sequence

import numpy as np


def weighted_quantile(
    values: Sequence[float], weights: Sequence[float], q: float | Sequence[float]
) -> float | list[float]:
    """Weighted quantile(s) with linear interpolation (median-unbiased plotting
    positions ``(cw - 0.5w)/Σw``). ``q`` scalar → float; ``q`` sequence → list.

    Equal weights reproduce the ordinary linear-interpolated quantile; a single
    sample returns that sample for any q. Values outside the coverage clamp to
    the extreme sample (np.interp behaviour).
    """
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    if v.size == 0:
        raise ValueError("weighted_quantile: empty values")
    if v.size != w.size:
        raise ValueError("weighted_quantile: values/weights length mismatch")
    total = w.sum()
    if total <= 0:
        # degenerate weights → fall back to unweighted
        w = np.ones_like(v)
        total = w.sum()

    order = np.argsort(v, kind="mergesort")
    v_sorted = v[order]
    w_sorted = w[order]
    cw = np.cumsum(w_sorted)
    positions = (cw - 0.5 * w_sorted) / total  # in (0, 1)

    scalar = np.isscalar(q)
    qs = np.atleast_1d(np.asarray(q, dtype=float))
    out = np.interp(qs, positions, v_sorted)
    return float(out[0]) if scalar else [float(x) for x in out]


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    """Weighted 50th percentile."""
    result = weighted_quantile(values, weights, 0.5)
    assert isinstance(result, float)
    return result


def weighted_histogram(
    values: Sequence[float],
    weights: Sequence[float],
    bins: int | Sequence[float] = 10,
    value_range: tuple[float, float] | None = None,
) -> list[tuple[float, float, float]]:
    """Weighted histogram → ``[(bucket_low, bucket_high, weight), ...]``.

    ``bins`` is either a bucket count or explicit edges. Empty input → ``[]``.
    """
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    if v.size == 0:
        return []
    if isinstance(bins, int):
        if value_range is None:
            lo, hi = float(v.min()), float(v.max())
        else:
            lo, hi = value_range
        if hi <= lo:
            hi = lo + 1.0  # avoid a zero-width single bucket
        counts, edges = np.histogram(v, bins=bins, range=(lo, hi), weights=w)
    else:
        counts, edges = np.histogram(v, bins=np.asarray(bins, dtype=float), weights=w)
    return [
        (float(edges[i]), float(edges[i + 1]), float(counts[i]))
        for i in range(len(counts))
    ]
