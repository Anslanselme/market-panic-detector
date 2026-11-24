"""Capture the dashboard in every language for the READMEs (docs/img/).

Opens a real window (not offscreen, so system fonts and OpenGL are used; the network is
in 3-D when available), then for each language and each scene: switches language live,
jumps to the date, opens a company card if the scene has one, lets the nodes glide into
place, and grabs the window.

Usage:
    python scripts/make_screenshots.py                 # all languages, default scenes
    python scripts/make_screenshots.py --lang fr       # one language
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from panic_detector.__main__ import load_data
from panic_detector.config import PROJECT_ROOT
from panic_detector.i18n import LANGUAGES
from panic_detector.ui import theme
from panic_detector.ui.main_window import MainWindow
from panic_detector.ui.state import AppState

SCENES = {                             # scene -> (date, company card to open or None)
    "panic": ("2020-03-16", None),     # COVID crash: contracted red network, glitch
    "calm": ("2017-08-01", None),      # record-calm summer 2017: spread-out tree
    "card": ("2024-08-05", "NVDA"),    # a company card opened from the network
}
SIZE = (1600, 1000)
SETTLE_MS = 1200  # time for the glide (and for a glitch frame to show in PANIC)
JPEG_QUALITY = 90


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", choices=LANGUAGES, nargs="*", default=list(LANGUAGES))
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--out", default=str(PROJECT_ROOT / "docs" / "img"))
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    theme.configure_pyqtgraph()
    app.setStyleSheet(theme.stylesheet())
    app.setFont(theme.font(10))
    data = load_data(app, args.lang[0], refresh=False)
    state = AppState(data, args.window, args.lang[0])
    window = MainWindow(state)
    window.resize(*SIZE)
    window.show()

    out = Path(args.out)
    out = out if out.is_absolute() else PROJECT_ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(lang, scene, date, ticker) for lang in args.lang for scene, (date, ticker) in SCENES.items()]
    written: list[str] = []

    def run_next() -> None:
        if not jobs:
            print("\n".join(written))
            app.quit()
            return
        lang, scene, date, ticker = jobs.pop(0)
        window.language.setCurrentIndex(window.language.findData(lang))  # same path as a user click
        state.set_selected(ticker)
        state.set_index(state.current.index_of(pd.Timestamp(date)))

        def grab() -> None:
            # JPEG: the film grain makes PNGs ~1.3 MB each; JPEG keeps them light for the READMEs.
            path = out / f"dashboard_{scene}_{lang}.jpg"
            window.grab().save(str(path), "JPG", JPEG_QUALITY)
            written.append(str(path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path))
            run_next()

        QTimer.singleShot(SETTLE_MS, grab)

    QTimer.singleShot(800, run_next)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
