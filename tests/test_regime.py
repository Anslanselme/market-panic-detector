import numpy as np
import pandas as pd
import pytest

from panic_detector.regime import CALM, PANIC, TENSION, WARMUP, classify, expanding_percentile


def random_series(n=1_000, seed=0):
    rng = np.random.default_rng(seed)
    values = 0.3 + 0.1 * np.cumsum(rng.standard_normal(n)) / np.sqrt(n)
    return pd.Series(values, index=pd.bdate_range("2008-01-01", periods=n))


def test_percentile_matches_brute_force_definition():
    s = random_series(300)
    pct = expanding_percentile(s)
    v = s.to_numpy()
    brute = [100 * np.mean(v[: i + 1] <= v[i]) for i in range(len(v))]
    assert np.allclose(pct.to_numpy(), brute)


def test_regime_uses_no_future_data():
    s = random_series()
    reference = classify(s, min_history=100)
    cut = 600
    altered = s.copy()
    # Rewrite the future completely: huge values, then reversed order.
    altered.iloc[cut:] = altered.iloc[cut:].to_numpy()[::-1] * 10
    result = classify(altered, min_history=100)
    pd.testing.assert_frame_equal(result.iloc[:cut], reference.iloc[:cut])
    # Sanity check: the future did change.
    assert not result.iloc[cut:].equals(reference.iloc[cut:])


def test_regime_prefix_invariance():
    """Classifying a truncated history gives the same answer as the full run on that prefix."""
    s = random_series()
    full = classify(s, min_history=50)
    for cut in (60, 333, 999):
        pd.testing.assert_frame_equal(classify(s.iloc[:cut], min_history=50), full.iloc[:cut])


def test_thresholds_and_warmup():
    s = pd.Series(np.arange(1, 301, dtype=float))  # strictly increasing: always 100th pct
    out = classify(s, min_history=250)
    assert (out["regime"].iloc[:249] == WARMUP).all()
    assert (out["regime"].iloc[249:] == PANIC).all()

    s = pd.Series(np.arange(300, 0, -1, dtype=float))  # strictly decreasing: lowest pct
    out = classify(s, min_history=10)
    assert (out["regime"].iloc[20:] == CALM).all()


def test_tension_band():
    hist = pd.Series(np.r_[np.arange(100, dtype=float), 74.5])  # last value ~75th pct
    out = classify(hist, 60, 90, min_history=10)
    assert out["percentile"].iloc[-1] == pytest.approx(100 * 76 / 101)
    assert out["regime"].iloc[-1] == TENSION


def test_nan_values_are_skipped():
    s = random_series(400)
    s.iloc[[5, 50, 300]] = np.nan
    out = classify(s, min_history=10)
    assert (out["regime"].iloc[[5, 50, 300]] == WARMUP).all()
    assert out["percentile"].iloc[[5, 50, 300]].isna().all()
