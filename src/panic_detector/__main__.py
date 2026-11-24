"""Launch the dashboard: python -m panic_detector [--window 60] [--lang fr] [--date 2020-03-16]."""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from panic_detector import pipeline
from panic_detector.config import load_settings, load_universe
from panic_detector.data import load_prices
from panic_detector.i18n import LANGUAGES, Translator
from panic_detector.ui import theme
from panic_detector.ui.data_store import DashboardData
from panic_detector.ui.main_window import MainWindow
from panic_detector.ui.state import AppState


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = load_settings()
    ui = settings["ui"]
    p = argparse.ArgumentParser(prog="python -m panic_detector", description="Market Panic Detector dashboard")
    p.add_argument("--window", type=int, default=int(ui["default_window"]), choices=settings.windows)
    p.add_argument("--lang", default=ui["default_language"], choices=LANGUAGES)
    p.add_argument("--date", default=None, help="initial date, e.g. 2020-03-16 (default: latest)")
    p.add_argument("--refresh", action="store_true", help="re-download prices before starting")
    p.add_argument("--no-animations", action="store_true", help="start with animations off")
    p.add_argument("--view", choices=["auto", "2d", "3d"], default="auto",
                   help="network view at start (auto = 3-D when OpenGL is available)")
    return p.parse_args(argv)


def load_data(app: QApplication, language: str, refresh: bool) -> DashboardData:
    universe, settings = load_universe(), load_settings()
    tr = Translator(language).tr
    results = None
    if refresh or not pipeline.cache_is_fresh(settings):
        dialog = QProgressDialog(tr("status.computing"), None, 0, 1000)
        dialog.setWindowTitle(tr("app.title"))
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumDuration(0)
        dialog.show()

        def progress(fraction: float, _message: str) -> None:
            dialog.setValue(int(1000 * fraction))
            app.processEvents()

        results = pipeline.run(universe, settings, refresh=refresh, progress=progress)
        dialog.close()
    else:
        results = {w: pipeline.load_results(w, settings) for w in settings.windows}
    return DashboardData(results, load_prices(universe, settings), universe, settings)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.configure_pyqtgraph()
    app.setStyleSheet(theme.stylesheet())
    app.setFont(theme.font(10))
    try:
        data = load_data(app, args.lang, args.refresh)
    except Exception as exc:  # network down and no cache, etc.
        QMessageBox.critical(None, Translator(args.lang).tr("app.title"), str(exc))
        return 1
    state = AppState(data, args.window, args.lang)
    state.set_animations(not args.no_animations)
    if args.date:
        state.set_index(state.current.index_of(pd.Timestamp(args.date)))
    window = MainWindow(state, network_view=args.view)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
