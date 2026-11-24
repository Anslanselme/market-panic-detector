"""Floating card with a company's details, shown over the network when a bubble is clicked.

It follows the selected date, window and language; links in the "Linked to" list open
the neighbour's card. Close with the ✕ button or Esc.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from panic_detector.ui import theme
from panic_detector.ui.company import company_profile
from panic_detector.ui.state import AppState

CARD_WIDTH = 300
MARGIN = 10
MAX_NEIGHBOURS = 8


def accent_color(state: AppState, ticker: str) -> str:
    return theme.LEADER_COLORS.get(ticker) or theme.SECTOR_COLORS[state.data.stocks[ticker].sector]


def _num(value: float, fmt: str) -> str:
    return "–" if value is None or math.isnan(value) else fmt.format(value)


class CompanyCard(QFrame):
    def __init__(self, state: AppState, parent: QWidget) -> None:
        super().__init__(parent)
        self.state = state
        self.setObjectName("companyCard")
        self.setFixedWidth(CARD_WIDTH)

        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.setWordWrap(True)
        self.close_button = QToolButton()
        self.close_button.setText("✕")
        self.close_button.setAutoRaise(True)
        self.close_button.clicked.connect(lambda: state.set_selected(None))
        head = QHBoxLayout()
        head.addWidget(self.title, 1)
        head.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)

        self.sector = QLabel()
        self.sector.setObjectName("kpiSub")
        self.sector.setWordWrap(True)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.stats = QLabel()
        self.stats.setTextFormat(Qt.TextFormat.RichText)
        self.stats.setWordWrap(True)
        self.neighbours = QLabel()
        self.neighbours.setTextFormat(Qt.TextFormat.RichText)
        self.neighbours.setWordWrap(True)
        self.neighbours.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.neighbours.linkActivated.connect(self._open_link)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)
        layout.addLayout(head)
        for w in (self.sector, self.description, self.stats, self.neighbours):
            layout.addWidget(w)

        state.selection_changed.connect(lambda _t: self.refresh())
        state.date_changed.connect(lambda _i: self.refresh())
        state.window_changed.connect(lambda _w: self.refresh())
        state.language_changed.connect(lambda _l: self.refresh())
        self.hide()

    def _open_link(self, link: str) -> None:
        if link.startswith("ticker:"):
            self.state.set_selected(link.split(":", 1)[1])

    def place(self, area: QRect) -> None:
        """Pin the card to the top-right corner of `area` (the network drawing)."""
        self.move(area.right() - self.width() - MARGIN, area.top() + MARGIN)
        self.raise_()

    def refresh(self) -> None:
        ticker = self.state.selected
        if ticker is None:
            self.hide()
            return
        tr, state = self.state.tr, self.state
        p = company_profile(state.data, state.window, state.index, ticker)
        color = accent_color(state, ticker)
        self.setStyleSheet(
            f"QFrame#companyCard {{ background: rgba(11, 13, 20, 240);"
            f" border: 1px solid {color}; border-radius: 8px; }}"
            f" QToolButton {{ color: {theme.TEXT_MUTED}; border: none; font-size: 11pt; }}"
            f" QToolButton:hover {{ color: {theme.TEXT}; }}"
        )
        self.close_button.setToolTip(tr("card.close"))
        self.title.setText(f"<span style='color:{color}; font-size:14pt; font-weight:700'>{ticker}</span>"
                           f"&nbsp;&nbsp;<span style='color:{theme.TEXT}; font-size:10.5pt'>{p.name}</span>")
        sector = tr(f"sector.{p.sector}")
        listed = tr("card.listed", date=f"{p.listed:%Y-%m-%d}") if p.listed is not None else ""
        self.sector.setText(f"{sector} · {listed}" if listed else sector)
        self.description.setText(tr(f"company.{ticker}"))

        ret = p.total_return
        ret_html = "–" if math.isnan(ret) else theme.arrow_html(ret, f"{ret:+.1%}")
        rows = [
            (tr("card.avg_corr"), _num(p.avg_corr, "{:.2f}")),
            (tr("card.beta"), _num(p.beta, "{:.2f}")),
            (tr("card.vol"), _num(p.volatility, "{:.0%}")),
            (tr("card.return"), ret_html),
        ]
        table = "".join(
            f"<tr><td style='color:{theme.TEXT_MUTED}; padding-right:10px'>{label}</td>"
            f"<td align='right' style='color:{theme.TEXT}'>{value}</td></tr>" for label, value in rows
        )
        self.stats.setText(
            f"<div style='color:{theme.TEXT_MUTED}; font-size:8.5pt'>{tr('card.window', n=p.window)}"
            f" · {p.date:%Y-%m-%d}</div><table width='100%'>{table}</table>"
        )

        if not p.in_network:
            self.neighbours.setText(f"<i style='color:{theme.TEXT_MUTED}'>{tr('card.absent')}</i>")
        else:
            links = "<br>".join(
                f"<a href='ticker:{t}' style='color:{accent_color(state, t)}; text-decoration:none'>{t}</a>"
                f"&nbsp;<span style='color:{theme.TEXT_MUTED}'>{state.data.stocks[t].name} · ρ {rho:.2f}</span>"
                for t, rho in p.neighbours[:MAX_NEIGHBOURS]
            )
            self.neighbours.setText(
                f"<span style='color:{theme.TEXT_MUTED}; font-size:8.5pt'>"
                f"{tr('card.neighbours')} · {tr('card.links', n=len(p.neighbours))}</span><br>{links}"
            )
        self.show()
        self._fit_height()
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "drawing_area"):
            self.place(parent.drawing_area())

    def _fit_height(self) -> None:
        """Height for the fixed width, once the wrapped texts are known (CJK wraps differently)."""
        layout = self.layout()
        layout.invalidate()
        layout.activate()
        self.setFixedHeight(layout.totalHeightForWidth(CARD_WIDTH))
