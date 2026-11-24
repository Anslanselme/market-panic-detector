import dataclasses
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Headless Qt for the UI tests (set before any QApplication is created).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The offscreen platform does not see system fonts by itself: point it at them, so the
# glyph-coverage tests check the fonts a real window would use.
if sys.platform == "win32" and "QT_QPA_FONTDIR" not in os.environ:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if fonts.is_dir():
        os.environ["QT_QPA_FONTDIR"] = str(fonts)


@pytest.fixture(scope="session")
def dashboard_data(tmp_path_factory):
    """Precomputed results on 420 days of synthetic prices for the real 50-stock universe."""
    from panic_detector import data, pipeline
    from panic_detector.config import load_settings, load_universe
    from panic_detector.ui.data_store import DashboardData

    universe = load_universe()
    s = load_settings()
    cache = tmp_path_factory.mktemp("cache")
    raw = {**s.raw, "data": {**s.raw["data"], "cache_dir": str(cache)},
           "regime": {**s.raw["regime"], "min_history": 50}}
    settings = dataclasses.replace(s, raw=raw)
    tickers = [universe.benchmark, *universe.tickers]
    n = 420
    rng = np.random.default_rng(0)
    market = rng.normal(0, 0.01, (n, 1)) * np.linspace(0.5, 3, n)[:, None]  # rising common factor
    rets = market + rng.normal(0, 0.012, (n, len(tickers)))
    prices = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)),
                          index=pd.bdate_range("2007-01-03", periods=n, name="date"), columns=tickers)
    prices.iloc[:150, tickers.index("META")] = np.nan  # a late listing
    data.save_cache(prices, settings.cache_dir, settings["data"]["start"])
    results = pipeline.run(universe, settings)
    return DashboardData(results, data.load_prices(universe, settings), universe, settings)
