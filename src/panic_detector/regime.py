"""Market regime from the expanding (past-only) percentile of the mean correlation."""

from __future__ import annotations

import bisect

import numpy as np
import pandas as pd

CALM, TENSION, PANIC, WARMUP = "calm", "tension", "panic", "warmup"
REGIMES = (CALM, TENSION, PANIC)


def expanding_percentile(series: pd.Series) -> pd.Series:
    """Percentile of each value among all values observed up to and including that day.

    Value at t = 100 * #{s <= t : x_s <= x_t} / #{s <= t}. No future observation is used.
    NaNs are skipped and give NaN.
    """
    history: list[float] = []
    out = np.full(len(series), np.nan)
    for i, x in enumerate(series.to_numpy(dtype=float)):
        if np.isnan(x):
            continue
        bisect.insort(history, x)
        out[i] = 100.0 * bisect.bisect_right(history, x) / len(history)
    return pd.Series(out, index=series.index, name="percentile")


def classify(
    series: pd.Series,
    tension_percentile: float = 60.0,
    panic_percentile: float = 90.0,
    min_history: int = 250,
) -> pd.DataFrame:
    """CALM below `tension_percentile`, PANIC above `panic_percentile`, TENSION in between.

    Days with fewer than `min_history` past observations are labelled WARMUP.
    """
    pct = expanding_percentile(series)
    history = series.notna().cumsum()
    regime = np.where(
        pct < tension_percentile, CALM, np.where(pct > panic_percentile, PANIC, TENSION)
    ).astype(object)
    regime[(history < min_history).to_numpy() | pct.isna().to_numpy()] = WARMUP
    return pd.DataFrame({"percentile": pct, "regime": regime}, index=series.index)
