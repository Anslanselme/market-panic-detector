import dataclasses

import numpy as np
import pandas as pd
import pytest

from panic_detector import data
from panic_detector.config import load_settings, load_universe


@pytest.fixture
def settings(tmp_path):
    s = load_settings()
    raw = {**s.raw, "data": {**s.raw["data"], "cache_dir": str(tmp_path / "cache")}}
    return dataclasses.replace(s, raw=raw)


@pytest.fixture
def universe():
    return load_universe()


def fake_prices(tickers, start="2007-01-03", days=30):
    idx = pd.bdate_range(start, periods=days, name="date")
    rng = np.random.default_rng(0)
    values = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (days, len(tickers))), axis=0))
    return pd.DataFrame(values, index=idx, columns=list(tickers))


def offline_downloader(*_args, **_kwargs):
    raise ConnectionError("network is down")


def test_cache_works_offline(settings, universe):
    tickers = [universe.benchmark, *universe.tickers]
    first = data.load_prices(universe, settings, downloader=lambda t, s, e: fake_prices(t))
    assert (settings.cache_dir / data.PRICES_FILE).exists()

    again = data.load_prices(universe, settings, downloader=offline_downloader)
    pd.testing.assert_frame_equal(first, again, check_freq=False)
    assert list(again.columns) == tickers


def test_refresh_bypasses_cache(settings, universe):
    data.load_prices(universe, settings, downloader=lambda t, s, e: fake_prices(t))
    with pytest.raises(ConnectionError):
        data.load_prices(universe, settings, refresh=True, downloader=offline_downloader)


def test_no_cache_and_offline_fails(settings, universe):
    with pytest.raises(ConnectionError):
        data.load_prices(universe, settings, downloader=offline_downloader)


def test_cache_miss_when_ticker_not_cached(settings, universe):
    tickers = [universe.benchmark, *universe.tickers]
    data.save_cache(fake_prices(tickers[:-1]), settings.cache_dir, "2007-01-01")
    assert data.read_cache(settings.cache_dir, tickers, "2007-01-01") is None


def test_retry_on_rate_limit_with_growing_delay():
    from yfinance.exceptions import YFRateLimitError

    calls, delays = [], []

    def flaky(tickers, start, end):
        calls.append(1)
        if len(calls) <= 2:
            raise YFRateLimitError()
        return fake_prices(tickers)

    out = data.download_with_retry(["SPY"], "2007-01-01", None, downloader=flaky,
                                   base_delay=2.0, sleep=delays.append)
    assert len(calls) == 3
    assert delays == [2.0, 4.0]
    assert list(out.columns) == ["SPY"]


def test_http_429_is_treated_as_rate_limit():
    delays = []

    def always_429(*_):
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    with pytest.raises(data.DataError):
        data.download_with_retry(["SPY"], "2007-01-01", None, downloader=always_429,
                                 max_retries=3, base_delay=1.0, sleep=delays.append)
    assert delays == [1.0, 2.0, 4.0]


def test_other_errors_are_not_retried():
    delays = []
    with pytest.raises(ConnectionError):
        data.download_with_retry(["SPY"], "2007-01-01", None, downloader=offline_downloader,
                                 sleep=delays.append)
    assert delays == []


def test_missing_ticker_raises(settings, universe):
    def partial(tickers, start, end):
        df = fake_prices(tickers)
        df["NVDA"] = np.nan
        return df

    with pytest.raises(data.DataError, match="NVDA"):
        data.load_prices(universe, settings, downloader=partial)


def test_extract_close_from_multiindex():
    idx = pd.bdate_range("2020-01-01", periods=3)
    cols = pd.MultiIndex.from_product([["Close", "Volume"], ["AAPL", "SPY"]])
    raw = pd.DataFrame(np.arange(12, dtype=float).reshape(3, 4), index=idx, columns=cols)
    close = data.extract_close(raw, ["SPY", "AAPL"])
    assert list(close.columns) == ["SPY", "AAPL"]
    assert close["AAPL"].tolist() == [0.0, 4.0, 8.0]
