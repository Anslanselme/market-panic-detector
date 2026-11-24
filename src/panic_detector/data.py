"""Download adjusted daily closes with yfinance and cache them as Parquet.

Usage: python -m panic_detector.data [--refresh]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from panic_detector.config import Settings, Universe, load_settings, load_universe

log = logging.getLogger(__name__)

PRICES_FILE = "prices.parquet"
MANIFEST_FILE = "prices_manifest.json"

Downloader = Callable[[Sequence[str], str, str | None], pd.DataFrame]


class DataError(RuntimeError):
    """Raised when prices cannot be obtained from the cache or from yfinance."""


class RateLimitError(RuntimeError):
    """Normalised rate-limit signal (YFRateLimitError or an HTTP 429)."""


def _is_rate_limit(exc: BaseException) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    try:
        from yfinance.exceptions import YFRateLimitError
    except ImportError:  # pragma: no cover - very old yfinance
        YFRateLimitError = ()  # type: ignore[assignment]
    if YFRateLimitError and isinstance(exc, YFRateLimitError):
        return True
    text = str(exc).lower()
    return "429" in text or "too many requests" in text or "rate limit" in text


def yfinance_download(tickers: Sequence[str], start: str, end: str | None) -> pd.DataFrame:
    """One grouped yfinance call; returns adjusted closes (dates x tickers).

    Batch downloads swallow per-ticker errors, so the shared error registry is
    inspected and a rate-limit error is re-raised to trigger the retry logic.
    """
    import yfinance as yf
    import yfinance.shared as yf_shared

    raw = yf.download(
        list(tickers),
        start=start,
        end=end,
        auto_adjust=True,
        group_by="column",
        progress=False,
        threads=True,
    )
    errors = dict(getattr(yf_shared, "_ERRORS", {}) or {})
    if any(_is_rate_limit(RuntimeError(str(msg))) for msg in errors.values()):
        raise RateLimitError(f"Rate limited on {len(errors)} ticker(s)")
    if raw is None or raw.empty:
        raise DataError("yfinance returned no data")
    return extract_close(raw, tickers)


def extract_close(raw: pd.DataFrame, tickers: Sequence[str]) -> pd.DataFrame:
    """Pick the 'Close' field out of a yfinance frame, whatever its column layout."""
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = raw.columns.get_level_values(0)
        close = raw["Close"] if "Close" in level0 else raw.xs("Close", axis=1, level=1)
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]}) if "Close" in raw else raw
    close = close.reindex(columns=list(tickers))
    close.index = pd.DatetimeIndex(pd.to_datetime(close.index)).tz_localize(None)
    close.index.name = "date"
    close.columns.name = None
    return close.sort_index().astype(float)


def download_with_retry(
    tickers: Sequence[str],
    start: str,
    end: str | None,
    *,
    downloader: Downloader = yfinance_download,
    max_retries: int = 5,
    base_delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Call the downloader, retrying rate-limit errors with a doubling delay."""
    for attempt in range(max_retries + 1):
        try:
            return downloader(tickers, start, end)
        except Exception as exc:
            if not _is_rate_limit(exc):
                raise
            if attempt == max_retries:
                raise DataError(f"Still rate limited after {max_retries} retries") from exc
            delay = base_delay * 2**attempt
            log.warning("Rate limited (attempt %d), retrying in %.0f s", attempt + 1, delay)
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def _paths(cache_dir: Path) -> tuple[Path, Path]:
    return cache_dir / PRICES_FILE, cache_dir / MANIFEST_FILE


def save_cache(prices: pd.DataFrame, cache_dir: Path, start: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    prices_path, manifest_path = _paths(cache_dir)
    prices.to_parquet(prices_path)
    manifest = {
        "tickers": list(prices.columns),
        "start": start,
        "first_date": str(prices.index.min().date()),
        "last_date": str(prices.index.max().date()),
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def read_cache(cache_dir: Path, tickers: Sequence[str], start: str) -> pd.DataFrame | None:
    """Return cached prices if they cover the requested tickers and start date."""
    prices_path, manifest_path = _paths(cache_dir)
    if not (prices_path.exists() and manifest_path.exists()):
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not set(tickers) <= set(manifest["tickers"]) or pd.Timestamp(manifest["start"]) > pd.Timestamp(start):
        return None
    prices = pd.read_parquet(prices_path)
    return prices.loc[prices.index >= pd.Timestamp(start), list(tickers)]


def load_prices(
    universe: Universe | None = None,
    settings: Settings | None = None,
    *,
    refresh: bool = False,
    downloader: Downloader = yfinance_download,
    sleep: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Adjusted closes for the benchmark + universe, from cache when possible."""
    universe = universe or load_universe()
    settings = settings or load_settings()
    cfg = settings["data"]
    tickers = [universe.benchmark, *universe.tickers]
    start, end = str(cfg["start"]), cfg.get("end")

    if not refresh:
        cached = read_cache(settings.cache_dir, tickers, start)
        if cached is not None:
            log.info("Loaded %d days x %d tickers from cache", *cached.shape)
            return cached

    prices = download_with_retry(
        tickers,
        start,
        end,
        downloader=downloader,
        max_retries=int(cfg.get("max_retries", 5)),
        base_delay=float(cfg.get("retry_base_delay_s", 2.0)),
        sleep=sleep,
    )
    empty = [t for t in tickers if prices[t].isna().all()]
    if empty:
        raise DataError(f"No data downloaded for: {empty}")
    prices = prices.dropna(how="all")
    save_cache(prices, settings.cache_dir, start)
    return prices


def coverage_report(prices: pd.DataFrame) -> pd.DataFrame:
    """First/last valid date, number of observations and gaps after listing."""
    rows = []
    for t in prices.columns:
        s = prices[t]
        first, last = s.first_valid_index(), s.last_valid_index()
        live = s.loc[first:last]
        rows.append(
            {
                "ticker": t,
                "first": first.date() if first is not None else None,
                "last": last.date() if last is not None else None,
                "obs": int(live.notna().sum()),
                "gaps_after_listing": int(live.isna().sum()),
            }
        )
    return pd.DataFrame(rows).set_index("ticker")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download or load cached prices.")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and re-download")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    prices = load_prices(refresh=args.refresh)
    report = coverage_report(prices)
    print(f"{prices.shape[0]} trading days x {prices.shape[1]} tickers, "
          f"{prices.index.min().date()} -> {prices.index.max().date()}")
    late = report[report["first"] > prices.index.min().date()]
    print("\nListed after the start date:")
    print(late.to_string() if not late.empty else "  none")
    print(f"\nTickers with gaps after listing: "
          f"{int((report['gaps_after_listing'] > 0).sum())} "
          f"(max {int(report['gaps_after_listing'].max())} days)")
    print(f"Non-positive prices: {int((prices <= 0).sum().sum())}, "
          f"max abs daily log return: {np.nanmax(np.abs(np.log(prices).diff().to_numpy())):.3f}")


if __name__ == "__main__":
    main()
