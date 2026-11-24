import dataclasses

import pandas as pd
import pytest

from panic_detector.config import (
    MAX_SECTOR_GROUPS,
    REQUIRED_TICKERS,
    ConfigError,
    load_settings,
    load_universe,
    validate_universe,
)


def test_universe_has_50_stocks_with_required_leaders():
    u = load_universe()
    assert len(u.stocks) == 50
    assert set(REQUIRED_TICKERS) <= set(u.tickers)
    assert set(u.leaders) == set(REQUIRED_TICKERS)


def test_universe_sector_groups():
    u = load_universe()
    assert len(u.sectors) <= MAX_SECTOR_GROUPS
    assert {s.sector for s in u.stocks} == set(u.sectors)  # every group is used


def test_benchmark_is_spy_and_outside_network():
    u = load_universe()
    assert u.benchmark == "SPY"
    assert "SPY" not in u.tickers


def test_validation_rejects_missing_leader():
    u = load_universe()
    broken = dataclasses.replace(u, stocks=tuple(s for s in u.stocks if s.ticker != "NVDA"))
    with pytest.raises(ConfigError):
        validate_universe(broken)


def test_settings_are_consistent():
    s = load_settings()
    assert s.windows == [60, 250]
    assert 0 < s["metrics"]["min_coverage"] <= 1
    r = s["regime"]
    assert 0 < r["tension_percentile"] < r["panic_percentile"] < 100
    assert pd.Timestamp(s["data"]["start"]) == pd.Timestamp("2007-01-01")
    for c in s.crises:
        assert pd.Timestamp(c.start) < pd.Timestamp(c.end)
