"""Time slider with play/pause and playback speed."""

from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, Qt, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from panic_detector.ui.kpi_panels import Panel
from panic_detector.ui.state import AppState


class Timeline(Panel):
    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        ui = state.data.settings["ui"]
        self.speeds = [int(s) for s in ui["playback_speeds"]]
        self.fps = float(ui["playback_fps"])
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(int(1000 / self.fps))
        self.timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()
        self._carry = 0.0  # fractional days not yet played

        self.title.hide()
        row = QHBoxLayout()
        row.setSpacing(10)
        self.play = QPushButton()
        self.play.setCheckable(True)
        self.play.setMinimumWidth(110)
        self.play.toggled.connect(self._toggled)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(state.set_index)
        self.speed_label = QLabel()
        self.speed = QComboBox()
        self.start_label, self.end_label = QLabel(), QLabel()
        for w in (self.start_label, self.end_label, self.speed_label):
            w.setObjectName("kpiSub")
        row.addWidget(self.play)
        row.addWidget(self.start_label)
        row.addWidget(self.slider, 1)
        row.addWidget(self.end_label)
        row.addSpacing(12)
        row.addWidget(self.speed_label)
        row.addWidget(self.speed)
        self.body.addLayout(row)

        state.date_changed.connect(self._sync)
        state.window_changed.connect(lambda _w: self._reset_range())
        state.language_changed.connect(lambda _l: self.retranslate())
        self._reset_range()
        self.retranslate()

    def retranslate(self) -> None:
        tr = self.state.tr
        current = max(self.speed.currentIndex(), 0)
        self.speed.blockSignals(True)
        self.speed.clear()
        self.speed.addItems([tr("controls.speed_value", n=s) for s in self.speeds])
        self.speed.setCurrentIndex(current)
        self.speed.blockSignals(False)
        self.speed_label.setText(tr("controls.speed"))
        self._update_play_text()

    def _update_play_text(self) -> None:
        tr = self.state.tr
        self.play.setText(f"❚❚  {tr('controls.pause')}" if self.play.isChecked() else f"▶  {tr('controls.play')}")

    def _reset_range(self) -> None:
        wd = self.state.current
        self.slider.blockSignals(True)
        self.slider.setRange(0, len(wd) - 1)
        self.slider.setValue(self.state.index)
        self.slider.blockSignals(False)
        self.start_label.setText(f"{wd.dates[0]:%Y-%m}")
        self.end_label.setText(f"{wd.dates[-1]:%Y-%m}")

    def _sync(self, index: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)

    def _toggled(self, playing: bool) -> None:
        if playing:
            if self.state.index >= len(self.state.current) - 1:
                self.state.set_index(0)  # restart from the beginning
            self._carry = 0.0
            self._clock.start()
            self.timer.start()
        else:
            self.timer.stop()
        self._update_play_text()

    def _tick(self) -> None:
        """Advance by elapsed time, not by timer count, so a slow frame never slows playback."""
        speed = self.speeds[max(self.speed.currentIndex(), 0)]
        self._carry += self._clock.restart() / 1000.0 * self.fps * speed
        step = int(self._carry)
        if step == 0:
            return
        self._carry -= step
        nxt = self.state.index + step
        last = len(self.state.current) - 1
        self.state.set_index(min(nxt, last))
        if nxt >= last:
            self.play.setChecked(False)

    def toggle(self) -> None:
        self.play.setChecked(not self.play.isChecked())
