"""Build the before and after figure from the measured metrics file."""

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3dd"

COLORS = {
    "full": "#a3a299",
    "lines": "#cfcec4",
    "ptk": "#2a78d6",
    "shift": "#eb6834",
    "align": "#eda100",
    "fast": "#1baf7a",
    "framepatch": "#4a3aa7",
}
LABELS = {
    "full": "full repaint",
    "lines": "changed lines",
    "ptk": "prompt_toolkit cell diff",
    "shift": "global shift detect",
    "align": "row alignment only",
    "fast": "framepatch, fast mode",
    "framepatch": "framepatch",
}
PANEL_SERIES = ("ptk", "shift", "framepatch")
NUDGE = {
    "full": (9, 4, "left"),
    "lines": (9, 4, "left"),
    "ptk": (9, 4, "left"),
    "shift": (9, 4, "left"),
    "align": (9, 5, "left"),
    "fast": (-9, 6, "right"),
    "framepatch": (9, -4, "left"),
}
HALO = [pe.withStroke(linewidth=2.4, foreground=SURFACE)]


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=3)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def build(metrics, path):
    workloads = metrics["workloads"]
    overall = metrics["overall"]
    names = [w["name"] for w in workloads]
    order = [n for n in metrics["order"]]

    fig, axes = plt.subplots(1, 3, figsize=(15.4, 5.3), dpi=120,
                             gridspec_kw={"width_ratios": [1.55, 1.0, 1.0]})
    fig.patch.set_facecolor(SURFACE)

    ax = axes[0]
    _style(ax)
    series = [s for s in PANEL_SERIES if s in order]
    width = 0.26
    for s, key in enumerate(series):
        xs = [i + (s - 1) * width for i in range(len(names))]
        ys = [w["strategies"][key]["mean"] for w in workloads]
        ax.bar(xs, ys, width * 0.92, color=COLORS[key], label=LABELS[key],
               linewidth=0)
        if key == "framepatch":
            for x, y in zip(xs, ys):
                ax.text(x, y + 16, "%d" % round(y), ha="center", va="bottom",
                        fontsize=7.5, color=INK2, path_effects=HALO)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=30, ha="right")
    ax.set_ylim(0, max(w["strategies"]["ptk"]["mean"] for w in workloads) * 1.26)
    ax.set_ylabel("bytes written per frame", color=INK2, fontsize=9)
    ax.set_title("Per workload: bytes sent to the terminal for one frame",
                 color=INK, fontsize=10.5, loc="left", pad=10)
    ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, ncol=3,
              loc="upper left", bbox_to_anchor=(0.0, 1.035), columnspacing=1.2,
              handlelength=1.2)

    ax = axes[1]
    _style(ax)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.grid(False)
    rows = list(reversed(order))
    ys = range(len(rows))
    vals = [overall[n]["mean_bytes"] for n in rows]
    ax.barh(list(ys), vals, 0.6, color=[COLORS[n] for n in rows], linewidth=0)
    for y, v in zip(ys, vals):
        ax.text(v + 14, y, "%d" % round(v), va="center", fontsize=8.5, color=INK2)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([LABELS[n] for n in rows], fontsize=9)
    ax.set_xlim(0, max(vals) * 1.18)
    ax.set_xlabel("mean bytes per frame, 9 workloads", color=INK2, fontsize=9)
    head = metrics["headline"]
    ax.set_title("Overall: %.2fx fewer bytes than the shipped renderer"
                 % head["factor"], color=INK, fontsize=10.5, loc="left", pad=10)

    ax = axes[2]
    _style(ax)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    for n in order:
        x = overall[n]["plan_us"]
        y = overall[n]["mean_bytes"]
        ax.scatter([x], [y], s=70, color=COLORS[n], zorder=3, linewidth=0)
        dx, dy, ha = NUDGE[n]
        ax.annotate(LABELS[n], (x, y), textcoords="offset points",
                    xytext=(dx, dy), fontsize=8, color=INK2, ha=ha,
                    path_effects=HALO)
    ax.set_xscale("log")
    ax.set_xlim(40, 90000)
    ax.set_ylim(0, max(overall[n]["mean_bytes"] for n in order) * 1.15)
    ax.set_xlabel("planning time per frame, microseconds, log scale",
                  color=INK2, fontsize=9)
    ax.set_ylabel("bytes written per frame", color=INK2, fontsize=9)
    ax.set_title("The trade: fewer bytes costs planning time",
                 color=INK, fontsize=10.5, loc="left", pad=10)
    mbit = metrics["cost"]["breakeven_mbit_per_second"]
    fast_mbit = metrics["cost"]["fast_breakeven_mbit_per_second"]
    ax.text(0.03, 0.06,
            "break even link rate: %.2f Mbit/s exact, %.2f Mbit/s fast mode"
            % (mbit, fast_mbit), transform=ax.transAxes, fontsize=8,
            color=INK2)

    fig.suptitle(
        "framepatch: minimum byte terminal screen updates, %d real frame "
        "transitions at %s" % (metrics["meta"]["transitions"],
                               metrics["meta"]["screen"]),
        color=INK, fontsize=12, x=0.012, ha="left", y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.945))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def build_from_file(metrics_path, out_path):
    with open(metrics_path, encoding="utf-8") as handle:
        return build(json.load(handle), out_path)
