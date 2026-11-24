"""Minimum spanning tree at the selected date, drawn as a glowing, breathing neon network.

- Nodes: filled with their sector colour, sized by number of links, with a soft halo.
- Leaders: a ring and a label in their signature colour (NVDA in green).
- Positions come from the precomputed stable layout; on a date change nodes glide to
  their new place (exponential easing) instead of jumping.
- Mood follows the regime: slow cold breathing in CALM, faster in TENSION, fast pulse
  and red links in PANIC. Everything static when animations are off.
- Mouse wheel zooms, drag pans, double-click resets the framing. Hover shows details.
"""

from __future__ import annotations

import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QStackedWidget, QWidget

from panic_detector.ui import theme
from panic_detector.ui.company_card import CompanyCard
from panic_detector.ui.effects import mix
from panic_detector.ui.kpi_panels import Panel
from panic_detector.ui.state import AppState

TICK_MS = 33              # animation clock (~30 fps)
PULSE_PERIOD_S = {"calm": 3.0, "warmup": 3.0, "tension": 1.5, "panic": 0.6}
HALO_STEPS = 6            # discrete halo sizes (keeps pyqtgraph's symbol atlas small)
HALO_SCALE = (1.9, 2.6)   # halo diameter relative to the node, min..max of the pulse
COLD = theme.NIGHT_BLUE
EDGE_CALM = theme.CONCRETE


def move_spots(item: pg.ScatterPlotItem, pos: np.ndarray) -> bool:
    """Move existing scatter points in place (no symbol re-rendering). False if counts differ.

    Same invalidation steps as ScatterPlotItem.setData, minus rebuilding every spot,
    which is ~5x cheaper for the per-frame glide.
    """
    if len(item.data) != len(pos):
        return False
    item.data["x"] = pos[:, 0]
    item.data["y"] = pos[:, 1]
    item.prepareGeometryChange()
    item.informViewBoundsChanged()
    item.bounds = [None, None]
    item.invalidate()
    return True


def spread_labels_2d(anchors_px: np.ndarray, widths_px: np.ndarray, height_px: float = 15.0,
                     iterations: int = 30) -> np.ndarray:
    """Push overlapping label boxes apart (screen pixels), mostly vertically."""
    lab = anchors_px.astype(float).copy()
    n = len(lab)
    for _ in range(iterations):
        moved = False
        for a in range(n):
            for b in range(a + 1, n):
                dx, dy = lab[b] - lab[a]
                min_dx = (widths_px[a] + widths_px[b]) / 2
                if abs(dx) < min_dx and abs(dy) < height_px:
                    push = (height_px - abs(dy)) / 2 + 0.5
                    sign = 1.0 if dy >= 0 else -1.0
                    lab[a, 1] -= sign * push
                    lab[b, 1] += sign * push
                    moved = True
        if not moved:
            break
    return lab


def node_sizes(degree: np.ndarray) -> np.ndarray:
    return np.minimum(7.0 + 3.0 * degree, 30.0)


def edge_color(regime: str, percentile: float) -> tuple[pg.QtGui.QColor, float]:
    """Concrete-grey links in calm, warming to sodium amber through TENSION, taillight red in PANIC."""
    if regime == "panic":
        return mix(EDGE_CALM, theme.TAILLIGHT, 1.0), 0.65
    if regime == "tension" and not math.isnan(percentile):
        t = (percentile - 60.0) / 30.0
        return mix(EDGE_CALM, theme.SODIUM, 0.25 + 0.6 * t), 0.45
    return pg.QtGui.QColor(EDGE_CALM), 0.35


def hidden_in_stack(widget: QWidget) -> bool:
    """True when the widget is a page of a QStackedWidget that currently shows another page.

    The 2-D and 3-D networks share a stack; the hidden one skips all work until shown.
    """
    parent = widget.parentWidget()
    return isinstance(parent, QStackedWidget) and parent.currentWidget() is not widget


def node_tooltip(state: AppState, ticker: str, links: int) -> str:
    tr = state.tr
    stock = state.data.stocks[ticker]
    return (f"{tr('tooltip.ticker')}: {ticker}\n{tr('tooltip.name')}: {stock.name}\n"
            f"{tr('tooltip.sector')}: {tr(f'sector.{stock.sector}')}\n{tr('tooltip.links')}: {links}")


def sector_legend_html(state: AppState) -> str:
    tr = state.tr
    items = [f"<span style='color:{theme.SECTOR_COLORS[s]}'>●</span>&nbsp;"
             f"{tr(f'sector.{s}').replace(' ', '&nbsp;')}" for s in state.data.universe.sectors]
    return "&nbsp;&nbsp; ".join(items)


def halo_tint(regime: str) -> tuple[str, float]:
    """Colour pulled into the halos: cold in calm, none in tension, red in panic."""
    return {"calm": (COLD, 0.5), "warmup": (COLD, 0.5), "tension": (theme.SODIUM, 0.35),
            "panic": (theme.TAILLIGHT, 0.45)}.get(regime, (COLD, 0.0))


class NetworkView(Panel):
    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.widget = pg.PlotWidget()
        self.body.addWidget(self.widget, 1)
        self.legend = QLabel()
        self.legend.setObjectName("kpiSub")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setWordWrap(True)
        self.body.addWidget(self.legend)

        self.plot = self.widget.getPlotItem()
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setAspectLocked(True)

        self.edge_glow = pg.PlotDataItem(connect="pairs", antialias=False)
        self.edge_line = pg.PlotDataItem(connect="pairs")
        self.halo = pg.ScatterPlotItem(pen=pg.mkPen(None))
        self.nodes = pg.ScatterPlotItem(
            pen=pg.mkPen(theme.qcolor(theme.BACKGROUND, 0.9), width=1),
            hoverable=True, hoverPen=pg.mkPen(theme.TEXT, width=2), tip=self._tip,
        )
        self.rings = pg.ScatterPlotItem(brush=pg.mkBrush(None))
        self.label_lines = pg.PlotDataItem(connect="pairs", pen=pg.mkPen(theme.qcolor(theme.TEXT_MUTED, 0.5), width=1))
        # Selected company: its links drawn bright, and a white ring around it.
        self.sel_edges = pg.PlotDataItem(connect="pairs", pen=pg.mkPen(theme.qcolor(theme.TEXT, 0.9), width=2.5))
        self.sel_ring = pg.ScatterPlotItem(brush=pg.mkBrush(None), pen=pg.mkPen(theme.TEXT, width=2.5))
        self.nodes.sigClicked.connect(self._node_clicked)
        for z, item in enumerate((self.edge_glow, self.edge_line, self.sel_edges, self.halo, self.nodes,
                                  self.rings, self.sel_ring, self.label_lines)):
            item.setZValue(z)
            self.plot.addItem(item)
        self.labels: dict[str, pg.TextItem] = {}
        for ticker, color in theme.LEADER_COLORS.items():
            label = pg.TextItem(ticker, color=color, anchor=(0.5, 0.5))
            label.setFont(theme.font(9 if ticker == "NVDA" else 8, bold=True))
            label.setZValue(10)
            self.plot.addItem(label)
            self.labels[ticker] = label

        self.tickers: list[str] = []
        self.display = np.zeros((0, 2))   # positions currently drawn
        self.target = np.zeros((0, 2))    # positions of the selected date
        self.degree = np.zeros(0, dtype=int)
        self.edges = np.zeros((0, 2), dtype=int)
        self.regime, self.percentile = "warmup", math.nan
        self._halo_step = -1
        # Exponential glide: ~95 % of the way after `transition_ms` (3 time constants).
        self.ease_tau_ms = float(state.data.settings["ui"]["transition_ms"]) / 3.0
        self._last_tick = time.monotonic()
        self._t0 = time.monotonic()

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.plot.scene().sigMouseClicked.connect(self._clicked)
        self.plot.vb.sigRangeChanged.connect(lambda *_: self._place_labels())  # zoom keeps label spacing
        state.date_changed.connect(self.refresh)
        state.window_changed.connect(lambda _w: self.fit())
        state.language_changed.connect(lambda _l: self.retranslate())
        state.animations_changed.connect(self._animations_changed)
        state.selection_changed.connect(lambda _t: self._draw_selection())
        self.card = CompanyCard(state, self)
        self.fit()
        self.retranslate()

    # ------------------------------------------------------------------ selection
    def drawing_area(self):
        return self.widget.geometry()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.card.isVisible():
            self.card.place(self.drawing_area())

    def _node_clicked(self, _item, points, _event=None) -> None:
        if len(points):
            self.state.set_selected(str(points[0].data()))

    def _draw_selection(self) -> None:
        ticker = self.state.selected
        if ticker is None or ticker not in self.tickers:
            self.sel_edges.setData([], [])
            self.sel_ring.clear()
            return
        k = self.tickers.index(ticker)
        pos = self.display
        touching = self.edges[(self.edges == k).any(axis=1)] if len(self.edges) else np.zeros((0, 2), int)
        seg = pos[touching.ravel()] if len(touching) else np.zeros((0, 2))
        self.sel_edges.setData(seg[:, 0], seg[:, 1])
        self.sel_ring.setData(pos=pos[[k]], size=[node_sizes(self.degree)[k] + 12])

    # ------------------------------------------------------------------ texts
    def retranslate(self) -> None:
        tr = self.state.tr
        self.set_title(tr("panel.network"))
        self.legend.setText(sector_legend_html(self.state))

    def _tip(self, x: float, y: float, data: object) -> str:
        ticker = str(data)
        k = self.tickers.index(ticker) if ticker in self.tickers else -1
        return node_tooltip(self.state, ticker, int(self.degree[k]) if k >= 0 else 0)

    # ------------------------------------------------------------------ view
    def fit(self) -> None:
        r = self.state.current.framing_extent * 1.12
        self.plot.setRange(xRange=(-r, r), yRange=(-r, r), padding=0)
        self.refresh(self.state.index, animate=False)

    def _clicked(self, event) -> None:
        if event.double():
            self.fit()

    # ------------------------------------------------------------------ data
    def refresh(self, index: int, animate: bool = True) -> None:
        if hidden_in_stack(self):
            return  # the 3-D view is showing; we catch up when switched back
        wd = self.state.current
        snap = wd.snapshot(index)
        row = wd.row(index)
        previous = dict(zip(self.tickers, self.display))
        self.tickers = list(snap.tickers)
        self.target = snap.positions.astype(float).copy()
        # Keep drawn positions of stocks already on screen; new listings appear in place.
        self.display = np.array([previous.get(t, p) for t, p in zip(self.tickers, self.target)], dtype=float)
        if not (animate and self.state.animations):
            self.display = self.target.copy()
        self.edges = snap.edges
        self.degree = np.bincount(snap.edges.ravel(), minlength=len(self.tickers))
        self.regime, self.percentile = str(row["regime"]), float(row["percentile"])
        self._restyle()
        self._draw()

    def _restyle(self) -> None:
        """Colours and sizes: recomputed on date changes only, not every frame."""
        stocks = self.state.data.stocks
        sectors = [stocks[t].sector for t in self.tickers]
        self.sizes = node_sizes(self.degree)
        self.node_brushes = [pg.mkBrush(theme.SECTOR_COLORS[s]) for s in sectors]
        tint, amount = halo_tint(self.regime)
        self.halo_brushes = [pg.mkBrush(theme.qcolor(mix(theme.SECTOR_COLORS[s], tint, amount).name(), 0.22))
                             for s in sectors]
        color, alpha = edge_color(self.regime, self.percentile)
        self.edge_line.setPen(pg.mkPen(theme.qcolor(color.name(), alpha), width=1.2))
        self.edge_glow.setPen(pg.mkPen(theme.qcolor(color.name(), alpha * 0.25), width=5))
        self.leader_idx = [k for k, t in enumerate(self.tickers) if t in theme.LEADER_COLORS]
        self.ring_pens = [pg.mkPen(theme.LEADER_COLORS[self.tickers[k]], width=3 if self.tickers[k] == "NVDA" else 2)
                          for k in self.leader_idx]
        self._halo_step = -1  # force halo sizes to be re-applied

    def _halo_sizes(self, step: int) -> np.ndarray:
        lo, hi = HALO_SCALE
        return self.sizes * (lo + (hi - lo) * step / (HALO_STEPS - 1))

    def _draw(self, positions_only: bool = False) -> None:
        """Redraw everything, or (during the glide) only move what is already there."""
        pos = self.display
        if len(self.edges):
            seg = pos[self.edges.ravel()]
            self.edge_line.setData(seg[:, 0], seg[:, 1])
            self.edge_glow.setData(seg[:, 0], seg[:, 1])
        leaders = self.leader_idx
        if not (positions_only and move_spots(self.halo, pos) and move_spots(self.nodes, pos)
                and (not leaders or move_spots(self.rings, pos[leaders]))):
            step = self._halo_step if self._halo_step >= 0 else HALO_STEPS // 2
            self.halo.setData(pos=pos, size=self._halo_sizes(step), brush=self.halo_brushes)
            self.nodes.setData(pos=pos, size=self.sizes, brush=self.node_brushes, data=self.tickers)
            if leaders:
                self.rings.setData(pos=pos[leaders], size=self.sizes[leaders] + 7, pen=self.ring_pens)
            else:
                self.rings.clear()
        self._place_labels()
        self._draw_selection()

    def _place_labels(self) -> None:
        """Leader labels pushed outward from the tree centre, de-overlapped on screen."""
        pos = self.display
        where = {t: k for k, t in enumerate(self.tickers)}
        shown = [t for t in self.labels if t in where]
        for ticker, label in self.labels.items():
            label.setVisible(ticker in where)
        if not shown:
            self.label_lines.setData([], [])
            return
        px, py = self.plot.vb.viewPixelSize()
        px, py = (px or 0.01), (py or 0.01)
        scale = np.array([px, py])
        anchors = np.array([pos[where[t]] for t in shown])
        # Work in screen pixels: unit vector from the tree centre to each leader.
        anchors_px = anchors / scale
        d = anchors_px - pos.mean(axis=0) / scale
        n = np.hypot(d[:, 0], d[:, 1])[:, None]
        d = np.where(n > 1e-6, d / np.maximum(n, 1e-6), np.array([0.0, 1.0]))
        offset_px = np.array([self.sizes[where[t]] / 2 + 16 for t in shown])[:, None]
        widths = np.array([7.5 * len(t) + 8 for t in shown])
        placed = spread_labels_2d(anchors_px + d * offset_px, widths) * scale
        for t, xy in zip(shown, placed):
            self.labels[t].setPos(*xy)
        seg = np.empty((2 * len(shown), 2))
        seg[0::2], seg[1::2] = anchors, placed
        self.label_lines.setData(seg[:, 0], seg[:, 1])

    # ------------------------------------------------------------------ animation
    def _animations_changed(self, enabled: bool) -> None:
        if not enabled:
            self.display = self.target.copy()
            self.halo.setOpacity(0.8)
            self._halo_step = -1
            self._draw()

    def pulse_period(self) -> float:
        return PULSE_PERIOD_S.get(self.regime, 3.0)

    def _tick(self) -> None:
        now = time.monotonic()
        dt_ms = (now - self._last_tick) * 1000.0
        self._last_tick = now
        if not self.state.animations or hidden_in_stack(self):
            return
        moved = False
        if len(self.display) and len(self.display) == len(self.target):
            delta = self.target - self.display
            if np.abs(delta).max() > 1e-4:
                self.display += delta * (1.0 - math.exp(-dt_ms / self.ease_tau_ms))
                moved = True
            elif np.abs(delta).max() > 0:
                self.display = self.target.copy()
                moved = True
        # Breathing: sinusoidal halo opacity, halo size in a few discrete steps.
        phase = 0.5 + 0.5 * math.sin(2 * math.pi * (now - self._t0) / self.pulse_period())
        self.halo.setOpacity(0.35 + 0.65 * phase)
        step = round(phase * (HALO_STEPS - 1))
        if moved:
            if step != self._halo_step:
                self._halo_step = step
                self.halo.setSize(self._halo_sizes(step))
            self._draw(positions_only=True)
        elif step != self._halo_step:
            self._halo_step = step
            self.halo.setSize(self._halo_sizes(step))
