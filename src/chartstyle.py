"""chartstyle.py - how Atom's charts look (dark, Power BI-style, in the jester's colours).

No data code here: analysis.py decides WHAT to draw, this file decides how it LOOKS.
Change CHART_THEME in config.py ("dark" or "light"). To restyle everything, edit THEMES below.

  theme(name)                      - the colours of a look
  compact(value)                   - 1234567 -> "1.2M"
  setup(fig, th)                   - background and fonts for a figure
  style_axes(ax, th)               - a chart panel: soft grid, no frame
  bars / lines / donut / histogram / scatter  - the five kinds of drawing
  heading(ax, th, title, subtitle) - title (and a quieter line below it)
  footer(fig, th)                  - the small ATOM tag in the corner
"""

from __future__ import annotations

import numpy as np

THEMES = {
    "dark": {
        "bg": "#12060b",          # page (the jester's near-black)
        "panel": "#1c1216",       # behind each chart
        "text": "#fff4ec",
        "muted": "#b79ba1",
        "grid": "#3a2a30",
        "edge": "#2b1d22",
        "palette": ["#ff4b6e", "#e4cc54", "#3bb3c3", "#9b6bdc", "#43b581", "#f2a33a", "#5b8cff", "#ff8fa6"],
        "bar_from": "#b3122f",    # bars fade from this (bottom) ...
        "bar_to": "#ff5f7e",      # ... to this (top)
        "highlight": "#e4cc54",   # the biggest bar, the average line, the trend line
        "highlight_to": "#f6e27a",
    },
    "light": {
        "bg": "#f4f1ee",
        "panel": "#ffffff",
        "text": "#1f1b1d",
        "muted": "#6e6469",
        "grid": "#e6dfdc",
        "edge": "#e0d8d5",
        "palette": ["#c9143a", "#e0b400", "#0e9aa7", "#7a4fc4", "#2e9a68", "#e8861a", "#3b6fe0", "#d46a85"],
        "bar_from": "#c9143a",
        "bar_to": "#ef5a78",
        "highlight": "#e0b400",
        "highlight_to": "#f5d54a",
    },
}
FONTS = ["Segoe UI", "Calibri", "Arial", "DejaVu Sans"]


def theme(name: str | None = None) -> dict:
    return THEMES.get((name or "dark").lower(), THEMES["dark"])


def compact(value: float) -> str:
    """1234 -> 1,234   12345 -> 12.3K   1234567 -> 1.2M"""
    v = float(value)
    a = abs(v)
    for limit, divisor, suffix in ((1e12, 1e12, "T"), (1e9, 1e9, "B"), (1e6, 1e6, "M"), (1e4, 1e3, "K")):
        if a >= limit:
            text = f"{v / divisor:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    if a >= 100 or v == int(v):
        return f"{v:,.0f}"
    return f"{v:,.2f}" if a < 10 else f"{v:,.1f}"


def axis_formatter():
    from matplotlib.ticker import FuncFormatter
    return FuncFormatter(lambda v, _p=None: compact(v))


def font_settings() -> dict:
    return {"font.family": "sans-serif", "font.sans-serif": FONTS}


def setup(fig, th: dict) -> None:
    fig.set_facecolor(th["bg"])


def style_axes(ax, th: dict, grid: str = "y") -> None:
    ax.set_facecolor(th["panel"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(th["grid"])
    ax.tick_params(colors=th["muted"], labelsize=8.5, length=0, pad=6)
    ax.xaxis.label.set_color(th["muted"])
    ax.yaxis.label.set_color(th["muted"])
    ax.xaxis.label.set_size(9)
    ax.yaxis.label.set_size(9)
    ax.set_axisbelow(True)
    if grid:
        ax.grid(axis=grid, color=th["grid"], linewidth=0.8, linestyle=(0, (4, 4)))


def heading(ax, th: dict, title: str, subtitle: str = "", size: float = 13.5) -> None:
    """The title sits in the top-left corner above the chart, with a quieter line below it."""
    lift = 26 if subtitle else 12
    ax.annotate(title, (0, 1), xycoords="axes fraction", xytext=(0, lift), textcoords="offset points", ha="left",
                va="bottom", fontsize=size, fontweight="bold", color=th["text"], annotation_clip=False)
    if subtitle:
        ax.annotate(subtitle, (0, 1), xycoords="axes fraction", xytext=(0, 10), textcoords="offset points", ha="left",
                    va="bottom", fontsize=8.5, color=th["muted"], annotation_clip=False)


def footer(fig, th: dict) -> None:
    fig.text(0.992, 0.012, "A T O M", ha="right", va="bottom", fontsize=7, color=th["muted"], alpha=0.7)


# ================================================================== drawings
def _gradient_bar(ax, x0, x1, y0, y1, c_from, c_to, z=3):
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Rectangle

    lo, hi = min(y0, y1), max(y0, y1)
    if hi - lo <= 0:
        return
    cmap = LinearSegmentedColormap.from_list("bar", [c_from, c_to])
    image = ax.imshow(np.linspace(0, 1, 48).reshape(-1, 1), extent=(x0, x1, lo, hi), origin="lower",
                      aspect="auto", cmap=cmap, zorder=z, interpolation="bilinear")
    clip = Rectangle((x0, lo), x1 - x0, hi - lo, transform=ax.transData)
    image.set_clip_path(clip)


def bars(ax, th: dict, labels: list, columns: dict, label_values: bool = True, legend_title: str = "") -> None:
    """columns = {series name: [values]}. One series: the biggest bar is gold. Several: one colour each."""
    n, k = len(labels), len(columns)
    width = 0.62 if k == 1 else 0.8
    slot = width / k
    top, bottom = 0.0, 0.0
    for s, (name, values) in enumerate(columns.items()):
        vals = np.nan_to_num(np.asarray(values, dtype=float))
        top, bottom = max(top, vals.max(initial=0)), min(bottom, vals.min(initial=0))
        for i, v in enumerate(vals):
            x0 = i - width / 2 + s * slot + (0.04 if k > 1 else 0)
            x1 = x0 + slot - (0.08 if k > 1 else 0)
            if k == 1:
                best = i == int(np.argmax(vals)) and n > 2
                c_from, c_to = (th["highlight"], th["highlight_to"]) if best else (th["bar_from"], th["bar_to"])
            else:
                c_from = th["palette"][s % len(th["palette"])]
                c_to = c_from
            _gradient_bar(ax, x0, x1, 0, v, c_from, c_to)
            if label_values and k == 1 and v != 0:
                ax.annotate(compact(v), ((x0 + x1) / 2, v), xytext=(0, 4 if v > 0 else -12), textcoords="offset points",
                            ha="center", fontsize=8.5, fontweight="bold", color=th["text"], zorder=5)
    span = (top - bottom) or 1.0
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_ylim(bottom - (span * 0.08 if bottom < 0 else 0), top + span * 0.14)
    ax.set_xticks(range(n))
    ax.set_xticklabels([str(x) for x in labels])
    ax.yaxis.set_major_formatter(axis_formatter())
    if k > 1:
        legend(ax, th, list(columns), legend_title)


def legend(ax, th: dict, names: list, title: str = "") -> None:
    from matplotlib.patches import Patch

    handles = [Patch(facecolor=th["palette"][i % len(th["palette"])], edgecolor="none") for i in range(len(names))]
    ax.legend(handles, [str(n) for n in names], frameon=False, fontsize=8.5, loc="lower right",
              bbox_to_anchor=(1.0, 1.0), ncol=min(len(names), 6), handlelength=1.0, columnspacing=1.2,
              labelcolor=th["text"], borderaxespad=0.2)


def lines(ax, th: dict, labels: list, columns: dict, label_last: bool = True, legend_title: str = "") -> None:
    n = len(labels)
    xs = np.arange(n)
    single = len(columns) == 1
    for s, (name, values) in enumerate(columns.items()):
        vals = np.asarray(values, dtype=float)
        color = th["palette"][s % len(th["palette"])]
        ok = ~np.isnan(vals)
        ax.plot(xs[ok], vals[ok], color=color, linewidth=2.6, solid_capstyle="round", zorder=4)
        if n <= 40:
            ax.scatter(xs[ok], vals[ok], s=34, color=color, edgecolor=th["panel"], linewidth=1.6, zorder=5)
        if single:
            ax.fill_between(xs[ok], vals[ok], 0, color=color, alpha=0.14, zorder=2, linewidth=0)
        if label_last and ok.any():
            j = int(np.flatnonzero(ok)[-1])
            ax.annotate(compact(vals[j]), (xs[j], vals[j]), xytext=(8, 0), textcoords="offset points", ha="left",
                        va="center", fontsize=8.5, fontweight="bold", color=th["text"], zorder=6, annotation_clip=False)
    ax.set_xlim(-0.4, n - 0.6 + (max(0.6, n * 0.05) if single and label_last else 0))
    allv = np.concatenate([np.asarray(v, dtype=float) for v in columns.values()])
    allv = allv[~np.isnan(allv)]
    if allv.size:
        lo, hi = min(0.0, allv.min()), allv.max()
        ax.set_ylim(lo - (hi - lo) * 0.04 if lo < 0 else 0, hi + (hi - lo or 1) * 0.16)
    step = max(1, int(np.ceil(n / 12)))
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([str(x) for x in labels][::step])
    ax.yaxis.set_major_formatter(axis_formatter())
    if not single:
        legend(ax, th, list(columns), legend_title)


def donut(ax, th: dict, labels: list, values: list, total_label: str = "") -> None:
    vals = np.clip(np.asarray(values, dtype=float), 0, None)
    colors = [th["palette"][i % len(th["palette"])] for i in range(len(vals))]
    ax.pie(vals, startangle=90, counterclock=False, colors=colors,
           wedgeprops={"width": 0.36, "edgecolor": th["panel"], "linewidth": 2.5})
    ax.set_facecolor(th["panel"])
    ax.axis("equal")
    total = vals.sum()
    ax.text(0, 0.08, compact(total), ha="center", va="center", fontsize=17, fontweight="bold", color=th["text"])
    if total_label:
        ax.text(0, -0.16, total_label, ha="center", va="center", fontsize=8.5, color=th["muted"])
    share = vals / total if total else vals
    names = [f"{str(l)[:22]}  {p:.0%}" for l, p in zip(labels, share)]
    from matplotlib.patches import Patch
    ax.legend([Patch(facecolor=c, edgecolor="none") for c in colors], names, frameon=False, fontsize=9,
              loc="center left", bbox_to_anchor=(1.0, 0.5), labelcolor=th["text"], handlelength=1.0)


def histogram(ax, th: dict, values, bins: int = 20, label: str = "") -> None:
    data = np.asarray(values, dtype=float)
    data = data[~np.isnan(data)]
    counts, edges = np.histogram(data, bins=bins)
    for c, a, b in zip(counts, edges[:-1], edges[1:]):
        _gradient_bar(ax, a, b - (b - a) * 0.06, 0, c, th["bar_from"], th["bar_to"])
    mean = float(data.mean())
    ax.axvline(mean, color=th["highlight"], linewidth=1.8, linestyle=(0, (5, 3)), zorder=5)
    ax.annotate(f"average {compact(mean)}", (mean, counts.max()), xytext=(6, -2), textcoords="offset points",
                color=th["highlight"], fontsize=8.5, fontweight="bold", va="top", zorder=6)
    ax.set_xlim(edges[0], edges[-1])
    ax.set_ylim(0, counts.max() * 1.15)
    ax.xaxis.set_major_formatter(axis_formatter())
    ax.yaxis.set_major_formatter(axis_formatter())
    ax.set_ylabel("Number of rows")
    if label:
        ax.set_xlabel(label)


def scatter(ax, th: dict, xs, ys, xlabel: str = "", ylabel: str = "") -> None:
    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    ax.scatter(xs, ys, s=70, color=th["palette"][0], alpha=0.12, linewidth=0, zorder=3)   # soft glow
    ax.scatter(xs, ys, s=20, color=th["palette"][0], alpha=0.85, linewidth=0, zorder=4)
    if len(xs) >= 3 and np.ptp(xs) > 0:
        slope, intercept = np.polyfit(xs, ys, 1)
        line = np.array([xs.min(), xs.max()])
        ax.plot(line, slope * line + intercept, color=th["highlight"], linewidth=2, zorder=5)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.xaxis.set_major_formatter(axis_formatter())
    ax.yaxis.set_major_formatter(axis_formatter())
    ax.grid(axis="x", color=th["grid"], linewidth=0.8, linestyle=(0, (4, 4)))
