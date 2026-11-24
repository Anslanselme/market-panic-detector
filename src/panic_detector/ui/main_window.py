"""Main dashboard window: header, KPI row, network + prices, two metric charts, timeline."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from panic_detector.i18n import LANGUAGES
from panic_detector.ui import theme
from panic_detector.ui.effects import FilmOverlay, GlitchLabel
from panic_detector.ui.kpi_panels import KpiRow, glow
from panic_detector.ui.network_view import NetworkView
from panic_detector.ui.network_view3d import NetworkView3D, opengl_available
from panic_detector.ui.price_chart import PriceChart
from panic_detector.ui.state import AppState
from panic_detector.ui.timeline import Timeline
from panic_detector.ui.timeseries_charts import MetricChart


class MainWindow(QMainWindow):
    def __init__(self, state: AppState, network_view: str = "auto") -> None:
        """`network_view`: view shown first, "3d", "2d", or "auto" (3-D when OpenGL works).

        Both views are built when OpenGL is available; a 2D / 3D switch flips between
        them, and the hidden one stops updating.
        """
        super().__init__()
        self.state = state
        self.has_3d = opengl_available()
        start_3d = self.has_3d and network_view in ("3d", "auto")
        self.resize(1600, 1000)
        self.setMinimumSize(1200, 780)

        root = QWidget()
        root.setObjectName("root")  # ochre side bands, like the cover
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)
        self.setCentralWidget(root)

        # Header: title + subtitle on the left, controls on the right.
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = GlitchLabel(seed=3)
        self.title.setStyleSheet(f"font-size: 17pt; font-weight: 700; letter-spacing: 3px; color: {theme.TEXT};")
        glow(self.title, theme.SODIUM, 18)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch(1)

        self.window_label = QLabel()
        self.window_label.setObjectName("kpiSub")
        header.addWidget(self.window_label)
        self.window_group = QButtonGroup(self)
        self.window_buttons: dict[int, QPushButton] = {}
        for w in state.data.windows:
            button = QPushButton()
            button.setCheckable(True)
            button.setChecked(w == state.window)
            button.clicked.connect(lambda _c=False, w=w: state.set_window(w))
            self.window_group.addButton(button)
            self.window_buttons[w] = button
            header.addWidget(button)
        header.addSpacing(16)
        self.view_label = QLabel()
        self.view_label.setObjectName("kpiSub")
        header.addWidget(self.view_label)
        self.view_group = QButtonGroup(self)
        self.view_buttons: dict[str, QPushButton] = {}
        for mode in ("2d", "3d"):
            button = QPushButton()
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, m=mode: self.set_network_view(m))
            self.view_group.addButton(button)
            self.view_buttons[mode] = button
            header.addWidget(button)
        self.view_buttons["3d"].setEnabled(self.has_3d)
        header.addSpacing(16)
        self.animations = QCheckBox()
        self.animations.setChecked(state.animations)
        self.animations.toggled.connect(state.set_animations)
        header.addWidget(self.animations)
        header.addSpacing(16)
        self.language_label = QLabel()
        self.language_label.setObjectName("kpiSub")
        header.addWidget(self.language_label)
        self.language = QComboBox()
        for code in LANGUAGES:
            self.language.addItem(state.translator.tr(f"lang.{code}"), code)
        self.language.setCurrentIndex(LANGUAGES.index(state.language))
        self.language.currentIndexChanged.connect(lambda i: state.set_language(self.language.itemData(i)))
        header.addWidget(self.language)
        outer.addLayout(header)

        self.kpis = KpiRow(state)
        outer.addWidget(self.kpis)

        center = QSplitter(Qt.Orientation.Horizontal)
        self.network_stack = QStackedWidget()
        self.network_2d = NetworkView(state)
        self.network_stack.addWidget(self.network_2d)
        self.network_3d = NetworkView3D(state) if self.has_3d else None
        if self.network_3d is not None:
            self.network_stack.addWidget(self.network_3d)
        self.network = self.network_2d
        self.prices = PriceChart(state)
        center.addWidget(self.network_stack)
        center.addWidget(self.prices)
        center.setSizes([760, 840])
        outer.addWidget(center, 6)

        self.corr_chart = MetricChart(state, "mean_corr", "panel.mean_corr", crisis_labels=True)
        self.lambda_chart = MetricChart(state, "lambda1", "panel.lambda1", show_mp=True)
        self.lambda_chart.link_x(self.corr_chart)
        outer.addWidget(self.corr_chart, 2)
        outer.addWidget(self.lambda_chart, 2)

        self.timeline = Timeline(state)
        outer.addWidget(self.timeline)
        self.film = FilmOverlay(root)  # grain + vignette on top of everything

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.timeline.toggle)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: state.set_index(state.index + 1))
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: state.set_index(state.index - 1))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=lambda: state.set_selected(None))

        state.window_changed.connect(self._window_changed)
        state.language_changed.connect(lambda _l: self.retranslate())
        state.date_changed.connect(lambda _i: self._update_glitch())
        state.window_changed.connect(lambda _w: self._update_glitch())
        state.animations_changed.connect(lambda _a: self._update_glitch())
        self.set_network_view("3d" if start_3d else "2d")
        self.retranslate()
        self._update_glitch()

    def set_network_view(self, mode: str) -> None:
        """Show the 2-D or 3-D network; the hidden view pauses until it is shown again."""
        view = self.network_3d if mode == "3d" and self.network_3d is not None else self.network_2d
        self.network = view
        self.network_stack.setCurrentWidget(view)
        self.view_buttons["3d" if view is self.network_3d else "2d"].setChecked(True)
        view.refresh(self.state.index, animate=False)  # catch up on what it missed while hidden
        view.card.refresh()

    def _window_changed(self, window: int) -> None:
        self.window_buttons[window].setChecked(True)

    def _update_glitch(self) -> None:
        """Glitch / chromatic aberration on the title and regime badge, in PANIC only."""
        panic = str(self.state.current.row(self.state.index)["regime"]) == "panic"
        on = panic and self.state.animations
        self.title.set_glitch(on)
        self.kpis.regime.badge.set_glitch(on)

    def retranslate(self) -> None:
        tr = self.state.tr
        self.setWindowTitle(tr("app.title"))
        self.title.setText(tr("app.title"))
        self.subtitle.setText(tr("app.subtitle"))
        self.window_label.setText(tr("controls.window"))
        self.language_label.setText(tr("controls.language"))
        self.animations.setText(tr("controls.animations"))
        self.view_label.setText(tr("controls.view"))
        self.view_buttons["2d"].setText(tr("controls.view_2d"))
        self.view_buttons["3d"].setText(tr("controls.view_3d"))
        self.view_buttons["3d"].setToolTip("" if self.has_3d else tr("controls.no_opengl"))
        for w, button in self.window_buttons.items():
            button.setText(tr("controls.days", n=w))
