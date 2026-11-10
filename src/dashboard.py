"""dashboard.py - a one-page dashboard picture, and a data pack for Power BI.

  make_dashboard(df, ...)   - KPI cards + up to 4 charts on one picture (saved as PNG)
  auto_plan(df)             - when you don't say what to show, Atom looks at the columns and picks
  export_powerbi(df, ...)   - a clean Excel file that Power BI Desktop loads in one click, a how-to,
                              and a Power BI colour theme that matches Atom's look

The numbers come from your real file (pandas), never from the AI.
"""

from __future__ import annotations

import json
import re
from datetime import date

import config
import analysis
import chartstyle
from analysis import _col, _dates, _looks_like_dates, _numeric, _pd

MAX_CHARTS = 4
MAX_KPIS = 4
_METRIC_WORDS = ("sales", "revenue", "amount", "total", "profit", "income", "cost", "price", "spend", "budget",
                 "quantity", "qty", "units", "score", "value")
_ID_WORDS = ("id", "no", "number", "code", "index", "zip", "phone")


# ================================================================ finding out what is in the table
def column_kinds(df) -> dict:
    """{'numbers': [...], 'dates': [...], 'categories': [...]} - what each column looks like."""
    numbers, dates, cats = [], [], []
    for c in df.columns:
        s = df[c]
        present = int(s.notna().sum())
        if not present:
            continue
        if _looks_like_dates(s):
            dates.append(c)
            continue
        n = _numeric(s)
        if n.notna().sum() >= 0.7 * present:
            name = str(c).strip().lower()
            unique = n.nunique()
            if (name in _ID_WORDS or name.endswith((" id", "_id")) or name.startswith("id ")) or (
                unique == present and present > 20 and float(n.dropna().diff().abs().median() or 0) == 1.0
            ):
                continue      # an ID or a row number: not something to add up
            numbers.append(c)
        else:
            unique = s.dropna().astype(str).str.strip().nunique()
            if 2 <= unique <= 20:
                cats.append(c)
    return {"numbers": numbers, "dates": dates, "categories": cats}


def main_metric(numbers: list) -> str | None:
    for word in _METRIC_WORDS:
        for c in numbers:
            if word in str(c).lower():
                return c
    return numbers[0] if numbers else None


def auto_plan(df) -> dict:
    """What a good first dashboard of this table shows: {'kpis': [...], 'charts': [...]}."""
    kinds = column_kinds(df)
    numbers, dates, cats = kinds["numbers"], kinds["dates"], kinds["categories"]
    metric = main_metric(numbers)
    charts, kpis = [], [{"how": "count", "column": "", "label": "Rows"}]
    if metric:
        kpis.append({"how": "sum", "column": metric})
        kpis.append({"how": "mean", "column": metric})
    if dates and metric:
        span = (_dates(df[dates[0]]).max() - _dates(df[dates[0]]).min()).days
        charts.append({"kind": "line", "x": dates[0], "y": metric, "how": "sum",
                       "period": "day" if span < 60 else "month" if span < 1100 else "year"})
    if cats:
        first = cats[0]
        charts.append({"kind": "bar", "x": first, "y": metric or "", "how": "sum" if metric else "count"})
        other = cats[1] if len(cats) > 1 else first
        if other != first or df[first].nunique() <= 6:
            charts.append({"kind": "pie", "x": other, "y": metric or "", "how": "sum" if metric else "count"})
        kpis.append({"how": "distinct", "column": first})
    if len(numbers) >= 2:
        other_metric = next(c for c in numbers if c != metric)
        charts.append({"kind": "scatter", "x": metric, "y": other_metric})
    elif metric:
        charts.append({"kind": "hist", "x": metric})
    if not charts and metric:
        charts.append({"kind": "hist", "x": metric})
    if not charts and cats:
        charts.append({"kind": "bar", "x": cats[0], "y": "", "how": "count"})
    return {"kpis": kpis[:MAX_KPIS], "charts": charts[:MAX_CHARTS]}


def parse_charts(text: str) -> list:
    """'bar,Region,Sales,sum; line,Date,Sales,sum,month; pie,Category,Sales' -> list of chart dicts."""
    charts = []
    for part in re.split(r"[;\n]+", str(text or "")):
        bits = [b.strip() for b in part.split(",")]
        if len(bits) < 2 or not bits[0]:
            continue
        keys = ("kind", "x", "y", "how", "period", "split")
        spec = {k: v for k, v in zip(keys, bits) if v}
        spec.setdefault("how", "sum")
        charts.append(spec)
    return charts[:MAX_CHARTS]


def parse_kpis(text: str) -> list:
    """'sum:Sales, mean:Profit, count:' -> list of kpi dicts."""
    kpis = []
    for part in str(text or "").split(","):
        how, _, column = part.partition(":")
        how = how.strip().lower()
        if how in analysis.HOWS or how == "distinct":
            kpis.append({"how": how, "column": column.strip()})
    return kpis[:MAX_KPIS]


def compute_kpi(df, kpi: dict) -> tuple[str, str, str]:
    """(label, value text, small line) for one KPI card - worked out by pandas."""
    how, column = kpi.get("how", "count"), kpi.get("column", "")
    if how == "count" and not column:
        return kpi.get("label", "Rows"), chartstyle.compact(len(df)), "rows in the table"
    col = _col(df, column)
    if how == "distinct":
        return f"Different {col}", chartstyle.compact(df[col].dropna().astype(str).str.strip().nunique()), "unique values"
    if how == "count":
        return f"Count of {col}", chartstyle.compact(int(df[col].notna().sum())), "filled in"
    s = _numeric(df[col]).dropna()
    if s.empty:
        raise ValueError(f"The column '{col}' has no numbers in it.")
    value = float(getattr(s, {"mean": "mean", "sum": "sum", "min": "min", "max": "max", "median": "median"}[how])())
    return f"{analysis.HOW_NAMES[how]} {col}", chartstyle.compact(value), f"from {len(s):,} values"


# ============================================================================ the picture
def _card(fig, th, rect, label, value, small, accent):
    from matplotlib.patches import FancyBboxPatch

    ax = fig.add_axes(rect)
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.08", transform=ax.transAxes,
                                facecolor=th["panel"], edgecolor=th["edge"], linewidth=1))
    ax.add_patch(FancyBboxPatch((0.0, 0.0), 0.022, 1, boxstyle="round,pad=0,rounding_size=0.011",
                                transform=ax.transAxes, facecolor=accent, edgecolor="none"))
    ax.text(0.07, 0.76, label.upper()[:26], fontsize=8.5, color=th["muted"], va="center", fontweight="bold")
    ax.text(0.07, 0.42, value, fontsize=24, color=th["text"], va="center", fontweight="bold")
    ax.text(0.07, 0.12, small[:34], fontsize=8, color=th["muted"], va="center")


def make_dashboard(df, title: str = "", kpis: list | None = None, charts: list | None = None,
                   notes: list | None = None, theme: str | None = None):
    """Draw the dashboard. Returns (path, text with the KPI numbers and what each chart shows)."""
    import matplotlib
    from matplotlib.figure import Figure

    th = chartstyle.theme(theme or config.CHART_THEME)
    plan = None
    if not charts or not kpis:
        plan = auto_plan(df)
    charts = (charts or plan["charts"])[:MAX_CHARTS]
    kpis = (kpis or plan["kpis"])[:MAX_KPIS]
    if not charts:
        raise ValueError("I couldn't find anything worth drawing in this table. Tell me which columns to use.")

    cards = [compute_kpi(df, k) for k in kpis]
    n = len(charts)
    with matplotlib.rc_context(chartstyle.font_settings()):
        fig = Figure(figsize=(14, 9.2 if n > 2 else 6.4 if n == 1 else 7.6), dpi=120)
        chartstyle.setup(fig, th)
        W, H = fig.get_size_inches()
        title = title or "Overview"
        fig.text(0.03, 1 - 0.55 / H, title, fontsize=21, fontweight="bold", color=th["text"], va="center")
        sub = " · ".join(x for x in (notes or []) if x)[:150]
        if sub:
            fig.text(0.03, 1 - 0.95 / H, sub, fontsize=9.5, color=th["muted"], va="center")
        fig.text(0.97, 1 - 0.55 / H, f"{date.today():%d %b %Y}", fontsize=10, color=th["muted"], va="center", ha="right")

        # KPI cards
        top = 1 - 1.2 / H
        card_h = 1.05 / H
        accents = [th["highlight"], th["palette"][0], th["palette"][2], th["palette"][3]]
        k = max(1, len(cards))
        gap = 0.014
        card_w = (0.94 - gap * (k - 1)) / k
        for i, (label, value, small) in enumerate(cards):
            _card(fig, th, [0.03 + i * (card_w + gap), top - card_h, card_w, card_h], label, value, small, accents[i % 4])

        # charts grid: each chart gets a panel; room is left for its title (top), labels (left, bottom)
        area_top = top - card_h - 0.35 / H
        area_bottom = 0.45 / H
        rows = 1 if n <= 2 else 2
        cols = n if n <= 2 else 2
        hgap, vgap = 0.04, 0.25 / H
        cell_w = (0.94 - hgap * (cols - 1)) / cols
        cell_h = (area_top - area_bottom - vgap * (rows - 1)) / rows
        slots = [(0, 0, 2), (1, 0, 1), (1, 1, 1)] if n == 3 else [(i % cols, i // cols, 1) for i in range(n)]
        title_room, label_room, left_room = 0.55 / H, 0.55 / H, 0.62 / W
        results = []
        for spec, (c, r, tall) in zip(charts, slots):
            left = 0.03 + c * (cell_w + hgap)
            height = cell_h * tall + vgap * (tall - 1)
            edge = area_top - r * (cell_h + vgap)          # the top of this slot
            kind = spec.get("kind", "bar")
            pie = kind == "pie"
            ax = fig.add_axes([left + (0.0 if pie else left_room), edge - height + label_room * (0.4 if pie else 1.0),
                               cell_w * (0.5 if pie else 1.0) - (0.0 if pie else left_room),
                               height - title_room - label_room * (0.4 if pie else 1.0)])
            name, summary = analysis.draw_chart(ax, df, kind, spec.get("x", ""), spec.get("y", ""),
                                                spec.get("how", "sum"), spec.get("period", ""), spec.get("split", ""),
                                                10, None, th)
            fig.text(left, edge - 0.17 / H, spec.get("title") or name, fontsize=11.5, fontweight="bold",
                     color=th["text"], va="center")
            if kind in ("bar", "line"):
                ax.set_xlabel("")
                ax.set_ylabel("")
                ax.tick_params(labelsize=8)
            lines_ = summary.splitlines()
            results.append(f"- {lines_[0]}" + ("\n  " + "\n  ".join(lines_[1:9]) if len(lines_) > 1 else ""))
        chartstyle.footer(fig, th)

        config.CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "dashboard"
        path = config.CHARTS_DIR / f"{date.today():%Y-%m-%d}-dashboard-{slug}.png"
        number = 2
        while path.exists():
            path = config.CHARTS_DIR / f"{date.today():%Y-%m-%d}-dashboard-{slug}-{number}.png"
            number += 1
        fig.savefig(path, facecolor=fig.get_facecolor())
    text = "Dashboard numbers:\n" + "\n".join(f"- {label}: {value} ({small})" for label, value, small in cards)
    text += "\nCharts:\n" + "\n".join(results)
    return path, text[: analysis.MAX_OUT]


# ============================================================================= Power BI
def clean_for_powerbi(df):
    """A tidy copy: trimmed text, real numbers, real dates, unique non-empty column names, no empty rows."""
    pd = _pd()
    out = df.copy()
    out = out.replace(r"^\s*$", pd.NA, regex=True)         # blank text counts as empty (CSV files have lots of it)
    out = out.dropna(how="all").dropna(axis=1, how="all")
    names, seen = [], {}
    for i, c in enumerate(out.columns):
        name = re.sub(r"\s+", " ", str(c)).strip() or f"Column {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} {seen[name]}"
        else:
            seen[name] = 1
        names.append(name)
    out.columns = names
    for c in out.columns:
        s = out[c]
        present = int(s.notna().sum())
        if not present:
            continue
        if _looks_like_dates(s):
            out[c] = _dates(s).dt.date
        elif not pd.api.types.is_numeric_dtype(s):
            n = _numeric(s)
            if n.notna().sum() >= 0.9 * present:
                out[c] = n
            else:
                out[c] = s.astype("string").str.strip()
    return out


THEME_JSON = {
    "name": "Atom Jester",
    "dataColors": ["#E4CC54", "#FF4B6E", "#3BB3C3", "#9B6BDC", "#43B581", "#F2A33A", "#5B8CFF", "#FF8FA6"],
    "background": "#1C1216",
    "foreground": "#FFF4EC",
    "tableAccent": "#E4CC54",
    "good": "#43B581",
    "neutral": "#E4CC54",
    "bad": "#FF4B6E",
    "maximum": "#E4CC54",
    "center": "#FF8FA6",
    "minimum": "#B3122F",
}


def powerbi_howto(file_name: str, table_name: str, df, plan: dict, theme_name: str) -> str:
    kinds = column_kinds(df)
    metric = main_metric(kinds["numbers"])
    q = lambda c: f"{table_name}[{c}]"      # noqa: E731
    lines = [
        f"HOW TO USE  {file_name}  IN POWER BI DESKTOP",
        "=" * 60,
        "",
        "1. Open Power BI Desktop (tell Atom: \"open Power BI\").",
        f"2. Home > Get data > Excel workbook > pick  {file_name}",
        f"   Tick the table  {table_name}  and press Load.",
        "   The numbers and dates are already clean, so you can skip \"Transform data\".",
        f"3. Make it look like Atom: View > Themes > Browse for themes > pick  {theme_name}",
        "   (a dark theme in the jester's colours).",
        "",
        "SUGGESTED VISUALS (click a visual type, then drag the columns in):",
    ]
    for spec in plan["charts"]:
        k, x, y = spec.get("kind"), spec.get("x"), spec.get("y")
        how = {"sum": "Sum", "mean": "Average", "count": "Count"}.get(spec.get("how", "sum"), "Sum")
        if k == "line":
            lines.append(f"- Line chart:  X-axis = {x} (use the date hierarchy: Month),  Y-axis = {how} of {y}")
        elif k == "bar":
            lines.append(f"- Clustered column chart:  X-axis = {x},  Y-axis = {how} of {y or 'rows (Count)'}")
        elif k == "pie":
            lines.append(f"- Donut chart:  Legend = {x},  Values = {how} of {y or 'rows (Count)'}")
        elif k == "scatter":
            lines.append(f"- Scatter chart:  X-axis = {x},  Y-axis = {y}")
        elif k == "hist":
            lines.append(f"- Column chart:  X-axis = {x} (right-click it > New group > Bin size),  Y-axis = Count of {x}")
    lines.append("- Card visuals (the big numbers on top): drag a number column in, choose Sum / Average.")
    lines += ["", "SUGGESTED MEASURES (Home > New measure, then paste one line):"]
    lines.append(f"Row Count = COUNTROWS({table_name})")
    if metric:
        lines.append(f"Total {metric} = SUM({q(metric)})")
        lines.append(f"Average {metric} = AVERAGE({q(metric)})")
        lines.append(f"Biggest {metric} = MAX({q(metric)})")
    if kinds["dates"] and metric:
        d = kinds["dates"][0]
        lines.append(f"{metric} Last Year = CALCULATE(SUM({q(metric)}), SAMEPERIODLASTYEAR({q(d)}))")
        lines.append(f"{metric} Growth % = DIVIDE([Total {metric}] - [{metric} Last Year], [{metric} Last Year])")
    lines += [
        "",
        "REFRESHING: when you change the Excel file, press Refresh in Power BI and the visuals update.",
        "",
        "Power BI is Microsoft's own app: Atom can't build the report for you inside it, but this pack",
        "gets you from file to first chart in about two minutes.",
    ]
    return "\n".join(lines) + "\n"


def export_powerbi(df, stem: str, notes: list | None = None) -> dict:
    """Write the Excel file, the how-to and the theme into  POWERBI_DIR/<stem>/ . Returns the paths."""
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    pd = _pd()
    clean = clean_for_powerbi(df)
    if clean.empty or clean.shape[1] == 0:
        raise ValueError("There is no data to export.")
    safe = re.sub(r"[^\w\- ]+", "", stem).strip() or "data"
    folder = config.POWERBI_DIR / safe
    folder.mkdir(parents=True, exist_ok=True)
    table_name = "AtomData"
    xlsx = folder / f"{safe} for Power BI.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl", date_format="yyyy-mm-dd", datetime_format="yyyy-mm-dd") as writer:
        clean.to_excel(writer, sheet_name="Data", index=False)
        ws = writer.sheets["Data"]
        ref = f"A1:{get_column_letter(clean.shape[1])}{len(clean) + 1}"
        tab = Table(displayName=table_name, ref=ref)
        tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(tab)
        ws.freeze_panes = "A2"
        for i, c in enumerate(clean.columns, 1):
            width = min(40, max(10, int(clean[c].astype(str).str.len().head(300).max() or 8) + 2, len(str(c)) + 4))
            ws.column_dimensions[get_column_letter(i)].width = width
            ws.cell(row=1, column=i).font = Font(bold=True)
            ws.cell(row=1, column=i).alignment = Alignment(vertical="center")
    theme_path = folder / "Atom Jester theme.json"
    theme_path.write_text(json.dumps(THEME_JSON, indent=2), encoding="utf-8")
    plan = auto_plan(clean)
    howto = folder / "HOW TO - open in Power BI.txt"
    howto.write_text(powerbi_howto(xlsx.name, table_name, clean, plan, "Atom Jester theme.json"), encoding="utf-8")
    return {"folder": folder, "xlsx": xlsx, "theme": theme_path, "howto": howto,
            "rows": len(clean), "columns": list(clean.columns)}
