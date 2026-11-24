"""Small visual effects: glitch / chromatic-aberration label, colour mixing."""

from __future__ import annotations

import random

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QLabel, QWidget

from panic_detector.ui import theme

GLITCH_MS = 70
GRAIN_TILE = 256
GRAIN_ALPHA = 13          # max opacity of a grain speck (0-255): barely visible
VIGNETTE_ALPHA = 120      # darkness reached in the corners (0-255)


class FilmOverlay(QWidget):
    """Night-photo finish over the whole window: fine static grain and a soft vignette.

    Rendered once per window size into a pixmap; painting only blits the exposed part,
    so it costs almost nothing when the charts below update. Mouse events pass through.
    """

    def __init__(self, parent: QWidget, seed: int = 7) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._grain = self._make_grain(seed)
        self._pixmap = QPixmap()
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.raise_()

    @staticmethod
    def _make_grain(seed: int) -> QImage:
        rng = np.random.default_rng(seed)
        shade = rng.integers(0, 2, (GRAIN_TILE, GRAIN_TILE), dtype=np.uint8) * 255  # light or dark speck
        alpha = (rng.random((GRAIN_TILE, GRAIN_TILE)) ** 3 * GRAIN_ALPHA).astype(np.uint8)
        rgba = np.dstack([shade, (shade * 0.9).astype(np.uint8), (shade * 0.75).astype(np.uint8), alpha])
        rgba = np.ascontiguousarray(rgba)
        image = QImage(rgba.data, GRAIN_TILE, GRAIN_TILE, GRAIN_TILE * 4, QImage.Format.Format_RGBA8888)
        return image.copy()  # own the pixels (the numpy buffer is temporary)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
            self.raise_()
        return False

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._render()
        super().resizeEvent(event)

    def _render(self) -> None:
        w, h = max(self.width(), 1), max(self.height(), 1)
        self._pixmap = QPixmap(w, h)
        self._pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(self._pixmap)
        p.drawTiledPixmap(0, 0, w, h, QPixmap.fromImage(self._grain))
        # Radius 0.6 x diagonal: the corners (0.5 x diagonal) get a soft, partial darkening.
        gradient = QRadialGradient(QPointF(w / 2, h / 2), 0.6 * (w * w + h * h) ** 0.5)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.55, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, QColor(0, 0, 0, VIGNETTE_ALPHA))
        p.fillRect(0, 0, w, h, gradient)
        p.end()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.drawPixmap(event.rect(), self._pixmap, event.rect())
        painter.end()


def mix(color_a: str, color_b: str, t: float) -> QColor:
    """Linear blend between two hex colours (t = 0 -> a, t = 1 -> b)."""
    a, b = QColor(color_a), QColor(color_b)
    t = min(max(t, 0.0), 1.0)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


class GlitchLabel(QLabel):
    """QLabel that, when glitching, splits into red/amber ghosts and jitters a horizontal slice.

    Kept subtle: 1-3 px channel offsets, an occasional slice shift, and clean frames in between.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None, seed: int | None = None) -> None:
        super().__init__(text, parent)
        self._color = QColor(theme.TEXT)
        self._glitching = False
        self._offset = 0
        self._slice: tuple[float, float, int] | None = None
        self._rng = random.Random(seed)
        self._timer = QTimer(self)
        self._timer.setInterval(GLITCH_MS)
        self._timer.timeout.connect(self._jitter)

    @property
    def glitching(self) -> bool:
        return self._glitching

    def set_text_color(self, color: str) -> None:
        """Colour of the main text while glitching (the owner styles the normal state)."""
        self._color = QColor(color)
        self.update()

    def set_glitch(self, enabled: bool) -> None:
        if enabled == self._glitching:
            return
        self._glitching = enabled
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()
            self._offset, self._slice = 0, None
        self.update()

    def _jitter(self) -> None:
        r = self._rng.random()
        if r < 0.25:  # clean frame: makes the glitch flicker instead of a constant blur
            self._offset, self._slice = 0, None
        else:
            self._offset = self._rng.choice((1, 2, 2, 3))
            self._slice = None
            if r > 0.8:
                top = self._rng.uniform(0.15, 0.7)
                self._slice = (top, top + self._rng.uniform(0.08, 0.25), self._rng.choice((-6, -4, 4, 6)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if not self._glitching or (self._offset == 0 and self._slice is None):
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        rect = self.contentsRect()
        flags = int(self.alignment()) or int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        text = self.text()
        d = self._offset
        # Warm chromatic aberration (taillight red / sodium amber), like a night photo.
        for color, dx in ((theme.qcolor(theme.TAILLIGHT, 0.75), -d), (theme.qcolor(theme.SODIUM, 0.6), d)):
            painter.setPen(color)
            painter.drawText(rect.translated(dx, 0), flags, text)
        painter.setPen(self._color)
        if self._slice is None:
            painter.drawText(rect, flags, text)
        else:
            top, bottom, shift = self._slice
            y0, y1 = int(rect.top() + top * rect.height()), int(rect.top() + bottom * rect.height())
            painter.save()
            painter.setClipRect(QRect(rect.left(), rect.top(), rect.width(), y0 - rect.top()))
            painter.drawText(rect, flags, text)
            painter.setClipRect(QRect(rect.left(), y1, rect.width(), rect.bottom() - y1 + 1))
            painter.drawText(rect, flags, text)
            painter.setClipRect(QRect(rect.left(), y0, rect.width(), y1 - y0))
            painter.drawText(rect.translated(shift, 0), flags, text)
            painter.restore()
        painter.end()
