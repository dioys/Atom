"""analysis.py - Step 4b: Atom as a data analyst.

No window code and no AI code in here. The AI never does the maths: it only
says WHAT it wants ("total of Sales by year") and this file calculates it from
your real spreadsheet with pandas, then draws charts with matplotlib.

  aggregate()   - sum / average / count / min / max / median of a column,
                  overall, per category, or per year / quarter / month / week,
                  optionally split into series (e.g. months, one line per year)
  stats_text()  - mean, median, spread, outliers and relationships (correlation)
  make_chart()  - bar, line, pie, scatter and histogram charts saved as PNG (the look is in chartstyle.py)
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import get_close_matches
from pathlib import Path

import config
import reports

MAX_ROWS = 300_000
MAX_OUT = 3000                      # text handed back to the AI is cut to this size
HOWS = ("sum", "mean", "count", "min", "max", "median")
PERIODS = ("year", "quarter", "month", "week", "day")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HOW_NAMES = {"sum": "Total", "mean": "Average", "count": "Count", "min": "Lowest", "max": "Highest", "median": "Median"}
ACCENT = "#5b8cff"
PALETTE = ["#5b8cff", "#f2a33a", "#43b581", "#e5675f", "#9b6bdc", "#3bb3c3", "#c7a14a", "#7f8794"]


def _pd():
    try:
        import pandas as pd
    except ImportError as error:
        raise ValueError("Data analysis needs pandas. Run: python -m pip install pandas matplotlib") from error
    return pd


# ================================================================= loading
def _read_csv_rows(path: Path) -> list[list]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows = []
    for row in csv.reader(text.splitlines(), delimiter=delimiter):
        rows.append([c if c.strip() else None for c in row])
        if len(rows) > MAX_ROWS:
            break
    return rows


def _pick_sheet(wanted: str, sheets: list[str]) -> str:
    low = {s.lower(): s for s in sheets}
    key = wanted.strip().lower()
    if key in low:
        return low[key]
    close = get_close_matches(key, list(low), n=1, cutoff=0.6)
    if close:
        return low[close[0]]
    raise ValueError(f"There is no sheet '{wanted}'. The sheets are: {', '.join(sheets)}.")


def _frame(raw):
    """Raw cells -> a table: find the header row (title rows above it are skipped)."""
    pd = _pd()
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if raw.empty:
        raise ValueError("That sheet is empty.")
    filled = raw.notna().sum(axis=1)
    start = int(next((i for i, n in enumerate(filled) if n >= 2), 0))
    names, seen = [], {}
    for i, value in enumerate(raw.iloc[start]):
        name = str(value).strip() if pd.notna(value) and str(value).strip() else f"Column {i + 1}"
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    table = raw.iloc[start + 1 :].reset_index(drop=True)
    table.columns = names
    table = table.dropna(how="all").reset_index(drop=True)
    if table.empty:
        raise ValueError("I found column names but no data rows under them.")
    return table


def load_table(path: Path, sheet: str = ""):
    """Read an Excel/CSV file into a pandas table. Returns (table, sheet name)."""
    pd = _pd()
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        return _frame(pd.DataFrame(_read_csv_rows(path))), "(whole file)"
    if suffix in (".xlsx", ".xlsm"):
        book = pd.ExcelFile(path)
        sheets = list(book.sheet_names)
        candidates = [_pick_sheet(sheet, sheets)] if sheet else sheets
        for name in candidates:
            raw = book.parse(name, header=None, nrows=MAX_ROWS)
            if raw.dropna(how="all").shape[0] >= 2:
                return _frame(raw), name
        raise ValueError("I found no table with data in that workbook.")
    raise ValueError("The data tools work on Excel (.xlsx) and CSV files only.")


def prepare(path: Path, sheet: str = "", filter_column: str = "", filter_value: str = ""):
    """Load the table and apply an optional 'column = value' filter."""
    df, sheet_name = load_table(path, sheet)
    notes = [f"file {path.name}, sheet {sheet_name}"]
    if filter_column:
        column = _col(df, filter_column)
        wanted = str(filter_value).strip().lower()
        df = df[df[column].astype(str).str.strip().str.lower() == wanted]
        notes.append(f"only rows where {column} = {filter_value}")
        if df.empty:
            raise ValueError(f"No rows have {column} = {filter_value}.")
    return df, notes


# ================================================================= columns
def _col(df, name: str) -> str:
    want = str(name or "").strip().lower()
    cols = list(df.columns)
    lower = {c.lower(): c for c in cols}
    if want in lower:
        return lower[want]
    contains = [c for c in cols if want and want in c.lower()]
    if len(contains) == 1:
        return contains[0]
    close = get_close_matches(want, list(lower), n=1, cutoff=0.75)
    if close:
        return lower[close[0]]
    raise ValueError(f"There is no column '{name}'. The columns are: {', '.join(cols)}.")


def _numeric(series):
    pd = _pd()
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = series.astype(str).str.replace(r"[,$₱€£\s]", "", regex=True).str.rstrip("%")
    cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # (1200) means -1200
    return pd.to_numeric(cleaned, errors="coerce")


_DATE_TEXT = re.compile(
    r"^\s*(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} [A-Za-z]{3,9}\.? \d{4})"
)


def _looks_like_dates(series) -> bool:
    pd = _pd()
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    sample = series.dropna().head(200)
    if sample.empty:
        return False
    hits = sum(
        isinstance(v, (datetime, date, pd.Timestamp)) or (isinstance(v, str) and bool(_DATE_TEXT.match(v)))
        for v in sample
    )
    return hits >= 0.7 * len(sample)


def _dates(series):
    pd = _pd()
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, errors="coerce", format="mixed")


def _period_labels(dt, period: str, seasonal: bool):
    """Turn dates into group names: 2025, 2025-Q1, 2025-03 ... (seasonal: Q1, Mar)."""
    if period == "year":
        return dt.dt.strftime("%Y")
    if period == "quarter":
        quarter = dt.dt.quarter.astype("Int64").astype("string")
        return ("Q" + quarter) if seasonal else (dt.dt.strftime("%Y") + "-Q" + quarter)
    if period == "month":
        return dt.dt.strftime("%b") if seasonal else dt.dt.strftime("%Y-%m")
    if period == "week":
        return dt.dt.strftime("%G-W%V")
    return dt.dt.strftime("%Y-%m-%d")


# ============================================================== aggregation
@dataclass
class Grouped:
    table: object                     # pandas table: rows = groups, columns = series
    how: str
    value: str
    by_label: str
    split: str
    is_date: bool
    rows_used: int
    skipped: int
    notes: list = field(default_factory=list)


def aggregate(df, value: str = "", by: str = "", how: str = "sum", period: str = "",
              split: str = "", top: int = 20) -> Grouped:
    pd = _pd()
    how = (how or "sum").lower()
    if how not in HOWS:
        raise ValueError(f"'how' must be one of: {', '.join(HOWS)}.")
    period = (period or "").lower()
    if period and period not in PERIODS:
        raise ValueError(f"'period' must be one of: {', '.join(PERIODS)}.")

    value_col = _col(df, value) if value else ""
    if how == "count":
        values = df[value_col].notna().astype(float) if value_col else pd.Series(1.0, index=df.index)
    else:
        if not value_col:
            raise ValueError(f"Tell me which column to {how}. The columns are: {', '.join(df.columns)}.")
        values = _numeric(df[value_col])
        if values.notna().sum() == 0:
            raise ValueError(f"The column '{value_col}' has no numbers in it.")
    frame = pd.DataFrame({"v": values})

    by_label, is_date, split_name = "", False, ""
    if by:
        by_col = _col(df, by)
        series = df[by_col]
        is_date = _looks_like_dates(series)
        if period and not is_date:
            raise ValueError(f"The column '{by_col}' doesn't look like dates, so I can't group it by {period}.")
        seasonal = False
        if is_date:
            period = period or "month"
            dt = _dates(series)
            if split.strip().lower() == "year":
                if period == "year":
                    raise ValueError("I can't split years by year.")
                seasonal, split_name = True, "year"
                frame["split"] = dt.dt.strftime("%Y")
            frame["label"] = _period_labels(dt, period, seasonal)
            by_label = f"{by_col} ({period}{', per year' if seasonal else ''})"
        else:
            frame["label"] = series.astype(str).str.strip().where(series.notna())
            by_label = by_col
        if split and not split_name:
            split_name = _col(df, split)
            frame["split"] = df[split_name].astype(str).str.strip().where(df[split_name].notna())

    needed = [c for c in ("label", "split") if c in frame] + ([] if how == "count" else ["v"])
    before = len(frame)
    frame = frame.dropna(subset=needed)
    skipped = before - len(frame)
    if frame.empty:
        raise ValueError("Nothing is left after removing empty values.")

    func = {"sum": "sum", "mean": "mean", "count": "sum", "min": "min", "max": "max", "median": "median"}[how]
    notes = []
    if not by:
        table = pd.DataFrame({"value": [float(frame["v"].agg(func))]}, index=["all rows"])
    else:
        keys = ["label", "split"] if "split" in frame else ["label"]
        grouped = frame.groupby(keys, sort=False)["v"].agg(func)
        table = grouped.unstack("split") if "split" in frame else grouped.to_frame("value")
        if is_date:  # chronological
            order = MONTHS if (period == "month" and split_name == "year") else None
            if order:
                table = table.reindex([m for m in order if m in table.index])
            else:
                table = table.sort_index()
            table = table[sorted(table.columns)]
        else:  # biggest first
            table = table.loc[table.fillna(0).sum(axis=1).sort_values(ascending=False).index]
            if len(table) > top:
                notes.append(f"showing the top {top} of {len(table)} groups")
                table = table.head(top)
    return Grouped(table, how, value_col, by_label, split_name, is_date, len(frame), skipped, notes)


def _num(x: float) -> str:
    return reports._fmt(float(x))


def _change(new: float, old: float) -> str:
    if old == 0:
        return f"{new - old:+,.0f}, n/a%"
    return f"{new - old:+,.0f}, {(new - old) / abs(old) * 100:+.1f}%"


def describe(g: Grouped) -> str:
    """The result as plain text, with change vs the previous group for dates."""
    t = g.table
    what = g.value or "rows"
    head = f"{HOW_NAMES[g.how]} of {what}"
    if g.by_label:
        head += f" by {g.by_label}"
    if g.split and "per year" not in g.by_label:
        head += f", split by {g.split}"
    lines = [head]
    cols = list(t.columns)
    if len(cols) == 1:
        previous = None
        for label, row in t.iterrows():
            value = float(row.iloc[0])
            extra = f"  ({_change(value, previous[1])} vs {previous[0]})" if g.is_date and previous else ""
            lines.append(f"{label}: {_num(value)}{extra}")
            previous = (label, value)
        if len(t) > 1 and g.how in ("sum", "count"):
            lines.append(f"Total: {_num(t.iloc[:, 0].sum())}")
    else:
        header = ["", *map(str, cols)] + ([f"change {cols[-1]} vs {cols[0]}"] if len(cols) == 2 else [])
        lines.append(" | ".join(header))
        for label, row in t.iterrows():
            cells = [("-" if row[c] != row[c] else _num(row[c])) for c in cols]
            change = []
            if len(cols) == 2 and row[cols[0]] == row[cols[0]] and row[cols[1]] == row[cols[1]]:
                change = [_change(row[cols[1]], row[cols[0]])]
            lines.append(" | ".join([str(label), *cells, *change]))
        if g.how in ("sum", "count"):
            totals = [t[c].sum() for c in cols]
            extra = [_change(totals[1], totals[0])] if len(cols) == 2 else []
            lines.append(" | ".join(["TOTAL", *[_num(x) for x in totals], *extra]))
    lines.append(f"({g.rows_used} rows used" + (f"; {g.skipped} skipped because a value was empty" if g.skipped else "") + ")")
    lines.extend(g.notes)
    return "\n".join(lines)[:MAX_OUT]


# ============================================================== statistics
def stats_text(df, columns: str = "", notes: list | None = None) -> str:
    pd = _pd()
    wanted = [c.strip() for c in str(columns or "").split(",") if c.strip()]
    if wanted:
        cols = [_col(df, c) for c in wanted]
    else:
        cols = [c for c in df.columns if _numeric(df[c]).notna().mean() >= 0.7 and not _looks_like_dates(df[c])][:8]
        if not cols:
            cols = list(df.columns)[:4]
    lines = [f"Statistics ({len(df)} rows; {'; '.join(notes or [])})"]
    numbers = {}
    for c in cols:
        present = int(df[c].notna().sum())
        s = _numeric(df[c])
        if present and s.notna().sum() >= 0.5 * present and not _looks_like_dates(df[c]):
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            spread = q3 - q1
            outliers = int(((s < q1 - 1.5 * spread) | (s > q3 + 1.5 * spread)).sum())
            lines.append(
                f"- {c}: {int(s.notna().sum())} values ({len(df) - present} missing); mean {_num(s.mean())}, "
                f"median {_num(s.median())}, std dev {_num(s.std() if s.notna().sum() > 1 else 0)}, "
                f"min {_num(s.min())}, 10% {_num(s.quantile(0.10))}, 25% {_num(q1)}, 75% {_num(q3)}, "
                f"90% {_num(s.quantile(0.90))}, max {_num(s.max())}; "
                f"{outliers} unusual values (outliers)"
            )
            numbers[c] = s
        else:
            counts = df[c].dropna().astype(str).str.strip().value_counts()
            top = ", ".join(f"{k} ({v})" for k, v in counts.head(5).items())
            lines.append(f"- {c}: {len(counts)} different values; most common: {top}")
    if len(numbers) >= 2:
        corr = pd.DataFrame(numbers).corr()
        pairs = []
        names = list(corr.columns)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                r = corr.loc[a, b]
                if r == r and abs(r) >= 0.3:
                    strength = "strongly" if abs(r) >= 0.7 else "moderately" if abs(r) >= 0.5 else "weakly"
                    way = "rise together" if r > 0 else "move in opposite directions"
                    pairs.append((abs(r), f"- {a} and {b} {strength} {way} (correlation {r:+.2f})"))
        if pairs:
            lines.append("Relationships:")
            lines.extend(text for _, text in sorted(pairs, reverse=True)[:5])
        else:
            lines.append("Relationships: no clear relationship between the number columns.")
    return "\n".join(lines)[:MAX_OUT]


# ================================================================== charts


def draw_chart(ax, df, kind: str, x: str, y: str = "", how: str = "sum", period: str = "",
               split: str = "", top: int = 12, notes: list | None = None, th: dict | None = None):
    """Draw one chart into `ax`. Returns (title, what it shows). Used by make_chart and by the dashboard."""
    import chartstyle

    th = th or chartstyle.theme(config.CHART_THEME)
    kind = (kind or "bar").lower()
    if kind not in ("bar", "line", "pie", "scatter", "hist"):
        raise ValueError("Chart kind must be one of: bar, line, pie, scatter, hist.")
    chartstyle.style_axes(ax, th)
    if kind == "hist":
        col = _col(df, x)
        s = _numeric(df[col]).dropna()
        if s.empty:
            raise ValueError(f"The column '{col}' has no numbers to draw.")
        chartstyle.histogram(ax, th, s.to_numpy(), 20, col)
        return (f"Distribution of {col}",
                f"Histogram of {col}: {len(s)} values, mean {_num(s.mean())}, median {_num(s.median())}, "
                f"from {_num(s.min())} to {_num(s.max())}.")
    if kind == "scatter":
        if not y:
            raise ValueError("A scatter chart needs both x and y (two number columns).")
        xc, yc = _col(df, x), _col(df, y)
        pair = _pd().DataFrame({"x": _numeric(df[xc]), "y": _numeric(df[yc])}).dropna()
        if len(pair) < 2:
            raise ValueError("I need at least two rows where both columns are numbers.")
        pair = pair.sample(5000, random_state=1) if len(pair) > 5000 else pair
        chartstyle.scatter(ax, th, pair["x"].to_numpy(), pair["y"].to_numpy(), xc, yc)
        r = pair["x"].corr(pair["y"])
        return f"{yc} vs {xc}", f"Scatter of {yc} against {xc}: {len(pair)} points, correlation {r:+.2f}."

    g = aggregate(df, value=y, by=x, how=how if y else "count", period=period, split=split, top=top)
    table = g.table
    g.notes.extend(notes or [])
    multi = len(table.columns) > 1
    labels = [str(i) for i in table.index]
    if kind == "pie":
        if multi:
            raise ValueError("A pie chart can't be split into series. Use a bar or line chart.")
        series = table.iloc[:, 0].clip(lower=0).sort_values(ascending=False)
        if len(series) > 8:  # keep the 7 biggest slices, lump the rest together
            pd = _pd()
            series = pd.concat([series.head(7), pd.Series({"Other": series.iloc[7:].sum()})])
        chartstyle.donut(ax, th, [str(i) for i in series.index], series.to_numpy(),
                         f"{HOW_NAMES[g.how].lower()} of {g.value}" if g.value else "rows")
    else:
        columns = {str(c): table[c].to_numpy() for c in table.columns}
        if kind == "bar":
            chartstyle.bars(ax, th, labels, columns, label_values=len(table) <= 24, legend_title=g.split.title())
        else:
            chartstyle.lines(ax, th, labels, columns, legend_title=g.split.title())
        ax.set_xlabel(g.by_label)
        ax.set_ylabel(f"{HOW_NAMES[g.how]} of {g.value or 'rows'}")
        if len(table) > 6:
            for label in ax.get_xticklabels():
                label.set_rotation(40)
                label.set_ha("right")
    return describe(g).splitlines()[0], describe(g)


def make_chart(df, kind: str, x: str, y: str = "", how: str = "sum", period: str = "",
               split: str = "", title: str = "", top: int = 12, notes: list | None = None):
    """Draw a chart, save it as a PNG. Returns (path, text describing what it shows)."""
    import matplotlib
    from matplotlib.figure import Figure

    import chartstyle

    th = chartstyle.theme(config.CHART_THEME)
    with matplotlib.rc_context(chartstyle.font_settings()):
        fig = Figure(figsize=(9, 5.6), dpi=130)
        chartstyle.setup(fig, th)
        pie = (kind or "").lower() == "pie"
        ax = fig.add_axes([0.04, 0.06, 0.50, 0.74] if pie else [0.085, 0.15, 0.875, 0.67])
        auto_title, summary = draw_chart(ax, df, kind, x, y, how, period, split, top, notes, th)
        title = title or auto_title
        sub = " \u00b7 ".join(n for n in (notes or []) if n)[:110]
        chartstyle.heading(ax, th, title, sub)
        chartstyle.footer(fig, th)
        config.CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "chart"
        path = config.CHARTS_DIR / f"{date.today():%Y-%m-%d}-{slug}.png"
        number = 2
        while path.exists():
            path = config.CHARTS_DIR / f"{date.today():%Y-%m-%d}-{slug}-{number}.png"
            number += 1
        fig.savefig(path, facecolor=fig.get_facecolor())
    return path, summary[:MAX_OUT]


# ======================================================== entry points (tools)
def _int(value, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def run_aggregate(path: Path, **a) -> str:
    df, notes = prepare(path, a.get("sheet", ""), a.get("filter_column", ""), a.get("filter_value", ""))
    g = aggregate(df, a.get("value", ""), a.get("by", ""), a.get("how", "sum"),
                  a.get("period", ""), a.get("split", ""), _int(a.get("top"), 20))
    g.notes.extend(notes)
    return describe(g)


def run_stats(path: Path, **a) -> str:
    df, notes = prepare(path, a.get("sheet", ""), a.get("filter_column", ""), a.get("filter_value", ""))
    return stats_text(df, a.get("columns", ""), notes)


def run_chart(path: Path, **a):
    df, notes = prepare(path, a.get("sheet", ""), a.get("filter_column", ""), a.get("filter_value", ""))
    return make_chart(df, a.get("kind", "bar"), a.get("x", ""), a.get("y", ""), a.get("how", "sum"),
                      a.get("period", ""), a.get("split", ""), a.get("title", ""), _int(a.get("top"), 12), notes)


def run_dashboard(path: Path, **a):
    import dashboard

    df, notes = prepare(path, a.get("sheet", ""), a.get("filter_column", ""), a.get("filter_value", ""))
    return dashboard.make_dashboard(df, a.get("title", ""), dashboard.parse_kpis(a.get("kpis", "")) or None,
                                    dashboard.parse_charts(a.get("charts", "")) or None, notes)


def run_export_powerbi(path: Path, **a):
    import dashboard

    df, notes = prepare(path, a.get("sheet", ""))
    return dashboard.export_powerbi(df, path.stem, notes)


def run_build_powerbi(path: Path, **a):
    import dashboard
    import pbip

    df, notes = prepare(path, a.get("sheet", ""), a.get("filter_column", ""), a.get("filter_value", ""))
    return pbip.build_project(df, path.stem, a.get("title", ""), dashboard.parse_kpis(a.get("kpis", "")) or None,
                              dashboard.parse_charts(a.get("charts", "")) or None, notes)
