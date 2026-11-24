"""Minimum spanning tree in 3-D (OpenGL): orbit, zoom, glowing breathing nodes.

Mouse: left-drag rotates around the tree, right- or middle-drag pans, wheel zooms,
double-click resets the camera. Hovering a bubble shows its details; clicking it
emits `node_clicked(ticker)`.

Same mood rules as the 2-D view: sector colours, size by number of links, additive
neon halos that breathe with the regime, red links in PANIC, smooth glide between
dates, slow automatic rotation in CALM. Farther nodes are dimmed for depth.
"""

from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QToolTip, QWidget

from panic_detector.ui import theme
from panic_detector.ui.company_card import CompanyCard
from panic_detector.ui.effects import mix
from panic_detector.ui.kpi_panels import Panel
from panic_detector.ui.network_view import (
    PULSE_PERIOD_S,
    TICK_MS,
    edge_color,
    halo_tint,
    hidden_in_stack,
    node_sizes,
    node_tooltip,
    sector_legend_html,
    spread_labels_2d,
)
from panic_detector.ui.state import AppState

HALO_LAYERS = ((2.0, 0.15), (3.2, 0.06), (5.0, 0.028))  # (size factor, alpha), additive: soft lamp bokeh
AUTO_ROTATE_DEG_S = 5.0      # slow orbit in CALM
IDLE_BEFORE_ROTATE_S = 4.0   # auto-rotation waits after any user interaction
DEPTH_DIM = 0.5              # farthest nodes keep 50 % of their brightness
CLICK_TOLERANCE_PX = 4.0
CAMERA_ELEVATION, CAMERA_AZIMUTH = 22.0, 45.0


def opengl_available() -> bool:
    """True if PyOpenGL is installed and a desktop OpenGL >= 2.1 context can be created."""
    try:
        import OpenGL  # noqa: F401
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext

        ctx = QOpenGLContext()
        if not ctx.create():
            return False
        surface = QOffscreenSurface()
        surface.setFormat(ctx.format())
        surface.create()
        if not surface.isValid() or not ctx.makeCurrent(surface):
            return False
        fmt = ctx.format()
        ok = not ctx.isOpenGLES() and (fmt.majorVersion(), fmt.minorVersion()) >= (2, 1)
        ctx.doneCurrent()
        return ok
    except Exception:
        return False


# ----------------------------------------------------------------------------- geometry (no GL needed)


def project_points(mvp: np.ndarray, points: np.ndarray, width: float, height: float) -> tuple[np.ndarray, np.ndarray]:
    """World points (N x 3) -> screen pixels (N x 2, y down) and clip-space depth (N)."""
    homogeneous = np.c_[points, np.ones(len(points))]
    clip = homogeneous @ mvp.T
    w = np.where(np.abs(clip[:, 3]) < 1e-12, 1e-12, clip[:, 3])
    ndc = clip[:, :3] / w[:, None]
    screen = np.c_[(ndc[:, 0] + 1.0) * 0.5 * width, (1.0 - ndc[:, 1]) * 0.5 * height]
    return screen, clip[:, 3]


def pick_node(screen: np.ndarray, depth: np.ndarray, sizes_px: np.ndarray, click: tuple[float, float],
              tolerance: float = CLICK_TOLERANCE_PX) -> int | None:
    """Index of the bubble under the cursor; the one nearest to the camera wins on overlap."""
    if len(screen) == 0:
        return None
    gap = np.hypot(screen[:, 0] - click[0], screen[:, 1] - click[1])
    hit = (gap <= sizes_px / 2.0 + tolerance) & (depth > 0)
    if not hit.any():
        return None
    candidates = np.flatnonzero(hit)
    return int(candidates[np.argmin(depth[candidates])])


def depth_brightness(points: np.ndarray, camera: np.ndarray) -> np.ndarray:
    """1 for the nearest node, DEPTH_DIM for the farthest."""
    d = np.linalg.norm(points - camera, axis=1)
    span = d.max() - d.min() if len(d) else 0.0
    if span < 1e-9:
        return np.ones(len(points))
    return 1.0 - (1.0 - DEPTH_DIM) * (d - d.min()) / span


def rgba(color: str | QColor, alpha: float = 1.0, scale: float = 1.0) -> tuple[float, float, float, float]:
    c = QColor(color) if isinstance(color, str) else color
    return (c.redF() * scale, c.greenF() * scale, c.blueF() * scale, alpha)


# ----------------------------------------------------------------------------- view


def _make_gl_view_class():
    """Build the GLViewWidget subclass lazily, so importing this module never needs OpenGL."""
    import pyqtgraph.opengl as gl

    class NeonGLView(gl.GLViewWidget):
        hovered = Signal(QPointF, QPointF)   # local pos, global pos
        clicked = Signal(QPointF)
        reset_requested = Signal()
        interacted = Signal()

        def __init__(self) -> None:
            super().__init__()
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep ← → for the date
            self.setMouseTracking(True)
            self._press = None

        def mousePressEvent(self, ev):  # noqa: N802
            self._press = ev.position()
            self.interacted.emit()
            super().mousePressEvent(ev)

        def mouseMoveEvent(self, ev):  # noqa: N802
            if ev.buttons() == Qt.MouseButton.NoButton:
                self.hovered.emit(ev.position(), ev.globalPosition())
                return
            self.interacted.emit()
            if ev.buttons() == Qt.MouseButton.RightButton:  # right-drag pans like the middle button
                diff = ev.position() - self.mousePos
                self.mousePos = ev.position()
                self.pan(diff.x(), diff.y(), 0, relative="view-upright")
                return
            super().mouseMoveEvent(ev)

        def mouseReleaseEvent(self, ev):  # noqa: N802
            if self._press is not None and (ev.position() - self._press).manhattanLength() < 4 \
                    and ev.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit(ev.position())
            self._press = None

        def mouseDoubleClickEvent(self, ev):  # noqa: N802
            self.reset_requested.emit()

        def wheelEvent(self, ev):  # noqa: N802
            self.interacted.emit()
            super().wheelEvent(ev)

        def mvp(self) -> np.ndarray:
            w, h = max(self.width(), 1), max(self.height(), 1)
            proj = self.projectionMatrix((0, 0, w, h), (0, 0, w, h))
            m = proj * self.viewMatrix()
            return np.array(m.data(), dtype=float).reshape(4, 4).T  # Qt stores column-major

        def camera(self) -> np.ndarray:
            p = self.cameraPosition()
            return np.array([p.x(), p.y(), p.z()])

    return NeonGLView


class LabelOverlay(QWidget):
    """Transparent layer over the 3-D view: leader labels and their thin leader lines.

    Drawn with QPainter in screen space (crisp text, works in window grabs), and
    transparent to the mouse so rotation and picking go to the 3-D view underneath.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.labels: list[tuple[str, str, np.ndarray, np.ndarray]] = []
        parent.installEventFilter(self)
        self.resize(parent.size())

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            self.resize(obj.size())
        return False

    def set_labels(self, labels: list[tuple[str, str, np.ndarray, np.ndarray]]) -> None:
        self.labels = labels  # (ticker, colour, anchor px, label px)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        painter.setPen(QPen(theme.qcolor(theme.TEXT_MUTED, 0.55), 1))
        for _t, _c, anchor, label in self.labels:
            painter.drawLine(QPointF(*anchor), QPointF(*label))
        for ticker, color, _a, label in self.labels:
            painter.setFont(theme.font(9 if ticker == "NVDA" else 8, bold=True))
            rect = painter.fontMetrics().boundingRect(ticker)
            x, y = label[0] - rect.width() / 2, label[1] + rect.height() / 3
            painter.setPen(theme.qcolor(theme.BACKGROUND, 0.9))  # dark outline for contrast
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawText(QPointF(x + dx, y + dy), ticker)
            painter.setPen(QColor(color))
            painter.drawText(QPointF(x, y), ticker)
        painter.end()


class NetworkView3D(Panel):
    node_clicked = Signal(str)

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import pyqtgraph.opengl as gl

        self.state = state
        self.view = _make_gl_view_class()()
        self.view.setBackgroundColor(theme.PANEL)
        self.view.opts["fov"] = 45
        self.body.addWidget(self.view, 1)
        self.legend = QLabel()
        self.legend.setObjectName("kpiSub")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setWordWrap(True)
        self.body.addWidget(self.legend)

        self.edge_glow = gl.GLLinePlotItem(mode="lines", width=4, antialias=True, glOptions="additive")
        self.edge_line = gl.GLLinePlotItem(mode="lines", width=1.5, antialias=True, glOptions="translucent")
        self.halos = [gl.GLScatterPlotItem(pxMode=True, glOptions="additive") for _ in HALO_LAYERS]
        self.leader_glow = gl.GLScatterPlotItem(pxMode=True, glOptions="additive")
        self.nodes = gl.GLScatterPlotItem(pxMode=True, glOptions="translucent")
        # Selected company: bright links and a white glow around the bubble.
        self.sel_edges = gl.GLLinePlotItem(mode="lines", width=3, antialias=True, glOptions="additive")
        self.sel_glow = gl.GLScatterPlotItem(pxMode=True, glOptions="additive")
        for item in (self.edge_glow, self.edge_line, self.sel_edges, *self.halos, self.leader_glow,
                     self.sel_glow, self.nodes):
            self.view.addItem(item)
        self.overlay = LabelOverlay(self.view)
        self.card = CompanyCard(state, self)

        self.tickers: list[str] = []
        self.display = np.zeros((0, 3))
        self.target = np.zeros((0, 3))
        self.degree = np.zeros(0, dtype=int)
        self.edges = np.zeros((0, 2), dtype=int)
        self.sizes = np.zeros(0)
        self.regime, self.percentile = "warmup", math.nan
        self.ease_tau_ms = float(state.data.settings["ui"]["transition_ms"]) / 3.0
        self._pulse = 0.5
        self._last_tick = time.monotonic()
        self._t0 = time.monotonic()
        self._last_interaction = -1e9
        self._user_camera = False

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.view.hovered.connect(self._hovered)
        self.view.clicked.connect(self._clicked)
        self.view.reset_requested.connect(self.reset_camera)
        self.view.interacted.connect(self._touched)
        state.date_changed.connect(self.refresh)
        state.window_changed.connect(lambda _w: self.reset_camera())
        state.language_changed.connect(lambda _l: self.retranslate())
        state.animations_changed.connect(lambda _a: self._apply_style())
        state.selection_changed.connect(lambda _t: self._draw())
        self.node_clicked.connect(state.set_selected)
        self.reset_camera()
        self.retranslate()

    # ------------------------------------------------------------------ texts & camera
    def retranslate(self) -> None:
        self.set_title(self.state.tr("panel.network"))
        self.legend.setText(sector_legend_html(self.state))

    def reset_camera(self) -> None:
        radius = self.state.current.framing_extent3d
        w, h = max(self.view.width(), 1), max(self.view.height(), 1)
        half_fov = math.radians(self.view.opts["fov"] / 2)  # horizontal field of view
        # Fit a typical tree in the shorter screen dimension (a 3-D blob projects smaller
        # than its radius, so no extra margin is needed).
        distance = 0.95 * radius / (math.tan(half_fov) * min(1.0, h / w))
        self.view.setCameraPosition(pos=pg_vector(0, 0, 0), distance=distance,
                                    elevation=CAMERA_ELEVATION, azimuth=CAMERA_AZIMUTH)
        self._user_camera = False
        self.refresh(self.state.index, animate=False)

    def drawing_area(self):
        return self.view.geometry()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Keep the tree framed while the window settles, until the user moves the camera.
        if not self._user_camera and self.view.width() > 50:
            self.reset_camera()
        if self.card.isVisible():
            self.card.place(self.drawing_area())

    def _touched(self) -> None:
        self._last_interaction = time.monotonic()
        self._user_camera = True

    # ------------------------------------------------------------------ data
    def refresh(self, index: int, animate: bool = True) -> None:
        if hidden_in_stack(self):
            return  # the 2-D view is showing; we catch up when switched back
        wd = self.state.current
        snap = wd.snapshot(index)
        row = wd.row(index)
        previous = dict(zip(self.tickers, self.display))
        self.tickers = list(snap.tickers)
        self.target = snap.positions3d.astype(float).copy()
        self.display = np.array([previous.get(t, p) for t, p in zip(self.tickers, self.target)], dtype=float)
        if not (animate and self.state.animations):
            self.display = self.target.copy()
        self.edges = snap.edges
        self.degree = np.bincount(snap.edges.ravel(), minlength=len(self.tickers))
        self.sizes = node_sizes(self.degree) * 1.1
        self.regime, self.percentile = str(row["regime"]), float(row["percentile"])
        self._apply_style()

    def _apply_style(self) -> None:
        """Colours and sizes for the current regime, depth and pulse; then positions."""
        if not len(self.tickers):
            return
        stocks = self.state.data.stocks
        sectors = [stocks[t].sector for t in self.tickers]
        bright = depth_brightness(self.display, self.view.camera())
        self.node_colors = np.array([rgba(theme.SECTOR_COLORS[s], 0.95, b) for s, b in zip(sectors, bright)])
        tint, amount = halo_tint(self.regime)
        self.halo_base = np.array([rgba(mix(theme.SECTOR_COLORS[s], tint, amount), 1.0, b)
                                   for s, b in zip(sectors, bright)])
        color, alpha = edge_color(self.regime, self.percentile)
        self.edge_line.setData(color=rgba(color, alpha))
        self.edge_glow.setData(color=rgba(color, alpha * 0.3))
        self.leader_idx = [k for k, t in enumerate(self.tickers) if t in theme.LEADER_COLORS]
        self.leader_colors = np.array([rgba(theme.LEADER_COLORS[self.tickers[k]], 0.35) for k in self.leader_idx]) \
            if self.leader_idx else np.zeros((0, 4))
        self._draw()

    def pulse_period(self) -> float:
        return PULSE_PERIOD_S.get(self.regime, 3.0)

    def _draw(self) -> None:
        pos = self.display
        seg = pos[self.edges.ravel()] if len(self.edges) else np.zeros((0, 3))
        self.edge_line.setData(pos=seg)
        self.edge_glow.setData(pos=seg)
        pulse = self._pulse if self.state.animations else 0.6
        scale = 0.85 + 0.35 * pulse
        for item, (factor, alpha) in zip(self.halos, HALO_LAYERS):
            colors = self.halo_base.copy()
            colors[:, 3] = alpha * (0.45 + 0.55 * pulse)
            item.setData(pos=pos, size=self.sizes * factor * scale, color=colors)
        self.nodes.setData(pos=pos, size=self.sizes, color=self.node_colors)
        lead = self.leader_idx
        if lead:
            self.leader_glow.setData(pos=pos[lead], size=self.sizes[lead] + 10, color=self.leader_colors)
        else:
            self.leader_glow.setData(pos=np.zeros((0, 3)))
        self._draw_selection()
        self._place_labels()

    def _draw_selection(self) -> None:
        ticker = self.state.selected
        if ticker is None or ticker not in self.tickers or not len(self.display):
            self.sel_edges.setData(pos=np.zeros((0, 3)))
            self.sel_glow.setData(pos=np.zeros((0, 3)))
            return
        k = self.tickers.index(ticker)
        touching = self.edges[(self.edges == k).any(axis=1)] if len(self.edges) else np.zeros((0, 2), int)
        seg = self.display[touching.ravel()] if len(touching) else np.zeros((0, 3))
        self.sel_edges.setData(pos=seg, color=rgba(theme.TEXT, 0.85))
        self.sel_glow.setData(pos=self.display[[k]], size=np.array([self.sizes[k] + 18]),
                              color=np.array([rgba(theme.TEXT, 0.55)]))

    def _place_labels(self) -> None:
        """Leader labels in screen space: pushed outward from the tree centre, de-overlapped."""
        lead = self.leader_idx
        if not lead:
            self.overlay.set_labels([])
            return
        w, h = self.view.width(), self.view.height()
        screen, depth = project_points(self.view.mvp(), self.display, w, h)
        centre, _ = project_points(self.view.mvp(), self.display.mean(axis=0, keepdims=True), w, h)
        anchors = screen[lead]
        d = anchors - centre[0]
        n = np.hypot(d[:, 0], d[:, 1])[:, None]
        d = np.where(n > 1e-6, d / np.maximum(n, 1e-6), np.array([0.0, -1.0]))
        offset = (self.sizes[lead] / 2 + 14)[:, None]
        names = [self.tickers[k] for k in lead]
        widths = np.array([7.5 * len(t) + 8 for t in names])
        placed = spread_labels_2d(anchors + d * offset, widths)
        self.overlay.set_labels([(t, theme.LEADER_COLORS[t], a, p) for t, a, p, z in
                                 zip(names, anchors, placed, depth[lead]) if z > 0])

    # ------------------------------------------------------------------ picking
    def node_at(self, pos: QPointF) -> int | None:
        if not len(self.tickers):
            return None
        screen, depth = project_points(self.view.mvp(), self.display, self.view.width(), self.view.height())
        return pick_node(screen, depth, self.sizes, (pos.x(), pos.y()))

    def _hovered(self, pos: QPointF, global_pos: QPointF) -> None:
        k = self.node_at(pos)
        if k is None:
            QToolTip.hideText()
            return
        ticker = self.tickers[k]
        QToolTip.showText(global_pos.toPoint(), node_tooltip(self.state, ticker, int(self.degree[k])), self.view)

    def _clicked(self, pos: QPointF) -> None:
        k = self.node_at(pos)
        if k is not None:
            self.node_clicked.emit(self.tickers[k])

    # ------------------------------------------------------------------ animation
    def _tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        if not self.state.animations or not len(self.tickers) or hidden_in_stack(self):
            return
        delta = self.target - self.display
        if len(delta) and np.abs(delta).max() > 1e-4:
            self.display += delta * (1.0 - math.exp(-dt * 1000.0 / self.ease_tau_ms))
        elif len(delta):
            self.display = self.target.copy()
        self._pulse = 0.5 + 0.5 * math.sin(2 * math.pi * (now - self._t0) / self.pulse_period())
        if self.regime in ("calm", "warmup") and now - self._last_interaction > IDLE_BEFORE_ROTATE_S:
            self.view.orbit(AUTO_ROTATE_DEG_S * dt, 0)
        self._apply_style()  # depth shading follows the camera; pulse follows time


def pg_vector(x: float, y: float, z: float):
    from pyqtgraph import Vector

    return Vector(x, y, z)
