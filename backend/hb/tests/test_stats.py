import pytest

from hb.engine import stats


def test_equal_weights_median_unbiased():
    values = [10, 20, 30, 40, 50]
    weights = [1, 1, 1, 1, 1]
    # median-unbiased plotting positions (cw-0.5w)/Σw = [.1,.3,.5,.7,.9] put the
    # median exactly at the middle value; the quartiles interpolate symmetrically.
    assert stats.weighted_median(values, weights) == pytest.approx(30.0)
    q25, q75 = stats.weighted_quantile(values, weights, [0.25, 0.75])
    assert q25 == pytest.approx(17.5, abs=1e-9)
    assert q75 == pytest.approx(42.5, abs=1e-9)


def test_weights_pull_the_median():
    # heavy weight on the low value drags the weighted median down
    values = [10, 100]
    low = stats.weighted_median(values, [9, 1])
    high = stats.weighted_median(values, [1, 9])
    assert low < 55 < high


def test_single_value():
    assert stats.weighted_median([42], [3]) == pytest.approx(42.0)
    assert stats.weighted_quantile([42], [3], 0.9) == pytest.approx(42.0)


def test_scalar_vs_sequence_return_types():
    assert isinstance(stats.weighted_quantile([1, 2, 3], [1, 1, 1], 0.5), float)
    out = stats.weighted_quantile([1, 2, 3], [1, 1, 1], [0.25, 0.5])
    assert isinstance(out, list) and len(out) == 2


def test_zero_total_weight_falls_back_to_unweighted():
    assert stats.weighted_median([10, 20, 30], [0, 0, 0]) == pytest.approx(20.0)


def test_histogram_conserves_weight():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    weights = [1] * 10
    buckets = stats.weighted_histogram(values, weights, bins=5)
    assert len(buckets) == 5
    assert sum(w for _, _, w in buckets) == pytest.approx(10.0)
    # buckets are contiguous and ascending
    for i in range(len(buckets) - 1):
        assert buckets[i][1] == pytest.approx(buckets[i + 1][0])


def test_histogram_explicit_edges_and_empty():
    buckets = stats.weighted_histogram([1.0, 1.5, 2.5], [2, 1, 1], bins=[1.0, 2.0, 3.0])
    assert buckets[0] == pytest.approx((1.0, 2.0, 3.0))  # 2+1 weight in [1,2)
    assert buckets[1] == pytest.approx((2.0, 3.0, 1.0))
    assert stats.weighted_histogram([], [], bins=5) == []
