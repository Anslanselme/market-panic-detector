"""Precompute every metric, tree and layout once and cache them; the UI only reads the cache."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from panic_detector.config import CONFIG_DIR, Settings, Universe, load_settings, load_universe
from panic_detector.data import MANIFEST_FILE, load_prices
from panic_detector.metrics import correlation_metrics, log_returns, rolling_correlations
from panic_detector.network import StableLayout, minimum_spanning_tree
from panic_detector.regime import classify

log = logging.getLogger(__name__)

PIPELINE_VERSION = 2  # 2: layouts in both 2-D (x, y) and 3-D (x3, y3, z3)
LAYOUT_COLUMNS = ["date", "ticker", "x", "y", "x3", "y3", "z3"]
RESULTS_MANIFEST = "results_manifest.json"
Progress = Callable[[float, str], None]


@dataclass
class WindowResults:
    window: int
    metrics: pd.DataFrame  # index: date; metric columns + percentile + regime
    edges: pd.DataFrame    # date, source, target, rho, distance
    layout: pd.DataFrame   # date, ticker, x, y (2-D), x3, y3, z3 (3-D)


def _files(cache_dir: Path, window: int) -> dict[str, Path]:
    return {name: cache_dir / f"{name}_w{window}.parquet" for name in ("metrics", "edges", "layout")}


def cache_key(settings: Settings) -> str:
    """Changes whenever the universe, the relevant settings, the prices or the code version change."""
    h = hashlib.sha256()
    h.update(str(PIPELINE_VERSION).encode())
    h.update((CONFIG_DIR / "universe.yaml").read_bytes())
    h.update(json.dumps({k: settings[k] for k in ("metrics", "network", "regime")}, sort_keys=True).encode())
    prices_manifest = settings.cache_dir / MANIFEST_FILE
    if prices_manifest.exists():
        h.update(prices_manifest.read_bytes())
    return h.hexdigest()[:16]


def compute_window(
    returns: pd.DataFrame,
    window: int,
    settings: Settings,
    progress: Progress | None = None,
) -> WindowResults:
    mcfg, rcfg = settings["metrics"], settings["regime"]
    stiffness = float(settings["network"]["layout_stiffness"])
    layout2d = StableLayout(stiffness=stiffness, dim=2)
    layout3d = StableLayout(stiffness=stiffness, dim=3)
    metric_rows, dates, edge_rows, layout_rows = [], [], [], []
    total = max(1, len(returns) - window + 1)

    for k, wc in enumerate(rolling_correlations(returns, window, float(mcfg["min_coverage"]))):
        row = correlation_metrics(wc.corr, wc.n_obs, float(mcfg["absorption_fraction"]))
        tree = minimum_spanning_tree(wc.corr, wc.tickers)
        row["mst_mean_distance"] = float(np.mean([d["weight"] for *_, d in tree.edges(data=True)]))
        metric_rows.append(row)
        dates.append(wc.date)
        for u, v, d in tree.edges(data=True):
            edge_rows.append((wc.date, u, v, d["rho"], d["weight"]))
        pos2 = layout2d.step(tree, wc.tickers)
        pos3 = layout3d.step(tree, wc.tickers)
        layout_rows.extend((wc.date, t, *p2, *p3) for t, p2, p3 in zip(wc.tickers, pos2, pos3))
        if progress and k % 100 == 0:
            progress(k / total, f"window {window}: {wc.date.date()}")

    metrics = pd.DataFrame(metric_rows, index=pd.DatetimeIndex(dates, name="date"))
    metrics["n_stocks"] = metrics["n_stocks"].astype(int)
    regime = classify(
        metrics["mean_corr"],
        float(rcfg["tension_percentile"]),
        float(rcfg["panic_percentile"]),
        int(rcfg["min_history"]),
    )
    metrics = metrics.join(regime)
    edges = pd.DataFrame(edge_rows, columns=["date", "source", "target", "rho", "distance"])
    layout_df = pd.DataFrame(layout_rows, columns=LAYOUT_COLUMNS)
    return WindowResults(window, metrics, edges, layout_df)


def save_results(results: WindowResults, cache_dir: Path) -> None:
    files = _files(cache_dir, results.window)
    results.metrics.to_parquet(files["metrics"])
    results.edges.to_parquet(files["edges"], index=False)
    results.layout.to_parquet(files["layout"], index=False)


def load_results(window: int, settings: Settings | None = None) -> WindowResults:
    settings = settings or load_settings()
    files = _files(settings.cache_dir, window)
    return WindowResults(
        window,
        pd.read_parquet(files["metrics"]),
        pd.read_parquet(files["edges"]),
        pd.read_parquet(files["layout"]),
    )


def cache_is_fresh(settings: Settings) -> bool:
    manifest = settings.cache_dir / RESULTS_MANIFEST
    if not manifest.exists():
        return False
    stored = json.loads(manifest.read_text(encoding="utf-8"))
    files_ok = all(p.exists() for w in settings.windows for p in _files(settings.cache_dir, w).values())
    return files_ok and stored.get("key") == cache_key(settings) and stored.get("windows") == settings.windows


def run(
    universe: Universe | None = None,
    settings: Settings | None = None,
    *,
    refresh: bool = False,
    force: bool = False,
    progress: Progress | None = None,
) -> dict[int, WindowResults]:
    """Load prices (cached), then compute or reload the results of every window."""
    universe = universe or load_universe()
    settings = settings or load_settings()
    prices = load_prices(universe, settings, refresh=refresh)

    if not (force or refresh) and cache_is_fresh(settings):
        log.info("Results cache is fresh, loading it")
        return {w: load_results(w, settings) for w in settings.windows}

    returns = log_returns(prices[universe.tickers])
    results = {}
    for w in settings.windows:
        results[w] = compute_window(returns, w, settings, progress)
        save_results(results[w], settings.cache_dir)
    manifest = {"key": cache_key(settings), "windows": settings.windows}
    (settings.cache_dir / RESULTS_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    if progress:
        progress(1.0, "done")
    return results
