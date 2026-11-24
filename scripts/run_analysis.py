"""Download (or reuse) data, precompute every window, and write reports/findings.md.

Usage:
    python scripts/run_analysis.py            # reuse caches when fresh
    python scripts/run_analysis.py --refresh  # re-download prices, then recompute
    python scripts/run_analysis.py --force    # recompute results from cached prices
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from panic_detector import pipeline, report
from panic_detector.config import PROJECT_ROOT, load_settings, load_universe
from panic_detector.data import load_prices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="re-download prices from yfinance")
    parser.add_argument("--force", action="store_true", help="recompute results even if the cache is fresh")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    universe, settings = load_universe(), load_settings()
    t0 = time.perf_counter()

    def progress(fraction: float, message: str) -> None:
        print(f"\r  {fraction:6.1%}  {message:<40}", end="", flush=True)

    results = pipeline.run(universe, settings, refresh=args.refresh, force=args.force, progress=progress)
    print(f"\nResults ready in {time.perf_counter() - t0:.0f} s")

    prices = load_prices(universe, settings)
    spy = prices[universe.benchmark]
    events, fresh, analyses = report.analyse(results, spy, settings)

    report_dir = PROJECT_ROOT / "reports"
    img_dir = report_dir / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    cfg = settings["event_study"]
    main_window = min(results)
    figures = {
        "profiles": report.plot_event_profiles(analyses, img_dir, int(cfg["days_before"])),
        "scatter": report.plot_predictive(results[main_window].metrics, spy, int(cfg["forward_horizon"]),
                                          main_window, img_dir),
    }
    findings = report_dir / "findings.md"
    text = report.render(events, fresh, analyses, settings, spy.index.max().date(), figures, report_dir,
                         report.existing_interpretation(findings))
    findings.write_text(text, encoding="utf-8")
    print(f"{len(events)} drawdown events ({len(fresh)} fresh). Report written to {findings}")
    print("\n".join(report._verdict(analyses)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
