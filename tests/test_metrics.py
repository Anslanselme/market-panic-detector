import numpy as np
import pandas as pd
import pytest

from panic_detector.metrics import (
    compute_metrics,
    correlation_metrics,
    log_returns,
    marchenko_pastur_upper,
    min_observations,
    rolling_correlations,
)

N = 50


def one_factor_returns(t, n=N, rho=0.4, seed=0):
    """r_i = f + e_i scaled so that every pairwise correlation equals rho."""
    rng = np.random.default_rng(seed)
    f = rng.standard_normal((t, 1))
    e = rng.standard_normal((t, n))
    r = np.sqrt(rho) * f + np.sqrt(1 - rho) * e
    idx = pd.bdate_range("2010-01-01", periods=t)
    return pd.DataFrame(0.01 * r, index=idx, columns=[f"S{i}" for i in range(n)])


def test_log_returns_not_prices():
    prices = pd.DataFrame({"A": [100.0, 110.0, 99.0]})
    r = log_returns(prices)
    assert np.allclose(r["A"], [np.log(1.1), np.log(0.9)])


def test_min_observations_rounding():
    assert min_observations(60, 0.95) == 57
    assert min_observations(250, 0.95) == 238


def test_one_factor_model_large_sample():
    rho = 0.4
    r = one_factor_returns(20_000, rho=rho)
    m = correlation_metrics(np.corrcoef(r.to_numpy(), rowvar=False), len(r))
    expected_l1 = 1 + (N - 1) * rho  # 20.6
    assert m["mean_corr"] == pytest.approx(rho, abs=0.01)
    assert m["lambda1"] == pytest.approx(expected_l1, rel=0.03)
    assert m["lambda1_share"] == pytest.approx(expected_l1 / N, rel=0.03)
    # Top N/5 = 10 eigenvalues: λ1 + 9 bulk eigenvalues of size (1 - rho).
    assert m["absorption_ratio"] == pytest.approx((expected_l1 + 9 * (1 - rho)) / N, abs=0.02)


def test_one_factor_model_rolling_windows():
    rho = 0.3
    r = one_factor_returns(1_500, rho=rho, seed=1)
    m = compute_metrics(r, window=250)
    assert len(m) == 1_500 - 250 + 1
    assert (m["n_stocks"] == N).all()
    assert m["mean_corr"].mean() == pytest.approx(rho, abs=0.02)
    assert m["lambda1"].mean() == pytest.approx(1 + (N - 1) * rho, rel=0.05)
    assert (m["mp_lambda_plus"] == marchenko_pastur_upper(N, 250)).all()


def test_pure_noise_top_eigenvalue_near_marchenko_pastur_edge():
    r = one_factor_returns(500, rho=0.0, seed=2)
    m = correlation_metrics(np.corrcoef(r.to_numpy(), rowvar=False), len(r))
    lam_plus = marchenko_pastur_upper(N, 500)  # (1 + sqrt(0.1))^2 ≈ 1.73
    assert m["mean_corr"] == pytest.approx(0.0, abs=0.01)
    assert m["lambda1"] == pytest.approx(lam_plus, rel=0.12)


def test_perfect_correlation_gives_lambda1_equal_n():
    r = one_factor_returns(300, rho=1.0)
    m = correlation_metrics(np.corrcoef(r.to_numpy(), rowvar=False), len(r))
    assert m["mean_corr"] == pytest.approx(1.0)
    assert m["lambda1"] == pytest.approx(N)
    assert m["absorption_ratio"] == pytest.approx(1.0)


def test_late_listing_enters_after_95_percent_coverage():
    r = one_factor_returns(400, rho=0.3)
    r.iloc[:100, 0] = np.nan  # S0 only has returns from row 100
    windows = {wc.date: wc for wc in rolling_correlations(r, window=60, min_coverage=0.95)}
    dates = r.index
    # Window ending at row i holds rows i-59..i; S0 has i-99 valid returns; needs 57.
    assert "S0" not in windows[dates[155]].tickers
    assert "S0" in windows[dates[156]].tickers
    assert len(windows[dates[156]].tickers) == N
    corr = windows[dates[156]].corr
    assert np.allclose(np.diag(corr), 1.0)
    assert np.allclose(corr, corr.T)
