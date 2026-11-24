"""Rolling correlation-matrix metrics: mean correlation, λ1, absorption ratio, Marchenko-Pastur edge."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd

METRIC_COLUMNS = [
    "n_stocks",
    "mean_corr",
    "lambda1",
    "lambda1_share",
    "absorption_ratio",
    "mp_lambda_plus",
]


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily log returns. Correlations are never computed on price levels."""
    return np.log(prices).diff().iloc[1:]


def min_observations(window: int, min_coverage: float) -> int:
    # Small epsilon so that e.g. 0.95 * 60 = 57.000000000000007 still gives 57.
    return math.ceil(window * min_coverage - 1e-9)


@dataclass(frozen=True)
class WindowCorrelation:
    date: pd.Timestamp
    tickers: list[str]
    corr: np.ndarray  # N x N correlation matrix
    n_obs: int        # window length T


def rolling_correlations(
    returns: pd.DataFrame, window: int, min_coverage: float = 0.95
) -> Iterator[WindowCorrelation]:
    """Yield the correlation matrix of each trailing window, one per day.

    Only stocks with at least `min_coverage` valid returns inside the window are
    kept, so late listings enter once they have enough history. Missing values are
    handled pairwise.
    """
    values = returns.to_numpy(dtype=float)
    valid = ~np.isnan(values)
    cum_valid = np.vstack([np.zeros((1, values.shape[1]), dtype=int), np.cumsum(valid, axis=0)])
    needed = min_observations(window, min_coverage)
    columns = np.asarray(returns.columns)

    for end in range(window - 1, len(values)):
        start = end - window + 1
        counts = cum_valid[end + 1] - cum_valid[start]
        cols = np.flatnonzero(counts >= needed)
        block = values[start : end + 1, cols]
        if valid[start : end + 1, cols].all():
            # Drop constant columns (zero variance would give NaN correlations).
            keep = block.std(axis=0) > 0
            cols, block = cols[keep], block[:, keep]
            if len(cols) < 2:
                continue
            corr = np.corrcoef(block, rowvar=False)
        else:
            corr = pd.DataFrame(block).corr(min_periods=needed).to_numpy()
            keep = ~np.isnan(np.diag(corr))
            cols, corr = cols[keep], corr[np.ix_(keep, keep)]
            if len(cols) < 2:
                continue
            corr = np.nan_to_num(corr, nan=0.0)
        yield WindowCorrelation(returns.index[end], list(columns[cols]), corr, window)


def marchenko_pastur_upper(n: int, t: int) -> float:
    """Upper edge λ+ = (1 + sqrt(N/T))^2 of the eigenvalue spectrum of pure noise."""
    return (1.0 + math.sqrt(n / t)) ** 2


def correlation_metrics(corr: np.ndarray, n_obs: int, absorption_fraction: float = 0.2) -> dict[str, float]:
    n = corr.shape[0]
    eig = np.linalg.eigvalsh(corr)[::-1]  # descending
    total = float(np.trace(corr))          # = N for a correlation matrix
    k = max(1, round(n * absorption_fraction))
    off_diag_sum = float(corr.sum() - np.trace(corr))
    return {
        "n_stocks": n,
        "mean_corr": off_diag_sum / (n * (n - 1)),
        "lambda1": float(eig[0]),
        "lambda1_share": float(eig[0]) / total,
        "absorption_ratio": float(eig[:k].sum()) / total,
        "mp_lambda_plus": marchenko_pastur_upper(n, n_obs),
    }


def compute_metrics(
    returns: pd.DataFrame,
    window: int,
    min_coverage: float = 0.95,
    absorption_fraction: float = 0.2,
) -> pd.DataFrame:
    """One row of metrics per trading day for a given rolling window."""
    rows, dates = [], []
    for wc in rolling_correlations(returns, window, min_coverage):
        rows.append(correlation_metrics(wc.corr, wc.n_obs, absorption_fraction))
        dates.append(wc.date)
    out = pd.DataFrame(rows, index=pd.DatetimeIndex(dates, name="date"), columns=METRIC_COLUMNS)
    out["n_stocks"] = out["n_stocks"].astype(int)
    return out
