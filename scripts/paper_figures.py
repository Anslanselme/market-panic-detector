"""Figures for paper/paper.pdf in academic style (white, Computer Modern, thin lines).

Usage: python scripts/paper_figures.py <output folder>   (called by scripts/make_paper.py)
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from panic_detector import eventstudy as es  # noqa: E402
from panic_detector import pipeline, report  # noqa: E402
from panic_detector.config import load_settings, load_universe  # noqa: E402
from panic_detector.data import load_prices  # noqa: E402

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

BLUE, GREY, RED, ORANGE, SHADE = "#2B5BA8", "#9A9A9A", "#C0504D", "#D08A2E", "#E4E4E4"
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["cmr10"], "mathtext.fontset": "cm",
    "axes.formatter.use_mathtext": True, "axes.unicode_minus": False,
    "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "legend.fontsize": 7,
    "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})
W, H = 6.3, 2.5  # A4 text width (16 cm); fonts below are real point sizes
DPI = 300

u, s = load_universe(), load_settings()
prices = load_prices(u, s)
spy = prices["SPY"]
res = {w: pipeline.load_results(w, s) for w in s.windows}
m60 = res[60].metrics
x60 = m60.index
crises = [(pd.Timestamp(c.start), pd.Timestamp(c.end)) for c in s.crises]


def save(fig, name):
    fig.savefig(OUT / name, dpi=DPI, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print("saved", name)


# Figure 1 - mean correlation and lambda1 over time ------------------------------------------
fig, (a1, a2) = plt.subplots(2, 1, figsize=(W, H), sharex=True, gridspec_kw={"hspace": 0.12})
for ax in (a1, a2):
    for start, end in crises:
        ax.axvspan(start, end, color=SHADE, lw=0)
a1.plot(x60, m60["mean_corr"], color=BLUE, lw=0.9, label="mean correlation (60 days)")
a1.plot(res[250].metrics.index, res[250].metrics["mean_corr"], color=GREY, lw=0.9, label="mean correlation (250 days)")
a1.set_ylabel("mean $\\rho$")
a1.legend(loc="upper right", ncol=2, frameon=True, facecolor="white", edgecolor="none", framealpha=0.9)
a1.set_title("Mean pairwise correlation and largest eigenvalue, 50 US large caps", pad=6)
a2.plot(x60, m60["lambda1"], color=BLUE, lw=0.9, label="$\\lambda_1$ (60 days)")
a2.plot(x60, m60["mp_lambda_plus"], color=RED, lw=0.9, ls="--", label="noise ceiling $\\lambda_+$ (Marchenko-Pastur)")
a2.set_ylabel("$\\lambda_1$")
a2.set_ylim(0, 45)
a2.legend(loc="upper right", ncol=2, frameon=True, facecolor="white", edgecolor="none", framealpha=0.9)
save(fig, "fig1_timeseries.png")

# Figure 2 - eigenvalue spectrum vs Marchenko-Pastur, calm vs panic ---------------------------
returns = np.log(prices[u.tickers]).diff()


def spectrum(date, window=60):
    r = returns.loc[:date].iloc[-window:]
    r = r.loc[:, r.notna().sum() >= 57]
    c = r.corr().to_numpy()
    return np.sort(np.linalg.eigvalsh(c))[::-1], c.shape[0], window


fig, axes = plt.subplots(1, 2, figsize=(W, H * 0.92), sharey=True, gridspec_kw={"wspace": 0.06})
for ax, (date, label) in zip(axes, [("2017-08-01", "Calm: 1 August 2017"), ("2020-03-16", "Panic: 16 March 2020")]):
    eig, n, t = spectrum(pd.Timestamp(date))
    q = n / t
    lo, hi = (1 - np.sqrt(q)) ** 2, (1 + np.sqrt(q)) ** 2
    bins = np.logspace(-2, np.log10(50), 40)
    ax.hist(eig, bins=bins, color=GREY, edgecolor="white", lw=0.4, density=False, label="eigenvalues")
    lam = np.linspace(max(lo, 1e-3), hi, 400)
    dens = np.sqrt(np.clip((hi - lam) * (lam - lo), 0, None)) / (2 * np.pi * q * lam)
    widths = np.diff(bins)
    centers = np.sqrt(bins[:-1] * bins[1:])
    expected = np.interp(centers, lam, dens, left=0, right=0) * widths * n
    ax.plot(centers, expected, color=BLUE, lw=1.1, label="pure noise (Marchenko-Pastur)")
    ax.axvline(hi, color=BLUE, lw=0.8, ls=":")
    ax.axvline(eig[0], color=RED, lw=1.4)
    right_side = eig[0] < 20  # room on the right of the line in the calm panel only
    ax.text(eig[0] * (1.08 if right_side else 0.93), 4.6, f"$\\lambda_1 = {eig[0]:.1f}$", color=RED, va="bottom",
            ha="left" if right_side else "right", fontsize=8.3)
    ax.text(hi * 0.93, 5.15, f"$\\lambda_+ = {hi:.2f}$ ", color=BLUE, va="bottom", ha="right", fontsize=7.6)
    ax.set_xscale("log")
    ax.set_xlim(0.01, 60)
    ax.set_title(label)
    ax.set_xlabel("eigenvalue (log scale)")
axes[0].set_ylabel("number of eigenvalues")
axes[0].set_ylim(0, 5.8)
fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.1))
save(fig, "fig2_spectrum.png")

# Figure 3 - minimum spanning trees, same scale ----------------------------------------------
lay = res[60].layout.set_index("date")
edges = res[60].edges
sector = {st.ticker: st.sector for st in u.stocks}
SECT = dict(zip(u.sectors, ["#2B5BA8", "#7E6BB0", "#C0504D", "#4E9A7B", "#D08A2E", "#7FA34A", "#A0602C", "#8C8C8C"]))
SECT_NAMES = {"technology": "Technology", "communication": "Communication", "consumer_discretionary": "Cons. discretionary",
              "consumer_staples": "Cons. staples", "financials": "Financials", "healthcare": "Healthcare",
              "energy_materials": "Energy & materials", "industrials_utilities": "Industrials & utilities"}
dates = [pd.Timestamp("2017-08-01"), pd.Timestamp("2020-03-16")]
tree_labels = []  # (axis, {ticker: (x, y)}, all node positions), labelled once the layout is final


def place_leader_labels(ax, points, nodes, fontsize=6.3, offset_pt=14, gap_pt=3.0):
    """Leader labels pushed outward from the tree's centre, then apart, each tied to its node by a thin line.

    Works in screen units once the axes are final, so the spacing is the same whatever the zoom of the tree.
    """
    fig = ax.figure
    fig.canvas.draw()
    to_px = ax.transData
    names = list(points)
    anchors = to_px.transform(np.array([points[n] for n in names]))
    centre = to_px.transform(np.asarray(nodes)).mean(axis=0)
    pt = fig.dpi / 72
    height = fontsize * pt * 1.3
    widths = np.array([0.75 * fontsize * pt * len(n) + 2 * pt for n in names])  # capitals are wide
    out = anchors - centre
    norm = np.hypot(out[:, 0], out[:, 1])[:, None]
    out = np.where(norm > 1e-9, out / np.maximum(norm, 1e-9), np.array([0.0, 1.0]))
    labels = anchors + out * offset_pt * pt
    gap = gap_pt * pt
    node_px = to_px.transform(np.asarray(nodes))
    node_r = 3.5 * pt
    for _ in range(400):  # push overlapping label boxes apart, and off the bubbles
        moved = False
        for i in range(len(names)):
            for node in node_px:
                dx, dy = labels[i] - node
                over_x = widths[i] / 2 + node_r - abs(dx)
                over_y = height / 2 + node_r - abs(dy)
                if over_x > 0 and over_y > 0:
                    moved = True
                    direction = out[i] if abs(dx) + abs(dy) < 1e-6 else np.array([dx, dy]) / np.hypot(dx, dy)
                    labels[i] += direction * (min(over_x, over_y) + 0.5)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                dx, dy = labels[j] - labels[i]
                over_x = (widths[i] + widths[j]) / 2 + gap - abs(dx)
                over_y = height + gap - abs(dy)
                if over_x > 0 and over_y > 0:
                    moved = True
                    if over_y <= over_x:
                        step = (over_y / 2 + 0.5) * (1.0 if dy >= 0 else -1.0)
                        labels[i, 1] -= step
                        labels[j, 1] += step
                    else:
                        step = (over_x / 2 + 0.5) * (1.0 if dx >= 0 else -1.0)
                        labels[i, 0] -= step
                        labels[j, 0] += step
        if not moved:
            break
    to_data = to_px.inverted()
    for name, anchor, label in zip(names, anchors, labels):
        ax.annotate(name, xy=to_data.transform(anchor), xytext=to_data.transform(label), textcoords="data",
                    fontsize=fontsize, ha="center", va="center", zorder=4, annotation_clip=False,
                    bbox={"boxstyle": "square,pad=0.1", "facecolor": "white", "edgecolor": "none", "alpha": 0.85},
                    arrowprops={"arrowstyle": "-", "color": "#777777", "lw": 0.4, "shrinkA": 1, "shrinkB": 1.5})
lim_x = max(np.abs(lay.loc[d, "x"].to_numpy()).max() for d in dates) * 1.1
lim_y = max(np.abs(lay.loc[d, "y"].to_numpy()).max() for d in dates) * 1.1
fig, axes = plt.subplots(1, 2, figsize=(W, H * 1.35), gridspec_kw={"wspace": 0.04})
for ax, d in zip(axes, dates):
    p = lay.loc[d].set_index("ticker")
    deg = pd.concat([edges.loc[edges.date == d, "source"], edges.loc[edges.date == d, "target"]]).value_counts()
    for _, e in edges[edges.date == d].iterrows():
        a, b = p.loc[e.source], p.loc[e.target]
        ax.plot([a.x, b.x], [a.y, b.y], color="#555555", lw=0.6, zorder=1)
    ax.scatter(p.x, p.y, s=[5 + 3.2 * deg.get(t, 1) for t in p.index], c=[SECT[sector[t]] for t in p.index],
               edgecolors="white", linewidths=0.3, zorder=2)
    tree_labels.append((ax, {t: (p.loc[t, "x"], p.loc[t, "y"]) for t in u.leaders if t in p.index},
                        p[["x", "y"]].to_numpy()))
    mc = m60.loc[d, "mean_corr"]
    ax.set_title(f"{d.day} {d:%B %Y}\nmean $\\rho$ = {mc:.2f}, mean link {m60.loc[d, 'mst_mean_distance']:.2f}")
    ax.set_xlim(-lim_x, lim_x)
    ax.set_ylim(-lim_y, lim_y)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
for ax, points, nodes in tree_labels:
    place_leader_labels(ax, points, nodes)
handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=SECT_NAMES[k]) for k, c in SECT.items()]
fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.06))
save(fig, "fig3_trees.png")

# Figure 4 - regimes on SPY + drawdown ----------------------------------------------------------
fig, (a1, a2) = plt.subplots(2, 1, figsize=(W, H), sharex=True, gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08})
reg = m60["regime"]
colors = {"tension": "#F3D9B1", "panic": "#EBB9B7"}
for name, col in colors.items():
    mask = (reg == name).to_numpy()
    starts = np.flatnonzero(mask & ~np.r_[False, mask[:-1]])
    ends = np.flatnonzero(mask & ~np.r_[mask[1:], False])
    for a, b in zip(starts, ends):
        a1.axvspan(x60[a], x60[b], color=col, lw=0)
spy_m = spy.loc[x60[0]:]
a1.plot(spy_m.index, spy_m, color=BLUE, lw=0.9)
a1.set_yscale("log")
a1.yaxis.set_major_locator(matplotlib.ticker.FixedLocator([50, 100, 200, 400, 800]))
a1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _p: f"{v:.0f}"))
a1.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
a1.set_ylabel("SPY (log, dividends reinvested)")
a1.set_title("SPY and the regime of the 60-day mean correlation (past-only percentile)")
a1.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=colors["tension"], label="TENSION (60th-90th pct)"),
                   plt.Rectangle((0, 0), 1, 1, color=colors["panic"], label="PANIC (above 90th pct)"),
                   plt.Line2D([], [], color=BLUE, label="SPY")], loc="upper left", frameon=False)
dd = (spy_m / spy_m.cummax() - 1) * 100
a2.fill_between(dd.index, dd, 0, color=RED, alpha=0.55, lw=0)
a2.set_ylabel("DD (%)")
save(fig, "fig4_regimes.png")

# Figure 5 - event study (main + two small panels) ---------------------------------------------
cfg = s["event_study"]
events, fresh, analyses = report.analyse(res, spy, s)
a = analyses[60]
fig = plt.figure(figsize=(W, H * 1.05))
gs = fig.add_gridspec(2, 3, width_ratios=[2.2, 1, 0.02], hspace=1.05, wspace=0.3)
ax = fig.add_subplot(gs[:, 0])
fresh_cols = list(a.table.loc[a.table["fresh"], "peak"])
for col in fresh_cols:
    ax.plot(a.profiles.index, a.profiles[col], color=GREY, lw=0.6, alpha=0.8)
ax.plot(a.profiles.index, a.profiles.mean(axis=1), color=GREY, lw=1.1, ls="--", label=f"mean, all {a.profiles.shape[1]} events")
ax.plot(a.profiles.index, a.profiles[fresh_cols].mean(axis=1), color=BLUE, lw=2.0, label=f"mean, {len(fresh_cols)} fresh events")
ax.axvline(0, color=RED, lw=0.9)
ax.text(1, 0.03, "SPY peak", color=RED, transform=ax.get_xaxis_transform(), fontsize=7.2)
ax.set_xlabel("trading days from the SPY peak")
ax.set_ylabel("mean correlation (60 days)")
ax.set_title("Mean correlation around SPY peaks (declines > 10%)")
ax.legend(loc="upper left", frameon=False)
ax2 = fig.add_subplot(gs[0, 1])
ind = m60["mean_corr"].reindex(spy.index)
changes = (ind - ind.shift(60)).dropna()
fresh_t = a.table[a.table["fresh"]].dropna(subset=["pre_peak_change"])
med = fresh_t["pre_peak_change"].median()
ax2.hist(changes, bins=45, color=GREY, edgecolor="white", lw=0.3)
ax2.axvline(med, color=RED, lw=1.4)
pct = (changes <= med).mean() * 100
ordinal = lambda k: f"{k}{'th' if 10 <= k % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th')}"
ax2.set_title(f"Pre-peak 60-day change:\n{ordinal(round(pct))} percentile", fontsize=7.6)
ax2.set_xlabel("60-day change in mean $\\rho$", fontsize=6.8)
ax3 = fig.add_subplot(gs[1, 1])
reached = a.table[a.table["fresh"]].dropna(subset=["panic_vs_cross_days"])
labels = [str(p.year) for p in reached["peak"]]
ax3.bar(labels, reached["panic_vs_cross_days"], color=BLUE, width=0.6)
for i, v in enumerate(reached["panic_vs_cross_days"]):
    ax3.text(i, v + 0.8, f"+{v:.0f}", ha="center", fontsize=6.5)
ax3.set_title(f"Days from $-$10% to first PANIC\n({len(reached)} of {len(fresh_t)} fresh events)", fontsize=7.6)
ax3.set_ylim(0, reached["panic_vs_cross_days"].max() * 1.3)
save(fig, "fig5_eventstudy.png")

# Figure 6 - predictive test ------------------------------------------------------------------
h = int(cfg["forward_horizon"])
spy60 = spy.reindex(m60.index)
xch = es.past_change(m60["mean_corr"], h)
fig, axes = plt.subplots(1, 3, figsize=(W, H * 0.95), gridspec_kw={"width_ratios": [1, 1, 0.8], "wspace": 0.3})
for ax, (y, title, col) in zip(axes[:2], [(es.forward_log_return(spy60, h), "Next 20 days (anticipation)", BLUE),
                                          (es.past_log_return(spy60, h), "Same 20 days (reaction)", RED)]):
    d = es.non_overlapping(pd.concat({"x": xch, "y": y}, axis=1).dropna(), h)
    r = np.corrcoef(d["x"], d["y"])[0, 1]
    ax.scatter(d["x"], 100 * d["y"], s=3, color=col, alpha=0.6, lw=0)
    k, b = np.polyfit(d["x"], 100 * d["y"], 1)
    xs = np.linspace(d["x"].min(), d["x"].max(), 20)
    ax.plot(xs, b + k * xs, color="black", lw=0.9)
    ax.axhline(0, color=GREY, lw=0.5)
    ax.axvline(0, color=GREY, lw=0.5)
    ax.set_title(f"{title}: $r = {r:+.2f}$", fontsize=7.9)
    ax.set_xlabel("20-day change in mean $\\rho$")
axes[0].set_ylabel("SPY log return (%)")
tests = a.tests
labels = ["$\\Delta\\rho$\nfwd", "level\nfwd", "$\\Delta$AR\nfwd", "$\\Delta\\rho$\nsame"]
ax = axes[2]
vals = tests["pearson_r"].to_numpy()
ax.bar(range(4), vals, color=[BLUE, BLUE, BLUE, RED], width=0.6)
for i, (v, pv) in enumerate(zip(vals, tests["pearson_p"])):
    ax.text(i, v + (0.03 if v >= 0 else -0.03), "$p<0.001$" if pv < 0.001 else f"$p={pv:.2f}$",
            ha="center", va="bottom" if v >= 0 else "top", fontsize=6.1)
ax.axhline(0, color="black", lw=0.6)
ax.set_xticks(range(4))
ax.set_xticklabels(labels, fontsize=6.5)
ax.set_ylim(-0.62, 0.25)
ax.set_xlim(-0.75, 3.75)
ax.set_title("Pearson r, non-overlapping", fontsize=7.9)
save(fig, "fig6_predictive.png")
