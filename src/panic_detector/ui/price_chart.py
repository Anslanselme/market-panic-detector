"""Leaders' prices rebased to 100, log scale, with a vertical line at the selected date."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from panic_detector.ui import theme
from panic_detector.ui.kpi_panels import Panel
from panic_detector.ui.state import AppState
from panic_detector.ui.timeseries_charts import Crosshair


class LogPriceAxis(pg.AxisItem):
    """Show 100, 1 000, 10 000 instead of 10^2, 10^3 on the log axis."""

    def tickStrings(self, values, scale, spacing):
        return [f"{10 ** v:,.0f}".replace(",", " ") if v < 6 else f"{10 ** v:.0e}" for v in values]


class ClampedDateAxis(pg.DateAxisItem):
    """Date axis that shows no ticks after the last data point (the right margin holds labels)."""

    def __init__(self, last_x: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self.last_x = last_x

    def tickValues(self, minVal, maxVal, size):  # noqa: N802 (pyqtgraph API)
        values = super().tickValues(minVal, maxVal, size)
        return [(spacing, [v for v in ticks if v <= self.last_x]) for spacing, ticks in values]


def spread_labels(positions: dict[str, float], min_gap: float) -> dict[str, float]:
    """Move label positions apart so consecutive ones are at least `min_gap` apart.

    Keeps the group centred on the original positions.
    """
    if not positions:
        return {}
    names = sorted(positions, key=positions.get)
    ys = np.array([positions[n] for n in names], dtype=float)
    out = ys.copy()
    for k in range(1, len(out)):
        out[k] = max(out[k], out[k - 1] + min_gap)
    out -= (out - ys).mean()  # recentre the pushed block
    for k in range(1, len(out)):  # recentring cannot break the gaps, but keep it strict
        out[k] = max(out[k], out[k - 1] + min_gap)
    return dict(zip(names, out))


class PriceChart(Panel):
    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        data = state.data
        self.widget = pg.PlotWidget(axisItems={
            "bottom": ClampedDateAxis(data.price_x[-1], orientation="bottom", utcOffset=0),
            "left": LogPriceAxis(orientation="left"),
        })
        self.body.addWidget(self.widget, 1)
        self.plot = self.widget.getPlotItem()
        self.plot.setLogMode(y=True)
        self.plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        for axis in ("left", "bottom"):
            self.plot.getAxis(axis).setPen(pg.mkPen(theme.BORDER))
            self.plot.getAxis(axis).setTextPen(pg.mkPen(theme.TEXT_MUTED))
            self.plot.getAxis(axis).setStyle(tickFont=theme.font(8))

        x = data.price_x
        prices = data.leader_prices
        # Draw from the back: GOOGL (pale) first, NVDA last so it sits on top.
        order = [t for t in reversed(list(theme.LEADER_COLORS)) if t in prices.columns]
        ends = {}
        for z, ticker in enumerate(order):
            y = prices[ticker].to_numpy(dtype=float)
            ok = np.isfinite(y)
            theme.add_glow_curve(self.plot, x[ok], y[ok], theme.LEADER_COLORS[ticker], z=z)
            ends[ticker] = np.log10(y[ok][-1])
        logs = np.log10(prices.to_numpy(dtype=float)[np.isfinite(prices.to_numpy(dtype=float))])
        y_lo, y_hi = logs.min() - 0.1, logs.max() + 0.15
        # Direct labels at the curve ends (never colour alone), pushed apart when they collide.
        for ticker, y_label in spread_labels(ends, min_gap=0.045 * (y_hi - y_lo)).items():
            label = pg.TextItem(ticker, color=theme.LEADER_COLORS[ticker], anchor=(0, 0.5))
            label.setFont(theme.font(8, bold=True))
            label.setPos(x[-1], y_label)
            self.plot.addItem(label, ignoreBounds=True)

        self.cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(theme.qcolor(theme.CURSOR, 0.8), width=1))
        self.cursor.setZValue(40)
        self.plot.addItem(self.cursor, ignoreBounds=True)
        self.dot_items = pg.ScatterPlotItem(size=7, pen=pg.mkPen(None))
        self.dot_items.setZValue(45)
        self.plot.addItem(self.dot_items, ignoreBounds=True)
        self.crosshair = Crosshair(self.plot, self._format)
        span = x[-1] - x[0]
        self.plot.setXRange(x[0], x[-1] + 0.06 * span, padding=0.01)  # room for end labels
        self.plot.setYRange(y_lo, y_hi, padding=0)  # fixed range: no auto-range work on updates
        self.plot.setLimits(xMin=x[0] - 86400 * 30, xMax=x[-1] + 0.1 * span)

        state.date_changed.connect(self._move_cursor)
        state.language_changed.connect(lambda _l: self.retranslate())
        self.retranslate()
        self._move_cursor(state.index)

    def retranslate(self) -> None:
        self.set_title(self.state.tr("panel.prices"))

    def _row_at(self, x_value: float) -> int:
        xs = self.state.data.price_x
        return int(np.clip(np.searchsorted(xs, x_value), 0, len(xs) - 1))

    def _move_cursor(self, index: int) -> None:
        x = self.state.current.x[index]
        self.cursor.setPos(x)
        row = self.state.data.leader_prices.iloc[self._row_at(x)]
        spots = [
            {"pos": (x, np.log10(v)), "brush": pg.mkBrush(theme.LEADER_COLORS[t])}
            for t, v in row.items() if np.isfinite(v)
        ]
        self.dot_items.setData(spots)

    def _format(self, x: float, _y: float) -> str | None:
        xs = self.state.data.price_x
        if x < xs[0] or x > xs[-1]:
            return None
        i = self._row_at(x)
        row = self.state.data.leader_prices.iloc[i]
        lines = [f"<span style='color:{theme.TEXT}'>{self.state.data.leader_prices.index[i]:%Y-%m-%d}</span>"]
        for ticker in theme.LEADER_COLORS:
            if ticker in row and np.isfinite(row[ticker]):
                lines.append(f"<span style='color:{theme.LEADER_COLORS[ticker]}'>{ticker:<5} {row[ticker]:>9,.0f}</span>")
        return "<br>".join(lines).replace(" ", "&nbsp;")
