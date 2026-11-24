"""Build paper/paper.pdf: the project written up as an A4 research paper.

Every number in the text is computed here from the cached results (run
scripts/run_analysis.py first), filled into paper/template.html, and the page is
printed to PDF with Microsoft Edge or Google Chrome in headless mode.

Usage:
    python scripts/make_paper.py                 # figures + HTML + PDF
    python scripts/make_paper.py --html-only     # skip the PDF
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from string import Template

import numpy as np
import pandas as pd

from panic_detector import pipeline, report
from panic_detector.config import PROJECT_ROOT, load_settings, load_universe
from panic_detector.data import load_prices

PAPER = PROJECT_ROOT / "paper"
AUTHOR = "Anselme Drugeon"
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
]
SECTOR_NAMES = {
    "technology": "Technology", "communication": "Communication services",
    "consumer_discretionary": "Consumer discretionary", "consumer_staples": "Consumer staples",
    "financials": "Financials", "healthcare": "Healthcare", "energy_materials": "Energy and materials",
    "industrials_utilities": "Industrials and utilities",
}
SIGNALS = {"Δ mean_corr": "Δ mean corr.", "mean_corr level": "Corr. level", "Δ absorption_ratio": "Δ absorption"}


def minus(text: str) -> str:
    """Typographic minus: an en dash, the width of LaTeX's minus in this typeface."""
    return text.replace("-", "–")


def pct(x: float, digits: int = 0) -> str:
    return f"{100 * x:.{digits}f}%"


def num(x: float, digits: int = 2) -> str:
    return minus(f"{x:.{digits}f}")


def pval(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def ordinal(k: int) -> str:
    suffix = "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{k}{suffix}"


def day(d) -> str:
    return f"{pd.Timestamp(d).day} {pd.Timestamp(d):%B %Y}"


def layout_median_move(layout: pd.DataFrame) -> float:
    pos = {d: g.set_index("ticker")[["x", "y"]] for d, g in layout.groupby("date")}
    dates = list(pos)
    extent = np.mean([np.ptp(p.to_numpy(), axis=0).max() for p in pos.values()])
    moves = []
    for a, b in zip(dates, dates[1:]):
        common = pos[a].index.intersection(pos[b].index)
        moves.append(np.linalg.norm(pos[b].loc[common].to_numpy() - pos[a].loc[common].to_numpy(), axis=1).mean())
    return float(np.median(moves) / extent)


def build_values() -> dict[str, str]:
    universe, settings = load_universe(), load_settings()
    prices = load_prices(universe, settings)
    spy = prices[universe.benchmark]
    results = {w: pipeline.load_results(w, settings) for w in settings.windows}
    m60, m250 = results[60].metrics, results[250].metrics
    calm, covid = pd.Timestamp("2017-08-01"), pd.Timestamp("2020-03-16")
    events, fresh, analyses = report.analyse(results, spy, settings)
    a60, a250 = analyses[60], analyses[250]

    edges = results[60].edges
    sector = {s.ticker: s.sector for s in universe.stocks}
    same_sector = (edges["source"].map(sector) == edges["target"].map(sector)).mean()
    shares = m60["regime"].value_counts(normalize=True)

    table = a60.table
    fresh_t = table[table["fresh"]]
    cols = list(fresh_t["peak"])
    fresh_path = a60.profiles[cols].mean(axis=1)
    reached = fresh_t.dropna(subset=["panic_vs_cross_days"])["panic_vs_cross_days"]
    sa, sf = a60.sign_all, a60.sign_fresh

    def test(a, kind, signal):
        t = a.tests
        return t[(t["test"] == kind) & (t["signal"] == signal)].iloc[0]

    fwd = test(a60, "forward", "Δ mean_corr")
    lvl250 = test(a250, "forward", "mean_corr level")

    universe_rows = "\n".join(
        f"<tr><td>{SECTOR_NAMES[s]}</td><td class='num'>{len(ts)}</td><td class='wrap'>{', '.join(ts)}</td></tr>"
        for s in universe.sectors
        for ts in [[st.ticker for st in universe.stocks if st.sector == s]]
    )
    regime_name = {"calm": "CALM", "tension": "TENSION", "panic": "PANIC", "warmup": "warm-up"}
    event_rows = "\n".join(
        "<tr>"
        f"<td>{r.peak}</td><td>{r.cross_10pct}</td><td>{r.trough}</td>"
        f"<td class='num'>{minus(f'{100 * r.depth:.1f}')}%</td>"
        f"<td>{'yes' if r.fresh else 'aftershock'}</td>"
        f"<td class='num'>{'–' if pd.isna(r.mean_corr_peak) else num(r.mean_corr_peak)}</td>"
        f"<td>{regime_name.get(r.regime_at_peak, '–') if isinstance(r.regime_at_peak, str) else '–'}</td>"
        f"<td class='num'>{'–' if pd.isna(r.panic_vs_cross_days) else minus(f'{r.panic_vs_cross_days:+.0f}')}</td>"
        "</tr>"
        for r in table.itertuples()
    )
    test_rows = "\n".join(
        "<tr>"
        f"<td>{w} days</td><td>{t.test}</td><td>{SIGNALS[t.signal]}</td>"
        f"<td class='num'>{minus(f'{t.pearson_r:+.3f}')}</td><td class='num'>{pval(t.pearson_p)}</td>"
        f"<td class='num'>{minus(f'{100 * t.nw_slope:+.2f}')}</td><td class='num'>{minus(f'{t.nw_t:+.2f}')}</td>"
        f"<td class='num'>{pval(t.nw_p)}</td>"
        "</tr>"
        for w, a in analyses.items() for t in a.tests.itertuples()
    )

    return {
        "author": AUTHOR,
        "month": f"{pd.Timestamp.today():%B %Y}",
        "start": day(prices.index.min()), "end": day(prices.index.max()), "n_days": f"{len(prices):,}",
        "mean_corr": num(m60["mean_corr"].mean()),
        "min_corr": num(m60["mean_corr"].min()), "min_corr_date": day(m60["mean_corr"].idxmin()),
        "max_corr": num(m60["mean_corr"].max()), "max_corr_date": day(m60["mean_corr"].idxmax()),
        "covid_share": pct(m60.loc[covid, "lambda1_share"]),
        "calm_l1": num(m60.loc[calm, "lambda1"], 1), "covid_l1": num(m60.loc[covid, "lambda1"], 1),
        "calm_ar": pct(m60.loc[calm, "absorption_ratio"]), "covid_ar": pct(m60.loc[covid, "absorption_ratio"]),
        "mp60": num(m60["mp_lambda_plus"].iloc[-1]), "mp250": num(m250["mp_lambda_plus"].iloc[-1]),
        "mst_calm": num(m60.loc[calm, "mst_mean_distance"]), "mst_panic": num(m60.loc[covid, "mst_mean_distance"]),
        "layout_move": pct(layout_median_move(results[60].layout), 1),
        "same_sector": pct(same_sector),
        "share_calm": pct(shares.get("calm", 0)), "share_tension": pct(shares.get("tension", 0)),
        "share_panic": pct(shares.get("panic", 0)),
        "n_events": str(len(events)), "n_fresh": str(len(fresh)),
        "fresh_before": num(fresh_path.loc[-60]), "fresh_peak": num(fresh_path.loc[0]),
        "fresh_after": num(fresh_path.loc[20]),
        "pre_pct": ordinal(round(sf["median"])),
        "n_reached": str(len(reached)),
        "reached_span": f"{reached.min():.0f} to {reached.max():.0f}", "reached_median": f"{reached.median():.0f}",
        "all_above": f"{sa['above']} of {sa['n']}", "sign_all_p": f"{sa['p']:.3f}",
        "fresh_above": f"{sf['above']} of {sf['n']}", "sign_fresh_p": f"{sf['p']:.2f}",
        "fwd_r_text": minus(f"r = {fwd.pearson_r:.2f}, p = {fwd.pearson_p:.2f}"),
        "same60_r": num(test(a60, "same period", "Δ mean_corr").pearson_r),
        "same250_r": num(test(a250, "same period", "Δ mean_corr").pearson_r),
        "lvl250_nw": f"{lvl250.nw_p:.3f}", "lvl250_p": f"{lvl250.pearson_p:.3f}",
        "universe_rows": universe_rows, "event_rows": event_rows, "test_rows": test_rows,
    }


def find_browser() -> str | None:
    for path in BROWSERS:
        if Path(path).exists():
            return path
    return shutil.which("msedge") or shutil.which("google-chrome") or shutil.which("chromium")


def print_pdf(html: Path, pdf: Path) -> None:
    browser = find_browser()
    if browser is None:
        raise SystemExit("No Edge or Chrome found: open paper/paper.html and print it to PDF (A4).")
    with tempfile.TemporaryDirectory() as profile:  # a throwaway profile: never touches yours
        subprocess.run([
            browser, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
            "--no-pdf-header-footer", "--virtual-time-budget=20000", f"--print-to-pdf={pdf}", html.as_uri(),
        ], check=True, timeout=180, capture_output=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--html-only", action="store_true")
    args = parser.parse_args(argv)

    figures = PAPER / "figures"
    subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "paper_figures.py"), str(figures)], check=True)
    shutil.copyfile(PROJECT_ROOT / "docs" / "img" / "dashboard_card_en.jpg", figures / "dashboard_card.jpg")

    template = Template((PAPER / "template.html").read_text(encoding="utf-8"))
    html = PAPER / "paper.html"
    html.write_text(template.substitute(build_values()), encoding="utf-8")
    print("wrote", html)
    if not args.html_only:
        pdf = PAPER / "paper.pdf"
        print_pdf(html, pdf)
        print("wrote", pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
