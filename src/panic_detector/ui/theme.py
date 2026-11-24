"""Sodium-night visual theme: palette, fonts, Qt stylesheet and glow-line helpers.

Taken from a night photo under sodium street lamps (the cover of "I'm Wide Awake"):
near-black sky, one dominant warm amber light, concrete greys, ochre side bands,
soft bokeh glows and a little film grain.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPixmapCache, QRawFont
from PySide6.QtWidgets import QGraphicsItem

# Base palette ------------------------------------------------------------------
BACKGROUND = "#0B0A0D"   # night sky
PANEL = "#16130F"        # panels: dark, slightly warm
BORDER = "#2B241B"
TEXT = "#EFE6D4"         # warm off-white
TEXT_MUTED = "#8E8474"
GRID_ALPHA = 0.07        # grid lines barely visible

SODIUM = "#FFAA3C"       # street-lamp amber: the one dominant light
LAMP_CORE = "#FFD98A"    # hot centre of a lamp
OCHRE = "#6E4C22"        # the cover's side bands
CONCRETE = "#7A7F88"     # the overpass
NIGHT_BLUE = "#5E7FA8"
TAILLIGHT = "#E8553B"

UP = "#00E676"    # always paired with ▲
DOWN = "#FF1744"  # always paired with ▼
ARROW_UP, ARROW_DOWN, ARROW_FLAT = "▲", "▼", "■"

# Leaders: fixed signature colours (NVDA is green, never blue).
LEADER_COLORS = {          # warmed up to sit under sodium light; NVDA stays green
    "NVDA": "#A6D35B",
    "AAPL": "#C7AEE6",
    "MSFT": "#F2A24B",
    "TSLA": "#E86A4E",
    "AMZN": "#F6D879",
    "META": "#7FB0D8",
    "GOOGL": "#E9E0CF",
}

# Sector fills for network nodes: dusky, photo-like tones (no fluorescent hues).
SECTOR_COLORS = {
    "technology": "#5E7FA8",
    "communication": "#8C7AB8",
    "consumer_discretionary": "#C86F5A",
    "consumer_staples": "#6FA58C",
    "financials": "#D9A441",
    "healthcare": "#8DB36A",
    "energy_materials": "#C9773A",
    "industrials_utilities": "#8A8F98",
}

REGIME_COLORS = {
    "calm": NIGHT_BLUE,
    "tension": SODIUM,
    "panic": TAILLIGHT,
    "warmup": TEXT_MUTED,
}
REGIME_ICONS = {"calm": "☾", "tension": "◐", "panic": "⚠", "warmup": "…"}

CRISIS_BRUSH = (232, 85, 59, 20)
CRISIS_LABEL = "#E9A07E"
CURSOR = LAMP_CORE
MP_LINE = CONCRETE
SERIES_COLORS = {"mean_corr": SODIUM, "lambda1": LAMP_CORE}

# Fonts ---------------------------------------------------------------------------
MONO_FAMILIES = ["JetBrains Mono", "Consolas", "Menlo", "DejaVu Sans Mono"]
CJK_FAMILIES = ["Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Noto Sans SC", "SimHei", "WenQuanYi Micro Hei"]
# ☾ ◐ ⚠ ▶ ❚ are missing from the monospace and CJK fonts on Windows.
SYMBOL_FAMILIES = ["Segoe UI Symbol", "Apple Symbols", "Noto Sans Symbols 2", "DejaVu Sans"]


def available_families(candidates: list[str]) -> list[str]:
    installed = set(QFontDatabase.families())
    return [f for f in candidates if f in installed]


def ui_families() -> list[str]:
    """Fallback chain used for every language, resolved glyph by glyph by Qt.

    Monospace first, so digits and Latin text stay aligned even in Chinese; then a
    Simplified-Chinese font for Han characters; then a symbol font for the icons.
    """
    return [*available_families(MONO_FAMILIES), *available_families(CJK_FAMILIES),
            *available_families(SYMBOL_FAMILIES)]


def missing_glyphs(text: str, families: list[str] | None = None) -> set[str]:
    """Characters of `text` that no font of the chain can draw (they would show as boxes)."""
    raws = [QRawFont.fromFont(QFont(f)) for f in (families if families is not None else ui_families())]
    return {ch for ch in set(text) if not ch.isspace() and not any(r.supportsCharacter(ord(ch)) for r in raws)}


def font(size: float = 10, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(ui_families() or ["monospace"])
    f.setPointSizeF(size)
    f.setBold(bold)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def css_families() -> str:
    return ", ".join(f'"{f}"' for f in ui_families()) or "monospace"


def stylesheet() -> str:
    fam = css_families()
    return f"""
    QWidget {{ background: {BACKGROUND}; color: {TEXT}; font-family: {fam}; font-size: 10pt; }}
    QFrame#panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; }}
    QLabel {{ background: transparent; }}
    QLabel#panelTitle {{ color: {TEXT_MUTED}; font-size: 9pt; letter-spacing: 1px; }}
    QLabel#kpiTitle {{ color: {TEXT_MUTED}; font-size: 8.5pt; letter-spacing: 1px; }}
    QLabel#kpiValue {{ color: {TEXT}; font-size: 22pt; font-weight: 600; }}
    QLabel#kpiSub {{ color: {TEXT_MUTED}; font-size: 8.5pt; }}
    QLabel#subtitle {{ color: {TEXT_MUTED}; font-size: 9pt; }}
    QPushButton, QComboBox {{
        background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 4px;
        padding: 4px 10px; min-height: 20px;
    }}
    QPushButton:hover, QComboBox:hover {{ border-color: {TEXT_MUTED}; }}
    QPushButton:checked {{ border-color: {SODIUM}; color: {SODIUM}; }}
    QComboBox QAbstractItemView {{ background: {PANEL}; color: {TEXT}; selection-background-color: {BORDER}; }}
    QCheckBox {{ background: transparent; spacing: 6px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {SODIUM}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {LAMP_CORE}; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
    }}
    QWidget#root {{ border-left: 6px solid {OCHRE}; border-right: 6px solid {OCHRE}; }}
    QSplitter::handle {{ background: {BACKGROUND}; }}
    QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; }}
    """


PIXMAP_CACHE_MB = 256


def configure_pyqtgraph() -> None:
    pg.setConfigOptions(antialias=True, background=PANEL, foreground=TEXT_MUTED)
    # Each glow layer is cached as a plot-sized pixmap (~1.6 MB); the 36 layers overflow
    # Qt's 10 MB default and get re-stroked on every cursor move without a larger cache.
    QPixmapCache.setCacheLimit(PIXMAP_CACHE_MB * 1024)


# Glow lines --------------------------------------------------------------------
GLOW_LAYERS = ((14.0, 0.035), (8.0, 0.07), (4.0, 0.16))  # (width px, alpha): soft lamp bloom, widest first


def qcolor(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


def add_glow_curve(plot: pg.PlotItem, x, y, color: str, width: float = 2.0, z: float = 0) -> list[pg.PlotDataItem]:
    """Draw the same curve 3 times, wider and more transparent, under a sharp 2 px line."""
    items = []
    for k, (w, alpha) in enumerate(GLOW_LAYERS):
        # Wide translucent halo: anti-aliasing is invisible at this opacity but makes
        # Qt's stroker ~10x slower, so it is kept for the sharp line only.
        items.append(plot.plot(x, y, pen=pg.mkPen(qcolor(color, alpha), width=w), antialias=False))
        items[-1].setZValue(z + k * 0.01)
    items.append(plot.plot(x, y, pen=pg.mkPen(qcolor(color), width=width), antialias=True))
    items[-1].setZValue(z + 0.05)
    for it in items:
        # Cached rendering: moving the date cursor does not repaint thousands of points.
        it.curve.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        it.setClipToView(True)
        it.setDownsampling(auto=True, method="peak")  # ~2 points per screen pixel
    return items


def arrow_html(change: float, text: str) -> str:
    """Coloured change with its arrow (never colour alone)."""
    if change > 0:
        return f'<span style="color:{UP}">{ARROW_UP} {text}</span>'
    if change < 0:
        return f'<span style="color:{DOWN}">{ARROW_DOWN} {text}</span>'
    return f'<span style="color:{TEXT_MUTED}">{ARROW_FLAT} {text}</span>'
