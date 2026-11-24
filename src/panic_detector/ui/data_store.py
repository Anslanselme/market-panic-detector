"""Read-only view of the precomputed results, shaped for fast lookups by the UI."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from panic_detector.config import Settings, Universe
from panic_detector.pipeline import WindowResults


def to_epoch_seconds(index: pd.DatetimeIndex) -> np.ndarray:
    return ((index - pd.Timestamp("1970-01-01")) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)


@dataclass
class DaySnapshot:
    tickers: list[str]
    positions: np.ndarray  # N x 2
    positions3d: np.ndarray  # N x 3
    edges: np.ndarray      # (N-1) x 2 indices into tickers
    edge_rho: np.ndarray   # (N-1)


class WindowData:
    """Metrics, trees and layouts of one rolling window, indexed by day position."""

    def __init__(self, results: WindowResults) -> None:
        self.window = results.window
        self.metrics = results.metrics
        self.dates = results.metrics.index
        self.x = to_epoch_seconds(self.dates)
        self._layout = results.layout.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)
        self._edges = results.edges.sort_values("date", kind="stable").reset_index(drop=True)
        self._layout_bounds = self._bounds(self._layout["date"])
        self._edge_bounds = self._bounds(self._edges["date"])
        xy = self._layout[["x", "y"]].to_numpy()
        self.extent = float(np.abs(xy).max()) if len(xy) else 1.0
        # Default framing: one common scale for every date (so contraction stays visible),
        # sized on a typical wide day (85th percentile of the daily tree radius) rather than
        # the single widest day; the rare wider days can be zoomed out with the wheel.
        radius = pd.Series(np.hypot(xy[:, 0], xy[:, 1])).groupby(self._layout["date"].to_numpy()).max()
        self.framing_extent = float(radius.quantile(0.85)) if len(radius) else 1.0
        xyz = self._layout[["x3", "y3", "z3"]].to_numpy()
        radius3 = pd.Series(np.linalg.norm(xyz, axis=1)).groupby(self._layout["date"].to_numpy()).max()
        self.framing_extent3d = float(radius3.quantile(0.85)) if len(radius3) else 1.0
        self._cache: dict[int, DaySnapshot] = {}

    def _bounds(self, column: pd.Series) -> tuple[np.ndarray, np.ndarray]:
        values = column.to_numpy()
        target = self.dates.to_numpy().astype(values.dtype)
        return np.searchsorted(values, target, "left"), np.searchsorted(values, target, "right")

    def __len__(self) -> int:
        return len(self.dates)

    def index_of(self, date: pd.Timestamp) -> int:
        """Position of the last day on or before `date` (clamped to the range)."""
        pos = int(self.dates.searchsorted(date, side="right")) - 1
        return min(max(pos, 0), len(self.dates) - 1)

    def row(self, i: int) -> pd.Series:
        return self.metrics.iloc[i]

    def snapshot(self, i: int) -> DaySnapshot:
        if i in self._cache:
            return self._cache[i]
        lo, hi = self._layout_bounds[0][i], self._layout_bounds[1][i]
        lay = self._layout.iloc[lo:hi]
        tickers = lay["ticker"].tolist()
        lookup = {t: k for k, t in enumerate(tickers)}
        lo, hi = self._edge_bounds[0][i], self._edge_bounds[1][i]
        ed = self._edges.iloc[lo:hi]
        edges = np.array([[lookup[s], lookup[t]] for s, t in zip(ed["source"], ed["target"])], dtype=int)
        snap = DaySnapshot(tickers, lay[["x", "y"]].to_numpy(), lay[["x3", "y3", "z3"]].to_numpy(),
                           edges.reshape(-1, 2), ed["rho"].to_numpy())
        if len(self._cache) > 512:
            self._cache.clear()
        self._cache[i] = snap
        return snap


class DashboardData:
    def __init__(
        self,
        results: dict[int, WindowResults],
        prices: pd.DataFrame,
        universe: Universe,
        settings: Settings,
    ) -> None:
        self.universe = universe
        self.settings = settings
        self.windows = {w: WindowData(r) for w, r in sorted(results.items())}
        self.stocks = universe.by_ticker()
        leaders = [t for t in universe.leaders if t in prices.columns]
        lead = prices[leaders]
        # Rebased to 100 at each leader's first available close (2007 or its IPO).
        first = lead.apply(lambda s: s.loc[s.first_valid_index()])
        self.leader_prices = 100 * lead / first
        self.price_x = to_epoch_seconds(self.leader_prices.index)
        # Daily log returns of the benchmark and every stock, for the company cards.
        columns = [universe.benchmark, *universe.tickers]
        self.returns = np.log(prices[columns]).diff().iloc[1:]
        self.listed = {t: prices[t].first_valid_index() for t in universe.tickers}
        self.crises = [
            (c.id, to_epoch_seconds(pd.DatetimeIndex([c.start, c.end]))) for c in settings.crises
        ]
