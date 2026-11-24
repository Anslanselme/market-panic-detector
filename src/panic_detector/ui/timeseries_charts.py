"""Bottom charts: mean correlation and λ1 over time, each on its own axis."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from panic_detector.ui import theme
from panic_detector.ui.kpi_panels import Panel
from panic_detector.ui.state import AppState


class Crosshair:
    """Dashed crosshair + value label that follows the mouse over a plot."""

    def __init__(self, plot: pg.PlotItem, formatter) -> None:
        self.plot = plot
        self.formatter = formatter  # (x, y) -> html
        pen = pg.mkPen(theme.qcolor(theme.TEXT_MUTED, 0.7), width=1, style=Qt.PenStyle.DashLine)
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self.hline = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        self.label = pg.TextItem(anchor=(0, 1), fill=pg.mkBrush(theme.qcolor(theme.PANEL, 0.85)),
                                 border=pg.mkPen(theme.BORDER))
        for item in (self.vline, self.hline, self.label):
            item.setZValue(50)
            item.setVisible(False)
            plot.addItem(item, ignoreBounds=True)
        self.proxy = pg.SignalProxy(plot.scene().sigMouseMoved, rateLimit=60, slot=self._moved)

    def _moved(self, event) -> None:
        pos = event[0]
        vb = self.plot.vb
        inside = self.plot.sceneBoundingRect().contains(pos) and vb.sceneBoundingRect().contains(pos)
        for item in (self.vline, self.hline, self.label):
            item.setVisible(inside)
        if not inside:
            return
        p = vb.mapSceneToView(pos)
        html = self.formatter(p.x(), p.y())
        if html is None:
            for item in (self.vline, self.hline, self.label):
                item.setVisible(False)
            return
        self.vline.setPos(p.x())
        self.hline.setPos(p.y())
        self.label.setHtml(html)
        # Keep the label inside the view: flip it left/down near the right/top edges.
        (x0, x1), (y0, y1) = vb.viewRange()
        right = p.x() > x0 + 0.7 * (x1 - x0)
        top = p.y() > y0 + 0.7 * (y1 - y0)
        self.label.setAnchor((1 if right else 0, 0 if top else 1))
        self.label.setPos(p.x(), p.y())


def date_label(x: float) -> str:
    return pd.Timestamp(x, unit="s").strftime("%Y-%m-%d")


class MetricChart(Panel):
    """One metric over time, with glow line, crisis bands, date cursor and crosshair."""

    def __init__(self, state: AppState, column: str, title_key: str, show_mp: bool = False,
                 crisis_labels: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state, self.column, self.title_key = state, column, title_key
        self.show_mp, self.crisis_labels = show_mp, crisis_labels
        self.widget = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom", utcOffset=0)})
        self.widget.setMinimumHeight(120)
        self.body.addWidget(self.widget, 1)
        self.plot = self.widget.getPlotItem()
        self.plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.vb.setMouseEnabled(x=True, y=False)
        for axis in ("left", "bottom"):
            self.plot.getAxis(axis).setPen(pg.mkPen(theme.BORDER))
            self.plot.getAxis(axis).setTextPen(pg.mkPen(theme.TEXT_MUTED))
            self.plot.getAxis(axis).setStyle(tickFont=theme.font(8))
        self.cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(theme.qcolor(theme.CURSOR, 0.8), width=1))
        self.cursor.setZValue(40)
        self.crisis_items: list[tuple[str, pg.TextItem]] = []
        self.series_items: list[pg.PlotDataItem] = []
        self.legend_items: list = []
        self.crosshair = Crosshair(self.plot, self._format)
        self.plot.scene().sigMouseClicked.connect(self._clicked)
        self._build()
        state.window_changed.connect(lambda _w: self._build())
        state.date_changed.connect(self._move_cursor)
        state.language_changed.connect(lambda _l: self.retranslate())

    # -- building
    def _build(self) -> None:
        self.plot.clear()
        self.series_items, self.crisis_items = [], []
        wd = self.state.current
        y = wd.metrics[self.column].to_numpy(dtype=float)
        for crisis_id, (start, end) in self.state.data.crises:
            region = pg.LinearRegionItem((start, end), movable=False, brush=pg.mkBrush(*theme.CRISIS_BRUSH),
                                         pen=pg.mkPen(None))
            region.setZValue(-10)
            self.plot.addItem(region)
            if self.crisis_labels:
                label = pg.TextItem(color=theme.CRISIS_LABEL, anchor=(0, 0))
                label.setFont(theme.font(7.5))
                self.plot.addItem(label, ignoreBounds=True)
                self.crisis_items.append((crisis_id, label))
        if self.show_mp:
            mp = wd.metrics["mp_lambda_plus"].to_numpy(dtype=float)
            line = self.plot.plot(wd.x, mp, pen=pg.mkPen(theme.MP_LINE, width=1.4, style=Qt.PenStyle.DashLine))
            line.setZValue(5)
            self.mp_item = line
        self.series_items = theme.add_glow_curve(self.plot, wd.x, y, theme.SERIES_COLORS[self.column], z=10)
        self.plot.addItem(self.cursor, ignoreBounds=True)
        self.plot.addItem(self.crosshair.vline, ignoreBounds=True)
        self.plot.addItem(self.crosshair.hline, ignoreBounds=True)
        self.plot.addItem(self.crosshair.label, ignoreBounds=True)
        top = 1.08 * (max(np.nanmax(y), np.nanmax(mp)) if self.show_mp else np.nanmax(y))
        self.plot.setYRange(0, top, padding=0)
        self.plot.setXRange(wd.x[0], wd.x[-1], padding=0.01)
        self.plot.setLimits(xMin=wd.x[0] - 86400 * 30, xMax=wd.x[-1] + 86400 * 30)
        self._place_crisis_labels(top)
        self.retranslate()
        self._move_cursor(self.state.index)

    def _place_crisis_labels(self, top: float) -> None:
        # Two staggered rows so labels of close crises (late 2018 / early 2020) do not collide.
        for k, (crisis_id, label) in enumerate(self.crisis_items):
            start = dict(self.state.data.crises)[crisis_id][0]
            label.setPos(start, top * (0.99 if k % 2 == 0 else 0.88))

    def retranslate(self) -> None:
        tr = self.state.tr
        title = tr(self.title_key).upper()
        if self.show_mp:
            title += f"&nbsp;&nbsp;&nbsp;<span style='color:{theme.MP_LINE}'>- - {tr('legend.mp_threshold')}</span>"
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.setText(title)
        for crisis_id, label in self.crisis_items:
            label.setFont(theme.font(7.5))
            label.setText(tr(f"crisis.{crisis_id}"))

    # -- interaction
    def _move_cursor(self, index: int) -> None:
        self.cursor.setPos(self.state.current.x[index])

    def _nearest(self, x: float) -> int:
        xs = self.state.current.x
        return int(np.clip(np.searchsorted(xs, x), 0, len(xs) - 1))

    def _format(self, x: float, _y: float) -> str | None:
        wd = self.state.current
        if x < wd.x[0] or x > wd.x[-1]:
            return None
        i = self._nearest(x)
        row = wd.metrics.iloc[i]
        color = theme.SERIES_COLORS[self.column]
        value = row[self.column]
        html = (f"<span style='color:{theme.TEXT}'>{wd.dates[i]:%Y-%m-%d}</span><br>"
                f"<span style='color:{color}'>{value:.3f}</span>")
        if self.show_mp:
            html += f"<br><span style='color:{theme.MP_LINE}'>λ+ {row['mp_lambda_plus']:.2f}</span>"
        return html

    def _clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        vb = self.plot.vb
        if not vb.sceneBoundingRect().contains(event.scenePos()):
            return
        x = vb.mapSceneToView(event.scenePos()).x()
        self.state.set_index(self._nearest(x))

    def link_x(self, other: "MetricChart") -> None:
        self.plot.setXLink(other.plot)
