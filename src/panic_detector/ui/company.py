"""Per-company figures for the card shown when a bubble is clicked.

Everything is computed on the same trailing window as the network (60 or 250 days)
ending at the selected date, so no future data is ever used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from panic_detector.ui.data_store import DashboardData

TRADING_DAYS = 252


@dataclass
class CompanyProfile:
    ticker: str
    name: str
    sector: str
    listed: pd.Timestamp | None
    window: int
    date: pd.Timestamp
    in_network: bool
    neighbours: list[tuple[str, float]] = field(default_factory=list)  # (ticker, rho), strongest first
    avg_corr: float = math.nan
    beta: float = math.nan
    volatility: float = math.nan  # annualised
    total_return: float = math.nan  # simple return over the window


def company_profile(data: DashboardData, window: int, index: int, ticker: str) -> CompanyProfile:
    wd = data.windows[window]
    date = wd.dates[index]
    stock = data.stocks[ticker]
    snap = wd.snapshot(index)
    profile = CompanyProfile(ticker, stock.name, stock.sector, data.listed.get(ticker), window, date,
                             in_network=ticker in snap.tickers)

    if profile.in_network:
        k = snap.tickers.index(ticker)
        linked = [(snap.tickers[b if a == k else a], float(rho))
                  for (a, b), rho in zip(snap.edges, snap.edge_rho) if k in (a, b)]
        profile.neighbours = sorted(linked, key=lambda item: -item[1])

    returns = data.returns.loc[:date].iloc[-window:]
    r = returns[ticker]
    if r.notna().sum() < 2:
        return profile
    spy = returns[data.universe.benchmark]
    both = pd.concat([r, spy], axis=1).dropna()
    if len(both) > 1 and both.iloc[:, 1].var() > 0:
        profile.beta = float(both.cov().iloc[0, 1] / both.iloc[:, 1].var())
    profile.volatility = float(r.std() * math.sqrt(TRADING_DAYS))
    profile.total_return = float(math.expm1(r.sum()))
    others = [t for t in snap.tickers if t != ticker]
    if others:
        corr = returns[others].corrwith(r)
        profile.avg_corr = float(np.nanmean(corr.to_numpy())) if corr.notna().any() else math.nan
    return profile
