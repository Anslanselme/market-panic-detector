"""Top row of big-number panels: mean correlation, λ1, absorption ratio, regime, date."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from panic_detector.ui import theme
from panic_detector.ui.effects import GlitchLabel
from panic_detector.ui.state import AppState

CHANGE_LAG = 20  # trading days used for the ▲/▼ change


class Panel(QFrame):
    """Dark rounded panel with a small uppercase title."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(10, 8, 10, 8)
        self.body.setSpacing(2)
        self.body.addWidget(self.title)

    def set_title(self, text: str) -> None:
        self.title.setText(text.upper())


def glow(widget: QWidget, color: str, radius: float = 22) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setOffset(0, 0)
    effect.setBlurRadius(radius)
    effect.setColor(theme.qcolor(color, 0.85))
    widget.setGraphicsEffect(effect)
    return effect


class KpiCard(Panel):
    def __init__(self, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title.setObjectName("kpiTitle")
        self.value = QLabel("–")
        self.value.setObjectName("kpiValue")
        self.value.setStyleSheet(f"color: {accent};")
        glow(self.value, accent, 16)
        self.sub = QLabel()
        self.sub.setObjectName("kpiSub")
        self.sub.setTextFormat(Qt.TextFormat.RichText)
        self.sub2 = QLabel()
        self.sub2.setObjectName("kpiSub")
        for w in (self.value, self.sub, self.sub2):
            self.body.addWidget(w)
        self.body.addStretch(1)


class RegimeCard(Panel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title.setObjectName("kpiTitle")
        self.badge = GlitchLabel("–", seed=7)
        self.badge.setObjectName("kpiValue")
        self.badge_glow = glow(self.badge, theme.REGIME_COLORS["calm"], 26)
        self.sub = QLabel()
        self.sub.setObjectName("kpiSub")
        self.body.addWidget(self.badge)
        self.body.addWidget(self.sub)
        self.body.addStretch(1)
        self.regime = "warmup"

    def set_regime(self, regime: str, label: str) -> None:
        self.regime = regime
        color = theme.REGIME_COLORS.get(regime, theme.TEXT_MUTED)
        self.badge.setText(f"{theme.REGIME_ICONS.get(regime, '')} {label}")
        self.badge.setStyleSheet(f"color: {color};")
        self.badge.set_text_color(color)
        self.badge_glow.setColor(theme.qcolor(color, 0.9))


class KpiRow(QWidget):
    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.corr = KpiCard(theme.SERIES_COLORS["mean_corr"])
        self.lambda1 = KpiCard(theme.SERIES_COLORS["lambda1"])
        self.absorption = KpiCard(theme.TEXT)
        self.regime = RegimeCard()
        self.date = KpiCard(theme.TEXT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for card, stretch in ((self.corr, 3), (self.lambda1, 3), (self.absorption, 3), (self.regime, 4), (self.date, 3)):
            layout.addWidget(card, stretch)
        state.date_changed.connect(self.refresh)
        state.window_changed.connect(lambda _w: self.refresh())
        state.language_changed.connect(lambda _l: self.retranslate())
        self.retranslate()

    def retranslate(self) -> None:
        tr = self.state.tr
        self.corr.set_title(tr("kpi.mean_corr"))
        self.lambda1.set_title(tr("kpi.lambda1"))
        self.absorption.set_title(tr("kpi.absorption"))
        self.regime.set_title(tr("kpi.regime"))
        self.date.set_title(tr("kpi.date"))
        self.refresh()

    def _change(self, column: str, fmt: str) -> str:
        wd, i = self.state.current, self.state.index
        if i < CHANGE_LAG:
            return ""
        now, before = wd.metrics[column].iloc[i], wd.metrics[column].iloc[i - CHANGE_LAG]
        delta = now - before
        return theme.arrow_html(delta, self.state.tr("kpi.change", arrow="", value=fmt.format(delta)).strip())

    def refresh(self) -> None:
        tr, wd, i = self.state.tr, self.state.current, self.state.index
        row = wd.row(i)
        self.corr.value.setText(f"{row['mean_corr']:.3f}")
        self.corr.sub.setText(self._change("mean_corr", "{:+.3f}"))
        self.lambda1.value.setText(f"{row['lambda1']:.1f}")
        self.lambda1.sub.setText(self._change("lambda1", "{:+.1f}"))
        self.lambda1.sub2.setText(
            f"{tr('kpi.lambda1_share', pct=f'{100 * row['lambda1_share']:.0f} %')} · "
            f"{tr('kpi.mp_ceiling', value=f'{row['mp_lambda_plus']:.2f}')}"
        )
        self.absorption.value.setText(f"{100 * row['absorption_ratio']:.1f} %")
        self.absorption.sub.setText(self._change("absorption_ratio", "{:+.1%}"))
        k = max(1, round(row["n_stocks"] * float(self.state.data.settings["metrics"]["absorption_fraction"])))
        self.absorption.sub2.setText(tr("kpi.absorption_detail", k=k))
        regime = str(row["regime"])
        self.regime.set_regime(regime, tr(f"regime.{regime}"))
        pct = row["percentile"]
        self.regime.sub.setText(tr("kpi.percentile", pct=f"{pct:.0f}") if not math.isnan(pct) else "")
        self.date.value.setText(wd.dates[i].strftime("%Y-%m-%d"))
        self.date.sub.setText(tr("kpi.n_stocks", n=int(row["n_stocks"])))
        self.date.sub2.setText(tr("controls.days", n=wd.window))
