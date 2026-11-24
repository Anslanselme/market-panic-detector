"""Shared application state; widgets listen to its signals instead of calling each other."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from panic_detector.i18n import Translator
from panic_detector.ui.data_store import DashboardData, WindowData


class AppState(QObject):
    date_changed = Signal(int)        # index in the current window's days
    window_changed = Signal(int)      # window length in days
    language_changed = Signal(str)
    animations_changed = Signal(bool)
    selection_changed = Signal(object)  # ticker (str) or None

    def __init__(self, data: DashboardData, window: int, language: str = "en") -> None:
        super().__init__()
        self.data = data
        self.translator = Translator(language)
        self._window = window if window in data.windows else next(iter(data.windows))
        self._index = len(self.current) - 1
        self.animations = True
        self.selected: str | None = None

    # -- accessors
    @property
    def window(self) -> int:
        return self._window

    @property
    def current(self) -> WindowData:
        return self.data.windows[self._window]

    @property
    def index(self) -> int:
        return self._index

    @property
    def language(self) -> str:
        return self.translator.language

    def tr(self, key: str, **kwargs: object) -> str:
        return self.translator.tr(key, **kwargs)

    # -- mutators
    def set_index(self, index: int) -> None:
        index = min(max(int(index), 0), len(self.current) - 1)
        if index != self._index:
            self._index = index
            self.date_changed.emit(index)

    def set_window(self, window: int) -> None:
        if window == self._window or window not in self.data.windows:
            return
        date = self.current.dates[self._index]
        self._window = window
        self._index = self.current.index_of(date)  # keep the same date
        self.window_changed.emit(window)
        self.date_changed.emit(self._index)

    def set_language(self, language: str) -> None:
        if language != self.translator.language:
            self.translator.language = language
            self.language_changed.emit(language)

    def set_selected(self, ticker: str | None) -> None:
        """Company shown in the card and highlighted in the network (None closes it)."""
        if ticker is not None and ticker not in self.data.stocks:
            return
        if ticker != self.selected:
            self.selected = ticker
            self.selection_changed.emit(ticker)

    def set_animations(self, enabled: bool) -> None:
        if enabled != self.animations:
            self.animations = enabled
            self.animations_changed.emit(enabled)
