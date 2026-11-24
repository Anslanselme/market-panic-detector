"""Honest test: does the correlation indicator anticipate market drawdowns, or only react to them?

1. Event study around every SPY decline of more than 10 % (peak to trough).
2. Predictive regressions of SPY's forward 20-day return on the indicator, on
   non-overlapping samples and with Newey-West standard errors on daily data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from panic_detector.regime import PANIC


@dataclass(frozen=True)
class DrawdownEvent:
    peak: pd.Timestamp      # last high before the decline (known only in hindsight)
    cross: pd.Timestamp     # first day the decline exceeded the threshold (known in real time)
    trough: pd.Timestamp
    rebound: pd.Timestamp | None  # first day `threshold` above the trough (ends the event)
    depth: float            # trough / peak - 1 (negative)


def find_drawdowns(prices: pd.Series, threshold: float = 0.10) -> list[DrawdownEvent]:
    """Zig-zag swings: declines of more than `threshold` from a peak.

    A peak is confirmed when the price falls `threshold` below it; the trough is
    confirmed when the price rebounds `threshold` above it, after which a new peak is
    tracked. A new all-time high is not required, so e.g. 2010 and 2011 are separate
    events even though SPY had not yet regained its 2007 high.
    """
    prices = prices.dropna()
    events: list[DrawdownEvent] = []
    peak_date, peak_val = prices.index[0], prices.iloc[0]
    falling = False
    cross = trough_date = None
    trough_val = np.inf
    for date, price in prices.items():
        if not falling:
            if price >= peak_val:
                peak_date, peak_val = date, price
            elif price <= peak_val * (1 - threshold):
                falling, cross, trough_date, trough_val = True, date, date, price
        else:
            if price < trough_val:
                trough_date, trough_val = date, price
            elif price >= trough_val * (1 + threshold):
                events.append(DrawdownEvent(peak_date, cross, trough_date, date, trough_val / peak_val - 1))
                falling = False
                peak_date, peak_val = date, price
    if falling:
        events.append(DrawdownEvent(peak_date, cross, trough_date, None, trough_val / peak_val - 1))
    return events


def fresh_events(
    events: list[DrawdownEvent], calendar: pd.DatetimeIndex, before: int
) -> list[DrawdownEvent]:
    """Events whose pre-peak window [-before, 0] starts after the previous event ended.

    Aftershocks (a new leg down shortly after a rebound) start from an indicator that
    is already high, which would make it look like it 'rose before the peak'.
    """
    kept: list[DrawdownEvent] = []
    previous_end: int | None = None
    for e in events:
        start = calendar.get_loc(e.peak) - before
        if previous_end is None or start > previous_end:
            kept.append(e)
        previous_end = calendar.get_loc(e.rebound) if e.rebound is not None else len(calendar)
    return kept


def sign_test(values: pd.Series, center: float = 50.0) -> dict[str, float]:
    """Two-sided binomial test that values fall above `center` as often as below."""
    v = values.dropna()
    above, below = int((v > center).sum()), int((v < center).sum())
    p = stats.binomtest(above, above + below, 0.5).pvalue if above + below else np.nan
    return {"n": above + below, "above": above, "below": below, "median": float(v.median()), "p": float(p)}


def event_window(series: pd.Series, event_date: pd.Timestamp, before: int, after: int) -> pd.Series:
    """Values from `before` trading days before to `after` days after the event, indexed by offset."""
    pos = series.index.get_indexer([event_date])[0]
    if pos < 0:
        raise KeyError(f"{event_date} not in index")
    offsets = np.arange(-before, after + 1)
    values = np.full(len(offsets), np.nan)
    for k, off in enumerate(offsets):
        if 0 <= pos + off < len(series):
            values[k] = series.iloc[pos + off]
    return pd.Series(values, index=pd.Index(offsets, name="offset"))


def event_profiles(
    indicator: pd.Series, calendar: pd.DatetimeIndex, events: list[DrawdownEvent], before: int, after: int
) -> pd.DataFrame:
    """One column per event (peak date), rows = trading-day offset from the peak."""
    aligned = indicator.reindex(calendar)
    return pd.DataFrame(
        {e.peak.date(): event_window(aligned, e.peak, before, after) for e in events}
    )


def _offset(calendar: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp | None) -> float:
    if end is None:
        return np.nan
    return float(calendar.get_loc(end) - calendar.get_loc(start))


def event_table(
    metrics: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    events: list[DrawdownEvent],
    before: int,
    after: int,
    column: str = "mean_corr",
) -> pd.DataFrame:
    """Per event: indicator path, how unusual the pre-peak change was, and timing of the PANIC regime."""
    aligned = metrics.reindex(calendar)
    ind = aligned[column]
    # Unconditional distribution of `before`-day changes, to judge the pre-peak change.
    all_changes = (ind - ind.shift(before)).dropna().to_numpy()
    rows = []
    for e in events:
        path = event_window(ind, e.peak, before, after)
        change_pre = path.loc[0] - path.loc[-before]
        # Look for PANIC between the peak and 20 days after the trough.
        trough_pos = calendar.get_loc(e.trough)
        end = calendar[min(trough_pos + after, len(calendar) - 1)]
        panic = aligned.loc[e.peak : end, "regime"]
        first_panic = panic.index[panic.eq(PANIC)][0] if panic.eq(PANIC).any() else None
        rows.append(
            {
                "peak": e.peak.date(),
                "cross_10pct": e.cross.date(),
                "trough": e.trough.date(),
                "depth": e.depth,
                "days_peak_to_cross": _offset(calendar, e.peak, e.cross),
                "days_peak_to_trough": _offset(calendar, e.peak, e.trough),
                f"{column}_t-{before}": path.loc[-before],
                f"{column}_peak": path.loc[0],
                f"{column}_t+{after}": path.loc[after],
                f"{column}_trough": ind.get(e.trough, np.nan),
                "pre_peak_change": change_pre,
                "pre_peak_change_pctile": (
                    100 * np.mean(all_changes <= change_pre) if np.isfinite(change_pre) else np.nan
                ),
                "regime_at_peak": aligned.loc[e.peak, "regime"],
                "first_panic": first_panic.date() if first_panic is not None else None,
                "days_peak_to_panic": _offset(calendar, e.peak, first_panic),
                "panic_vs_cross_days": (
                    _offset(calendar, e.cross, first_panic) if first_panic is not None else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def forward_log_return(prices: pd.Series, horizon: int) -> pd.Series:
    """log(P[t+h] / P[t]): the return earned AFTER day t."""
    lp = np.log(prices)
    return lp.shift(-horizon) - lp


def past_log_return(prices: pd.Series, horizon: int) -> pd.Series:
    """log(P[t] / P[t-h]): the return earned over the h days ending at t."""
    lp = np.log(prices)
    return lp - lp.shift(horizon)


def past_change(series: pd.Series, horizon: int) -> pd.Series:
    """x[t] - x[t-h]: uses only information available at t."""
    return series - series.shift(horizon)


def non_overlapping(frame: pd.DataFrame, step: int, start: int = 0) -> pd.DataFrame:
    """Every `step`-th row, so consecutive forward windows never overlap."""
    return frame.iloc[start::step]


@dataclass(frozen=True)
class PredictiveResult:
    signal: str
    n_nonoverlap: int
    pearson_r: float
    pearson_p: float
    spearman_rho: float
    spearman_p: float
    r_min_offsets: float  # range of Pearson r over the `horizon` possible sampling offsets
    r_max_offsets: float
    n_daily: int
    nw_slope: float       # forward return per 1 standard deviation of the signal
    nw_t: float
    nw_p: float
    r2: float


def predictive_test(signal: pd.Series, forward: pd.Series, horizon: int, name: str) -> PredictiveResult:
    data = pd.concat({"x": signal, "y": forward}, axis=1).dropna()
    sample = non_overlapping(data, horizon)
    pr = stats.pearsonr(sample["x"], sample["y"])
    sr = stats.spearmanr(sample["x"], sample["y"])
    offsets_r = [
        stats.pearsonr(s["x"], s["y"])[0]
        for s in (non_overlapping(data, horizon, k) for k in range(horizon))
    ]
    z = (data["x"] - data["x"].mean()) / data["x"].std()
    fit = sm.OLS(data["y"].to_numpy(), sm.add_constant(z.to_numpy())).fit(
        cov_type="HAC", cov_kwds={"maxlags": horizon}
    )
    return PredictiveResult(
        signal=name,
        n_nonoverlap=len(sample),
        pearson_r=float(pr[0]),
        pearson_p=float(pr[1]),
        spearman_rho=float(sr[0]),
        spearman_p=float(sr[1]),
        r_min_offsets=float(min(offsets_r)),
        r_max_offsets=float(max(offsets_r)),
        n_daily=len(data),
        nw_slope=float(fit.params[1]),
        nw_t=float(fit.tvalues[1]),
        nw_p=float(fit.pvalues[1]),
        r2=float(fit.rsquared),
    )


def predictive_tests(metrics: pd.DataFrame, spy: pd.Series, horizon: int) -> pd.DataFrame:
    """Forward test (anticipation) and same-period test (reaction) for several signals."""
    spy = spy.reindex(metrics.index)
    fwd = forward_log_return(spy, horizon)
    past = past_log_return(spy, horizon)
    signals = {
        "Δ mean_corr": past_change(metrics["mean_corr"], horizon),
        "mean_corr level": metrics["mean_corr"],
        "Δ absorption_ratio": past_change(metrics["absorption_ratio"], horizon),
    }
    rows = []
    for name, sig in signals.items():
        rows.append({"test": "forward", **predictive_test(sig, fwd, horizon, name).__dict__})
    rows.append(
        {"test": "same period", **predictive_test(signals["Δ mean_corr"], past, horizon, "Δ mean_corr").__dict__}
    )
    return pd.DataFrame(rows)


def panic_precision(metrics: pd.DataFrame, spy: pd.Series, threshold: float = 0.10) -> dict[str, float]:
    """How often PANIC days coincide with SPY already being in a > threshold drawdown."""
    spy = spy.reindex(metrics.index)
    drawdown = spy / spy.cummax() - 1
    panic = metrics["regime"].eq(PANIC)
    return {
        "panic_days": int(panic.sum()),
        "share_in_drawdown": float((drawdown[panic] <= -threshold).mean()) if panic.any() else np.nan,
        "share_in_5pct_drawdown": float((drawdown[panic] <= -0.05).mean()) if panic.any() else np.nan,
    }
