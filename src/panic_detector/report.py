"""Build reports/findings.md and its figures from the cached results.

A hand-written interpretation block between the markers below is preserved when
the report is regenerated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from panic_detector import eventstudy as es  # noqa: E402
from panic_detector.config import Settings  # noqa: E402
from panic_detector.pipeline import WindowResults  # noqa: E402

INTERP_START = "<!-- interpretation:start -->"
INTERP_END = "<!-- interpretation:end -->"
DEFAULT_INTERPRETATION = "_To be written after reading the numbers above._"

# Same "sodium night" palette as the dashboard (see ui/theme.py; duplicated here so the
# report can be built without importing Qt).
BG, PANEL, TEXT, MUTED, GRID = "#0B0A0D", "#16130F", "#EFE6D4", "#8E8474", "#2B241B"
SODIUM, TAILLIGHT, NIGHT_BLUE = "#FFAA3C", "#E8553B", "#5E7FA8"
NEON = ["#A6D35B", "#C7AEE6", "#F2A24B", "#E86A4E", "#F6D879", "#7FB0D8", "#E9E0CF", "#C9773A", "#8C7AB8", "#6FA58C"]


@dataclass
class WindowAnalysis:
    window: int
    table: pd.DataFrame          # per event
    profiles: pd.DataFrame       # offset x event
    tests: pd.DataFrame          # predictive + same-period
    precision: dict[str, float]
    sign_all: dict[str, float]
    sign_fresh: dict[str, float]


def analyse(results: dict[int, WindowResults], spy: pd.Series, settings: Settings):
    cfg = settings["event_study"]
    before, after, horizon = int(cfg["days_before"]), int(cfg["days_after"]), int(cfg["forward_horizon"])
    calendar = spy.dropna().index
    events = es.find_drawdowns(spy, float(cfg["drawdown_threshold"]))
    fresh = es.fresh_events(events, calendar, before)
    fresh_peaks = {e.peak.date() for e in fresh}
    out = {}
    for w, r in results.items():
        table = es.event_table(r.metrics, calendar, events, before, after)
        table.insert(1, "fresh", table["peak"].isin(fresh_peaks))
        out[w] = WindowAnalysis(
            window=w,
            table=table,
            profiles=es.event_profiles(r.metrics["mean_corr"], calendar, events, before, after),
            tests=es.predictive_tests(r.metrics, spy, horizon),
            precision=es.panic_precision(r.metrics, spy, float(cfg["drawdown_threshold"])),
            sign_all=es.sign_test(table["pre_peak_change_pctile"]),
            sign_fresh=es.sign_test(table.loc[table["fresh"], "pre_peak_change_pctile"]),
        )
    return events, fresh, out


# ----------------------------------------------------------------------------- figures


def _style(ax) -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(color=GRID, lw=0.5)
    ax.title.set_color(TEXT)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)


def _glow(ax, x, y, color, lw=2.0, **kw) -> None:
    for width, alpha in ((lw * 5, 0.06), (lw * 3, 0.12), (lw * 2, 0.25)):
        ax.plot(x, y, color=color, lw=width, alpha=alpha, solid_capstyle="round")
    ax.plot(x, y, color=color, lw=lw, **kw)


def plot_event_profiles(analyses: dict[int, WindowAnalysis], img_dir: Path, before: int) -> Path:
    fig, axes = plt.subplots(1, len(analyses), figsize=(6.2 * len(analyses), 4.4), facecolor=BG, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (w, a) in zip(axes, analyses.items()):
        _style(ax)
        fresh_cols = list(a.table.loc[a.table["fresh"], "peak"])
        for k, col in enumerate(fresh_cols):
            ax.plot(a.profiles.index, a.profiles[col], color=NEON[k % len(NEON)], lw=0.9, alpha=0.55,
                    label=str(col))
        ax.plot(a.profiles.index, a.profiles.mean(axis=1), color=MUTED, lw=1.3, ls="--",
                label=f"mean, all {a.profiles.shape[1]} events")
        _glow(ax, a.profiles.index, a.profiles[fresh_cols].mean(axis=1), TEXT, lw=2.2)
        ax.plot([], [], color=TEXT, lw=2.2, label=f"mean, {len(fresh_cols)} fresh events")
        ax.axvline(0, color=TAILLIGHT, lw=1, alpha=0.8)
        ax.text(1, 0.02, "SPY peak", color=TAILLIGHT, fontsize=8, transform=ax.get_xaxis_transform())
        ax.set_title(f"Mean correlation around SPY peaks, {w}-day window", fontsize=10, family="monospace")
        ax.set_xlabel("trading days from the peak")
        ax.set_xlim(-before, a.profiles.index.max())
    axes[0].set_ylabel("mean pairwise correlation")
    leg = axes[-1].legend(fontsize=6.5, ncol=2, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, loc="upper left")
    leg.get_frame().set_alpha(0.9)
    fig.tight_layout()
    path = img_dir / "event_profiles.png"
    fig.savefig(path, dpi=130, facecolor=BG)
    plt.close(fig)
    return path


def plot_predictive(metrics: pd.DataFrame, spy: pd.Series, horizon: int, window: int, img_dir: Path) -> Path:
    spy = spy.reindex(metrics.index)
    x = es.past_change(metrics["mean_corr"], horizon)
    panels = [
        ("forward", es.forward_log_return(spy, horizon), f"SPY return over the NEXT {horizon} days"),
        ("same period", es.past_log_return(spy, horizon), f"SPY return over the SAME {horizon} days"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), facecolor=BG, sharex=True)
    for ax, (name, y, ylabel), color in zip(axes, panels, (NIGHT_BLUE, SODIUM)):
        _style(ax)
        d = es.non_overlapping(pd.concat({"x": x, "y": y}, axis=1).dropna(), horizon)
        r = np.corrcoef(d["x"], d["y"])[0, 1]
        ax.scatter(d["x"], 100 * d["y"], s=10, color=color, alpha=0.6, edgecolor="none")
        slope, icpt = np.polyfit(d["x"], 100 * d["y"], 1)
        xs = np.linspace(d["x"].min(), d["x"].max(), 50)
        _glow(ax, xs, icpt + slope * xs, TEXT, lw=1.6)
        ax.axhline(0, color=MUTED, lw=0.6)
        ax.axvline(0, color=MUTED, lw=0.6)
        ax.set_title(f"{name}: r = {r:+.2f}  (n = {len(d)}, non-overlapping)", fontsize=10, family="monospace")
        ax.set_xlabel(f"{horizon}-day change in mean correlation ({window}-day window)")
        ax.set_ylabel(ylabel + " (%)")
    fig.tight_layout()
    path = img_dir / "predictive_scatter.png"
    fig.savefig(path, dpi=130, facecolor=BG)
    plt.close(fig)
    return path


# ----------------------------------------------------------------------------- markdown


def md_table(df: pd.DataFrame, formats: dict | None = None) -> str:
    """Markdown table; `formats` maps a column to a format string or a callable."""
    formats = formats or {}

    def cell(col: str, v) -> str:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "–"
        fmt = formats.get(col)
        if callable(fmt):
            return fmt(v)
        if fmt:
            return fmt.format(v)
        return str(v)

    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    rows = ["| " + " | ".join(cell(c, v) for c, v in zip(df.columns, row)) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


def _p(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def _verdict(analyses: dict[int, WindowAnalysis]) -> list[str]:
    lines = []
    for w, a in analyses.items():
        fwd = a.tests[a.tests["test"] == "forward"]
        both = fwd[(fwd["pearson_p"] < 0.05) & (fwd["nw_p"] < 0.05)]
        either = fwd[(fwd["pearson_p"] < 0.05) | (fwd["nw_p"] < 0.05)]
        same = a.tests[a.tests["test"] == "same period"].iloc[0]
        if both.empty and either.empty:
            pred = "no forward test is significant at 5 %"
        elif both.empty:
            names = ", ".join(f"{s} (Newey-West p = {_p(p)}, non-overlapping p = {_p(q)})"
                              for s, p, q in zip(either["signal"], either["nw_p"], either["pearson_p"]))
            pred = f"only one of the two methods is significant at 5 % for {names}"
        else:
            names = ", ".join(f"{s} (r = {r:+.2f})" for s, r in zip(both["signal"], both["pearson_r"]))
            pred = f"both methods are significant at 5 % for {names}"
        lines.append(
            f"- **{w}-day window** — anticipation: {pred}. Reaction: the same-period correlation between "
            f"the change in mean correlation and SPY's return is r = {same['pearson_r']:+.2f} "
            f"(p {_p(same['pearson_p'])})."
        )
    return lines


def render(
    events: list[es.DrawdownEvent],
    fresh: list[es.DrawdownEvent],
    analyses: dict[int, WindowAnalysis],
    settings: Settings,
    last_date: date,
    figures: dict[str, Path],
    report_dir: Path,
    interpretation: str = DEFAULT_INTERPRETATION,
) -> str:
    cfg = settings["event_study"]
    before, after, horizon = cfg["days_before"], cfg["days_after"], cfg["forward_horizon"]
    thr = int(round(100 * cfg["drawdown_threshold"]))
    rel = {k: p.relative_to(report_dir).as_posix() for k, p in figures.items()}
    fresh_set = {e.peak for e in fresh}

    ev = pd.DataFrame(
        {
            "peak": [e.peak.date() for e in events],
            "−10 % crossed": [e.cross.date() for e in events],
            "trough": [e.trough.date() for e in events],
            "depth": [e.depth for e in events],
            "fresh": ["yes" if e.peak in fresh_set else "aftershock" for e in events],
        }
    )
    out = [
        "# Findings: does the correlation indicator anticipate crises?",
        "",
        f"_Generated by `scripts/run_analysis.py` on {date.today()}; data through {last_date}._",
        "",
        "## Verdict",
        "",
        *_verdict(analyses),
        "",
        "## Interpretation",
        "",
        INTERP_START,
        interpretation.strip(),
        INTERP_END,
        "",
        "## Method",
        "",
        f"- **Events**: every SPY decline of more than {thr} % (adjusted closes), found with a zig-zag rule: "
        f"a peak is confirmed by a {thr} % fall, the trough by a {thr} % rebound. A new all-time high is not "
        "required, so 2010 and 2011 count as separate events.",
        f"- **Fresh events**: events whose pre-peak window ({before} trading days) starts after the previous "
        "event ended. Aftershocks start from an indicator that is already high, which would bias the "
        "'did it rise before the peak?' question.",
        "- **Peak dates are only known in hindsight.** The date the decline first crossed "
        f"−{thr} % is the first moment an observer could know an event was under way.",
        f"- **Pre-peak change percentile**: the change in mean correlation over the {before} days before the "
        f"peak, ranked against all {before}-day changes in the sample (50 = ordinary, > 90 = unusually large rise).",
        f"- **Predictive test**: SPY's forward {horizon}-day log return regressed on three signals known at t: "
        f"the {horizon}-day change in mean correlation, its level, and the {horizon}-day change in the absorption ratio. "
        f"(a) Pearson and Spearman correlations on non-overlapping {horizon}-day samples, with the range of r "
        f"over the {horizon} possible starting days; (b) OLS on all days with Newey-West (HAC, {horizon} lags) "
        "standard errors; the slope is the forward return per one standard deviation of the signal.",
        "- **Same-period test**: identical, but against SPY's return over the same past "
        f"{horizon} days: this measures reaction, not anticipation.",
        "",
        "## 1. SPY drawdown events",
        "",
        md_table(ev, {"depth": "{:.1%}"}),
        "",
        "## 2. Event study",
        "",
        f"![Mean correlation around SPY peaks]({rel['profiles']})",
        "",
    ]
    for w, a in analyses.items():
        t = a.table
        cols = {
            "peak": "peak",
            "fresh": "fresh",
            f"mean_corr_t-{before}": f"corr t−{before}",
            "mean_corr_peak": "corr at peak",
            f"mean_corr_t+{after}": f"corr t+{after}",
            "mean_corr_trough": "corr at trough",
            "pre_peak_change_pctile": "pre-peak change pctile",
            "regime_at_peak": "regime at peak",
            "days_peak_to_cross": f"days to −{thr} %",
            "days_peak_to_panic": "days to 1st PANIC",
            "panic_vs_cross_days": f"PANIC vs −{thr} % (days)",
        }
        view = t[list(cols)].rename(columns=cols).copy()
        view["fresh"] = view["fresh"].map({True: "yes", False: "–"})
        fmt = {c: "{:.2f}" for c in cols.values() if c.startswith("corr")}
        fmt.update({"pre-peak change pctile": "{:.0f}", f"days to −{thr} %": "{:.0f}",
                    "days to 1st PANIC": "{:.0f}", f"PANIC vs −{thr} % (days)": "{:+.0f}"})
        fresh_t = t[t["fresh"]]
        counts = fresh_t["regime_at_peak"].fillna("no data").value_counts()
        regimes_at_peak = ", ".join(
            f"{name.upper()} {int(counts.get(name, 0))}"
            for name in ("panic", "tension", "calm", "warmup", "no data")
            if name in ("panic", "tension", "calm") or counts.get(name, 0)
        )
        reached = fresh_t.dropna(subset=["panic_vs_cross_days"])
        lo, hi = (reached["panic_vs_cross_days"].min(), reached["panic_vs_cross_days"].max()) if len(reached) else (0, 0)
        span = f"{lo:+.0f}" if lo == hi else f"{lo:+.0f} to {hi:+.0f}"
        sa, sf = a.sign_all, a.sign_fresh
        out += [
            f"### {w}-day window",
            "",
            md_table(view, fmt),
            "",
            f"- Pre-peak rise larger than the median {before}-day change: {sa['above']} of {sa['n']} events "
            f"(sign test p = {_p(sa['p'])}); fresh events only: {sf['above']} of {sf['n']} (p = {_p(sf['p'])}, "
            f"median percentile {sf['median']:.0f}).",
            f"- Regime at the peak of the {len(fresh_t)} fresh events: {regimes_at_peak}.",
            f"- Fresh events that reached PANIC: {len(reached)} of {len(fresh_t)}"
            + (
                f"; it came {span} trading days after the −{thr} % line was crossed"
                + (f" (median {reached['panic_vs_cross_days'].median():+.0f})." if len(reached) > 1 else ".")
                if len(reached) else "."
            ),
            f"- Precision of PANIC days: {a.precision['panic_days']} PANIC days, of which "
            f"{a.precision['share_in_drawdown']:.0%} occurred while SPY was already more than {thr} % below its "
            f"running high ({a.precision['share_in_5pct_drawdown']:.0%} more than 5 % below).",
            "",
        ]

    out += [
        "## 3. Predictive test",
        "",
        f"![Change in correlation vs SPY return]({rel['scatter']})",
        "",
    ]
    for w, a in analyses.items():
        tt = a.tests.copy()
        tt["r range (offsets)"] = [f"{lo:+.2f} … {hi:+.2f}" for lo, hi in zip(tt["r_min_offsets"], tt["r_max_offsets"])]
        tt["NW slope (%/sd)"] = 100 * tt["nw_slope"]
        view = tt[["test", "signal", "n_nonoverlap", "pearson_r", "pearson_p", "spearman_rho", "spearman_p",
                   "r range (offsets)", "n_daily", "NW slope (%/sd)", "nw_t", "nw_p", "r2"]].rename(
            columns={"n_nonoverlap": "n (non-overlap)", "pearson_r": "Pearson r", "pearson_p": "p",
                     "spearman_rho": "Spearman ρ", "spearman_p": "p (ρ)", "n_daily": "n (daily)",
                     "nw_t": "NW t", "nw_p": "NW p", "r2": "R²"})
        out += [
            f"### {w}-day window",
            "",
            md_table(view, {"Pearson r": "{:+.3f}", "p": _p, "Spearman ρ": "{:+.3f}", "p (ρ)": _p,
                            "NW slope (%/sd)": "{:+.2f}", "NW t": "{:+.2f}", "NW p": _p, "R²": "{:.3f}"}),
            "",
        ]
    n_tests = sum(int((a.tests["test"] == "forward").sum()) for a in analyses.values())
    out += [
        f"{n_tests} forward tests are run in total (3 signals × {len(analyses)} windows): at the 5 % level, "
        f"{0.05 * n_tests:.1f} false positives are expected by chance alone.",
        "",
        "## Caveats",
        "",
        "- **Survivorship bias**: the 50 stocks are today's large caps, chosen with hindsight.",
        f"- **Few events**: {len(events)} drawdowns ({len(fresh)} fresh), several of them parts of the same crisis.",
        "- **Peaks are chosen with hindsight**; only the −10 % crossing date is observable in real time.",
        "- **Overlapping windows**: rolling 60/250-day statistics are highly autocorrelated; Newey-West and "
        "non-overlapping samples address this only partially.",
        "- **The regime percentile is expanding**: crises are judged against everything seen before, so later, "
        "milder crises (2018, 2022) rarely reach PANIC.",
        "- This is a description of market structure, **not a buy or sell signal**.",
        "",
    ]
    return "\n".join(out)


def existing_interpretation(path: Path) -> str:
    if not path.exists():
        return DEFAULT_INTERPRETATION
    text = path.read_text(encoding="utf-8")
    if INTERP_START in text and INTERP_END in text:
        return text.split(INTERP_START, 1)[1].split(INTERP_END, 1)[0].strip() or DEFAULT_INTERPRETATION
    return DEFAULT_INTERPRETATION
