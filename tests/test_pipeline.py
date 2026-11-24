import dataclasses

import numpy as np
import pandas as pd
import pytest

from panic_detector import pipeline
from panic_detector.config import Stock, load_settings, load_universe


@pytest.fixture
def small_setup(tmp_path):
    u = load_universe()
    stocks = tuple(Stock(f"S{i}", f"Stock {i}", u.sectors[i % 8]) for i in range(12))
    universe = dataclasses.replace(u, stocks=stocks, leaders=())
    s = load_settings()
    raw = {
        **s.raw,
        "data": {**s.raw["data"], "cache_dir": str(tmp_path / "cache")},
        "metrics": {**s.raw["metrics"], "windows": [20, 60]},
        "regime": {**s.raw["regime"], "min_history": 30},
    }
    settings = dataclasses.replace(s, raw=raw)

    rng = np.random.default_rng(0)
    tickers = [universe.benchmark, *universe.tickers]
    idx = pd.bdate_range("2007-01-03", periods=300, name="date")
    prices = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (300, 13)), axis=0)),
                          index=idx, columns=tickers)
    from panic_detector import data
    data.save_cache(prices, settings.cache_dir, settings["data"]["start"])
    return universe, settings


def test_pipeline_computes_then_reads_cache(small_setup, monkeypatch):
    universe, settings = small_setup
    results = pipeline.run(universe, settings)
    assert set(results) == {20, 60}
    r = results[20]
    assert len(r.metrics) == 299 - 20 + 1
    assert {"mean_corr", "lambda1", "absorption_ratio", "mp_lambda_plus", "regime",
            "percentile", "mst_mean_distance"} <= set(r.metrics.columns)
    # N - 1 edges and N positions every day.
    assert (r.edges.groupby("date").size() == 11).all()
    assert (r.layout.groupby("date").size() == 12).all()
    assert list(r.layout.columns) == ["date", "ticker", "x", "y", "x3", "y3", "z3"]
    assert r.layout[["x3", "y3", "z3"]].notna().all().all()
    assert pipeline.cache_is_fresh(settings)

    def boom(*_a, **_k):
        raise AssertionError("should not recompute")

    monkeypatch.setattr(pipeline, "compute_window", boom)
    again = pipeline.run(universe, settings)
    pd.testing.assert_frame_equal(again[20].metrics, r.metrics, check_freq=False)
    pd.testing.assert_frame_equal(again[60].layout, results[60].layout)


def test_cache_goes_stale_when_settings_change(small_setup):
    universe, settings = small_setup
    pipeline.run(universe, settings)
    raw = {**settings.raw, "regime": {**settings.raw["regime"], "panic_percentile": 95}}
    assert not pipeline.cache_is_fresh(dataclasses.replace(settings, raw=raw))
