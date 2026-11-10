"""analyst.py - Step 10: the heavier data-analyst tools.

Everything runs on your computer with pandas (no AI, no internet). Atom only READS your files; anything he
saves is a NEW file in  ~/.atom/reports  (never your original).

  pivot_table    rows x columns table with totals and shares      (tool data_pivot)
  compare        what changed between two files or two sheets     (tool data_compare)
  trend          growth per period, straight-line forecast        (tool data_trend)
  relate         how much one column moves another (regression)   (tool data_relate)
  find_issues    messy-data check + an optional cleaned copy      (tool data_cleanup)
  join           put two files together on a shared column        (tool data_join)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from difflib import get_close_matches
from pathlib import Path

import analysis as A
import config

MAX_OUT = A.MAX_OUT
PLACEHOLDERS = {"n/a", "na", "none", "null", "nan", "-", "--", "?", "tbd", "nil", "#n/a", "unknown"}


def _np():
    try:
        import numpy as np
    except ImportError as error:
        raise ValueError("This needs numpy. Run: python -m pip install numpy pandas") from error
    return np




def _is_text_column(series) -> bool:
    pd = A._pd()
    return not (pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series)
                or pd.api.types.is_bool_dtype(series))


def _save_path(stem: str, tag: str, ext: str = ".xlsx") -> Path:
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\- ]+", "", stem).strip().replace(" ", "-")[:40] or "data"
    path = config.REPORTS_DIR / f"{date.today():%Y-%m-%d}-{tag}-{safe}{ext}"
    number = 2
    while path.exists():
        path = config.REPORTS_DIR / f"{date.today():%Y-%m-%d}-{tag}-{safe}-{number}{ext}"
        number += 1
    return path


def _write_xlsx(df, path: Path, sheet: str = "Data") -> None:
    """A tidy Excel file: bold header, frozen top row, sensible column widths."""
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    pd = A._pd()
    with pd.ExcelWriter(path, engine="openpyxl", date_format="yyyy-mm-dd", datetime_format="yyyy-mm-dd") as writer:
        df.to_excel(writer, sheet_name=sheet, index=False)
        ws = writer.sheets[sheet]
        ws.freeze_panes = "A2"
        for i, name in enumerate(df.columns, 1):
            longest = df[name].dropna().astype(str).str.len().head(300).max()
            width = min(40, max(10, len(str(name)) + 4, (int(longest) if longest == longest else 8) + 2))
            ws.column_dimensions[get_column_letter(i)].width = width
            ws.cell(row=1, column=i).font = Font(bold=True)


# ====================================================================== pivot
@dataclass
class Pivot:
    table: object
    text: str
    title: str
    additive: bool
    percent: bool
    notes: list = field(default_factory=list)


def pivot_table(df, rows: str, columns: str = "", value: str = "", how: str = "sum", period: str = "",
                top: int = 15, percent: bool = False, max_cols: int = 8) -> Pivot:
    pd = A._pd()
    if not rows:
        raise ValueError("Tell me which column to put down the side (rows).")
    how = (how or "sum").lower()
    g = A.aggregate(df, value, rows, how, period, columns, top=1_000_000)
    t = g.table.copy()
    notes = list(g.notes)
    additive = how in ("sum", "count")
    if list(t.columns) == ["value"]:
        t.columns = [A.HOW_NAMES[how]]

    if columns and t.shape[1] > max_cols:                       # too many columns: keep the biggest
        order = list(t.fillna(0).sum().sort_values(ascending=False).index)
        keep = set(order[:max_cols])
        kept = [c for c in t.columns if c in keep]
        rest = [c for c in t.columns if c not in keep]
        if additive:
            other = t[rest].sum(axis=1)
            t = t[kept].copy()
            t["Other"] = other
            notes.append(f"{len(rest)} smaller columns are combined into 'Other'")
        else:
            t = t[kept]
            notes.append(f"showing the {max_cols} biggest of {len(order)} columns")

    limit = max(1, top)
    if g.is_date and len(t) > 36:
        t = t.tail(36)
        notes.append("showing the latest 36 periods")
    elif not g.is_date and len(t) > limit:
        if additive:
            other = t.iloc[limit:].sum()
            t = t.iloc[:limit].copy()
            t.loc["Other"] = other
            notes.append(f"the rest of the rows are combined into 'Other'")
        else:
            t = t.iloc[:limit]
            notes.append(f"showing the top {limit} rows")

    grand = None
    if additive:
        if t.shape[1] > 1:
            t["Total"] = t.sum(axis=1)
        t.loc["TOTAL"] = t.sum()
        grand = float(t.iloc[-1, -1]) if t.shape[1] else 0.0
        if percent and grand:
            t = t / grand * 100
    elif percent:
        notes.append("shares only make sense for totals and counts, so I showed the plain numbers")
        percent = False

    what = f"{A.HOW_NAMES[how]} of {g.value or 'rows'}"
    title = f"{what} by {g.by_label}" + (f" and {g.split or columns}" if columns else "")
    if percent:
        title += " (percent of the grand total)"
    cells = (lambda v: "-" if v != v else (f"{v:.1f}%" if percent else A._num(v)))
    lines = [title, " | ".join(["", *map(str, t.columns)])]
    for label, row in t.iterrows():
        lines.append(" | ".join([str(label), *[cells(row[c]) for c in t.columns]]))
    lines.append(f"({g.rows_used} rows used" + (f"; {g.skipped} skipped because a value was empty" if g.skipped else "") + ")")
    lines.extend(notes)
    return Pivot(t, "\n".join(lines)[:MAX_OUT], title, additive, percent, notes)


def save_pivot(result: Pivot, stem: str) -> Path:
    """The pivot as an Excel file with a real (editable) Excel chart under it."""
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    t = result.table
    wb = Workbook()
    ws = wb.active
    ws.title = "Pivot"
    ws.append([result.title])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([""] + [str(c) for c in t.columns])
    for cell in ws[2]:
        cell.font = Font(bold=True)
    for label, row in t.iterrows():
        ws.append([str(label)] + [None if v != v else float(v) for v in row])
        if str(label) == "TOTAL":
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
    fmt = '0.0"%"' if result.percent else "#,##0.##"
    for r in ws.iter_rows(min_row=3, min_col=2):
        for cell in r:
            cell.number_format = fmt
    ws.column_dimensions["A"].width = max(14, min(40, max(len(str(i)) for i in t.index) + 2))
    for i in range(2, t.shape[1] + 2):
        ws.column_dimensions[get_column_letter(i)].width = 16
    ws.freeze_panes = "B3"

    data_rows = [i for i, label in enumerate(t.index) if str(label) != "TOTAL"][:15]
    data_cols = [i for i, c in enumerate(t.columns) if str(c) != "Total"]
    if data_rows and data_cols:
        chart = BarChart()
        chart.type = "col"
        chart.title = result.title[:80]
        chart.height, chart.width = 9, 18
        first_col, last_col = 2 + data_cols[0], 2 + data_cols[-1]
        first_row, last_row = 3, 2 + len(data_rows)
        chart.add_data(Reference(ws, min_col=first_col, max_col=last_col, min_row=2, max_row=last_row), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=first_row, max_row=last_row))
        ws.add_chart(chart, f"A{ws.max_row + 3}")
    path = _save_path(stem, "pivot")
    wb.save(path)
    return path


# ==================================================================== compare
def _norm_key(series):
    """Keys that look alike match: ' A-01 ' = 'a-01', and 7 = 7.0 = '007' only if both are plain numbers."""
    pd = A._pd()
    text = series.astype(str).str.strip()
    numbers = pd.to_numeric(text, errors="coerce")
    if numbers.notna().mean() > 0.95:
        return numbers.map(lambda v: "" if v != v else (str(int(v)) if float(v).is_integer() else str(v)))
    return text.str.lower()


def _diff_mask(sa, sb):
    """True where two aligned columns differ. Numbers compare as numbers, text ignores case and spaces."""
    na, nb = A._numeric(sa), A._numeric(sb)
    numeric = na.notna() & nb.notna()
    both_empty = sa.isna() & sb.isna()
    ta = sa.astype(str).str.strip().str.lower()
    tb = sb.astype(str).str.strip().str.lower()
    same = (numeric & ((na - nb).abs() < 1e-9)) | (~numeric & (ta == tb)) | both_empty
    return ~same


def compare(df_a, df_b, label_a: str, label_b: str, key: str = "", key_b: str = "", max_items: int = 10) -> str:
    pd = A._pd()
    lines = [f"Comparing {label_a} (A: {len(df_a)} rows) with {label_b} (B: {len(df_b)} rows)"]
    cols_a = {str(c).strip().lower(): c for c in df_a.columns}
    cols_b = {str(c).strip().lower(): c for c in df_b.columns}
    common = [k for k in cols_a if k in cols_b]
    only_a = [cols_a[k] for k in cols_a if k not in cols_b]
    only_b = [cols_b[k] for k in cols_b if k not in cols_a]
    if only_a:
        lines.append("Columns only in A: " + ", ".join(map(str, only_a[:12])))
    if only_b:
        lines.append("Columns only in B: " + ", ".join(map(str, only_b[:12])))
    if not common:
        lines.append("The two tables share no column names, so there is nothing to line up.")
        return "\n".join(lines)

    totals = []
    for k in common:
        if k == str(key).strip().lower() or re.search(r"(^|[\s_])(id|no|number|code)$", k):
            continue                                   # adding up ID numbers means nothing
        sa, sb = A._numeric(df_a[cols_a[k]]), A._numeric(df_b[cols_b[k]])
        if sa.notna().mean() >= 0.7 and sb.notna().mean() >= 0.7 and not A._looks_like_dates(df_a[cols_a[k]]):
            ta, tb = float(sa.sum()), float(sb.sum())
            totals.append(f"- {cols_a[k]}: total {A._num(ta)} -> {A._num(tb)} ({A._change(tb, ta)})")
    if totals:
        lines.append("Totals of the number columns (A -> B):")
        lines.extend(totals[:8])

    if key:
        ka = A._col(df_a, key)
        kb = A._col(df_b, key_b or key) if (key_b or key.strip().lower() in cols_b) else None
        if kb is None:
            raise ValueError(f"The second table has no column '{key}'. Its columns are: {', '.join(map(str, df_b.columns))}.")
        a = df_a.assign(__k=_norm_key(df_a[ka])).dropna(subset=["__k"])
        b = df_b.assign(__k=_norm_key(df_b[kb])).dropna(subset=["__k"])
        a, b = a[a["__k"] != ""], b[b["__k"] != ""]
        dup_a, dup_b = int(a["__k"].duplicated().sum()), int(b["__k"].duplicated().sum())
        if dup_a or dup_b:
            lines.append(f"Careful: '{ka}' repeats ({dup_a} repeats in A, {dup_b} in B); only the first row of each is compared.")
        a, b = a.drop_duplicates("__k").set_index("__k"), b.drop_duplicates("__k").set_index("__k")
        removed = [k for k in a.index if k not in b.index]
        added = [k for k in b.index if k not in a.index]
        both = [k for k in a.index if k in b.index]
        lines.append(f"Matched by '{ka}': {len(both)} in both, {len(removed)} only in A (removed), {len(added)} only in B (new).")
        if removed:
            lines.append("Removed: " + ", ".join(str(a.loc[k, ka]) for k in removed[:max_items]) + (" ..." if len(removed) > max_items else ""))
        if added:
            lines.append("New: " + ", ".join(str(b.loc[k, kb]) for k in added[:max_items]) + (" ..." if len(added) > max_items else ""))
        shared = a.loc[both]
        other = b.loc[both]
        changes, per_column = [], {}
        any_change = A._pd().Series(False, index=shared.index)
        for name in common:
            ca, cb = cols_a[name], cols_b[name]
            if ca == ka:
                continue
            mask = _diff_mask(shared[ca], other[cb])
            if mask.any():
                per_column[str(ca)] = int(mask.sum())
                any_change |= mask
                for k in list(mask[mask].index)[: max(0, max_items - len(changes))]:
                    va, vb = shared.at[k, ca], other.at[k, cb]
                    changes.append(f"- {shared.at[k, ka]}: {ca} {'(empty)' if va != va else va} -> {'(empty)' if vb != vb else vb}")
        changed_rows = int(any_change.sum())
        lines.append(f"Changed values: {changed_rows} of {len(both)} matched rows differ.")
        if per_column:
            lines.append("Changes per column: " + ", ".join(f"{c} ({n})" for c, n in sorted(per_column.items(), key=lambda x: -x[1])[:8]))
        lines.extend(changes)
        if changed_rows > len(changes):
            lines.append(f"... and {changed_rows - len(changes)} more changed rows")
    else:
        use_a = [cols_a[k] for k in common]
        use_b = [cols_b[k] for k in common]

        def rows_of(frame, cols):
            return frame[cols].astype(str).apply(lambda col: col.str.strip().str.lower()).agg("|".join, axis=1)

        ra, rb = rows_of(df_a, use_a), rows_of(df_b, use_b)
        from collections import Counter
        ca, cb = Counter(ra), Counter(rb)
        gone = ca - cb
        new = cb - ca
        lines.append(f"Whole rows: {sum((ca & cb).values())} identical, {sum(gone.values())} only in A, {sum(new.values())} only in B.")
        for title, bag, source in (("Only in A", gone, ra), ("Only in B", new, rb)):
            examples = [k for k in bag][:3]
            if examples:
                lines.append(f"{title} (examples): " + " || ".join(k.replace("|", " | ")[:90] for k in examples))
        lines.append("Tip: tell me a key column (like an ID or name) and I'll show exactly which cells changed.")
    return "\n".join(lines)[:MAX_OUT]


# ======================================================================= trend
_PERIOD_FREQ = {"year": "Y", "quarter": "Q", "month": "M", "week": "W", "day": "D"}
_LAG = {"year": 1, "quarter": 4, "month": 12, "week": 52, "day": 7}


def _label(p, period: str) -> str:
    if period == "year":
        return str(p.year)
    if period == "quarter":
        return f"{p.year}-Q{p.quarter}"
    if period == "month":
        return p.strftime("%Y-%m")
    if period == "week":
        return p.start_time.strftime("%G-W%V")
    return p.strftime("%Y-%m-%d")


def trend(df, value: str, date_col: str = "", period: str = "month", how: str = "sum", forecast: int = 3) -> str:
    pd, np = A._pd(), _np()
    period = (period or "month").lower()
    if period not in A.PERIODS:
        raise ValueError(f"'period' must be one of: {', '.join(A.PERIODS)}.")
    how = (how or "sum").lower()
    if date_col:
        dcol = A._col(df, date_col)
    else:
        found = [c for c in df.columns if A._looks_like_dates(df[c])]
        if not found:
            raise ValueError(f"I need a date column for a trend and found none. The columns are: {', '.join(map(str, df.columns))}.")
        dcol = found[0]
    g = A.aggregate(df, value, dcol, how, period)
    if not g.is_date:
        raise ValueError(f"'{dcol}' doesn't look like dates.")
    dt = A._dates(df[dcol]).dropna()
    freq = _PERIOD_FREQ[period]
    first_p, last_p = dt.min().to_period(freq), dt.max().to_period(freq)
    notes = []
    additive = how in ("sum", "count")
    slack = {"year": 14, "quarter": 10, "month": 5, "week": 2}.get(period, 0)
    if additive and slack and (last_p.end_time.normalize() - dt.max().normalize()).days > slack:
        notes.append(f"{_label(last_p, period)} is not finished yet (data ends {dt.max():%Y-%m-%d}), so I left it out of the trend")
        last_p = last_p - 1
    full = pd.period_range(first_p, last_p, freq=freq)
    labels = [_label(p, period) for p in full]
    raw = g.table.iloc[:, 0].astype(float)
    series = raw.reindex(labels)
    if series.notna().sum() == 0:
        raise ValueError("I couldn't line the dates up into periods. Try period='month' or 'year'.")
    gaps = int(series.isna().sum())
    if additive:
        series = series.fillna(0.0)
    else:
        series = series.interpolate(limit_direction="both")
    if gaps:
        notes.append(f"{gaps} {period}(s) had no rows" + (" and count as 0" if additive else " and were filled in between their neighbours"))
    n = len(series)
    if n < 3:
        raise ValueError(f"I only have {n} {period}(s) of data; I need at least 3 to see a trend.")
    y = series.to_numpy(dtype=float)
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fit = slope * x + intercept
    ss_res, ss_tot = float(((y - fit) ** 2).sum()), float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0

    name = g.value or "rows"
    lines = [f"Trend of {A.HOW_NAMES[how].lower()} of {name} per {period}, {labels[0]} to {labels[-1]} ({n} {period}s)"]
    shown = list(zip(labels, y))[-12:]
    lines.append("Latest: " + "; ".join(f"{l} {A._num(v)}" for l, v in shown))
    last, prev = y[-1], y[-2]
    lines.append(f"Last {period}: {A._num(last)} vs {A._num(prev)} before it ({A._change(last, prev)})")
    lag = _LAG[period]
    if lag > 1 and n > lag:
        back = y[-1 - lag]
        same = "the same weekday a week earlier" if period == "day" else f"the same {period} a year ago"
        lines.append(f"Compared with {same}: {A._num(back)} -> {A._num(last)} ({A._change(last, back)})")
    positive = (y > 0).all()
    if positive and n > 1:
        per = (y[-1] / y[0]) ** (1 / (n - 1)) - 1
        lines.append(f"Average growth: {per * 100:+.1f}% per {period} (compounded, first to last)")
    lines.append(f"Straight-line trend: {slope:+,.1f} per {period} on average (fit quality R2 {r2:.2f})")
    best, worst = int(np.argmax(y)), int(np.argmin(y))
    lines.append(f"Best {period}: {labels[best]} ({A._num(y[best])}); weakest: {labels[worst]} ({A._num(y[worst])})")

    k = max(0, min(int(forecast or 0), 12))
    if k:
        if n < 6 or r2 < 0.3:
            reason = f"only {n} {period}s of history" if n < 6 else f"the data doesn't follow a straight line (R2 {r2:.2f})"
            lines.append(f"Forecast: shaky, because {reason}. If you still want a guess:")
        else:
            lines.append(f"Forecast (continuing the straight line; not a promise, seasons and events are ignored):")
        future = []
        for i in range(1, k + 1):
            guess = slope * (n - 1 + i) + intercept
            if (y >= 0).all():
                guess = max(0.0, guess)
            future.append(f"{_label(last_p + i, period)} ~{A._num(guess)}")
        lines.append("; ".join(future))
    lines.extend(notes)
    return "\n".join(lines)[:MAX_OUT]


# ====================================================================== relate
def relate(df, x: str, y: str, at: str = "") -> str:
    pd, np = A._pd(), _np()
    xc, yc = A._col(df, x), A._col(df, y)
    if xc == yc:
        raise ValueError("Pick two different columns.")
    frame = pd.DataFrame({"x": A._numeric(df[xc]), "y": A._numeric(df[yc])}).dropna()
    n = len(frame)
    if n < 3:
        raise ValueError(f"Only {n} rows have numbers in both '{xc}' and '{yc}'; I need at least 3.")
    if frame["x"].nunique() < 2:
        raise ValueError(f"'{xc}' has the same number in every row, so it can't explain '{yc}'.")
    xs, ys = frame["x"].to_numpy(float), frame["y"].to_numpy(float)
    slope, intercept = np.polyfit(xs, ys, 1)
    r = float(np.corrcoef(xs, ys)[0, 1]) if ys.std() else 0.0
    rho = float(frame["x"].rank().corr(frame["y"].rank())) if ys.std() else 0.0
    r2 = r * r
    t = abs(r) * ((n - 2) / max(1e-12, 1 - r2)) ** 0.5 if n > 2 else 0.0
    strength = "very strong" if abs(r) >= 0.8 else "strong" if abs(r) >= 0.6 else "moderate" if abs(r) >= 0.4 else "weak" if abs(r) >= 0.2 else "almost no"
    lines = [
        f"How {xc} relates to {yc} ({n} rows used)",
        f"Each +1 in {xc} goes with {slope:+,.3f} in {yc}  (line: {yc} = {slope:,.3f} x {xc} {'+' if intercept >= 0 else '-'} {abs(intercept):,.2f})",
        (f"Correlation {r:+.2f} - almost no link" if abs(r) < 0.2 else
         f"Correlation {r:+.2f} - a {strength} {'upward' if r > 0 else 'downward'} link")
        + f"; {xc} explains about {r2 * 100:.0f}% of the ups and downs in {yc}.",
    ]
    if n >= 10 and t > 2:
        lines.append("With this many rows that link is unlikely to be luck.")
    elif n < 10:
        lines.append(f"Only {n} rows, so treat this as a hint, not proof.")
    else:
        lines.append("The link is small enough that it could be chance.")
    if abs(r - rho) > 0.25:
        lines.append(f"Warning: a few extreme rows pull this line (rank correlation is {rho:+.2f}); look for outliers.")
    for piece in [p.strip() for p in str(at or "").split(",") if p.strip()][:4]:
        try:
            value = float(piece.replace(" ", ""))
        except ValueError:
            continue
        outside = value < xs.min() or value > xs.max()
        lines.append(f"If {xc} = {A._num(value)} then {yc} is about {A._num(slope * value + intercept)}" +
                     (f" (outside the {A._num(xs.min())} to {A._num(xs.max())} I have data for, so less reliable)" if outside else ""))
    lines.append("A link is not proof that one causes the other.")
    return "\n".join(lines)[:MAX_OUT]


# ===================================================================== cleanup
def _has_leading_zero(strings) -> bool:
    """IDs and ZIP codes like 00123 must stay text: as numbers they would lose their zeros."""
    return bool(strings.str.match(r"^0\d").any())


def _normal(text: str) -> str:
    return re.sub(r"[\W_]+", " ", str(text).lower()).strip()


def _date_styles(strings) -> dict[str, int]:
    styles = {"2025-03-31": 0, "31/03/2025": 0, "Mar 31, 2025": 0}
    for s in strings:
        s = str(s).strip()
        if re.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", s):
            styles["2025-03-31"] += 1
        elif re.match(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", s):
            styles["31/03/2025"] += 1
        elif re.search(r"[A-Za-z]{3}", s):
            styles["Mar 31, 2025"] += 1
    return {k: v for k, v in styles.items() if v}


def find_issues(df) -> list[str]:
    pd = A._pd()
    issues: list[tuple[int, str]] = []        # (importance, text)
    rows = len(df)
    for c in df.columns:
        s = df[c]
        present = s.dropna()
        if present.empty:
            issues.append((1, f"'{c}' is completely empty - you can probably delete the column."))
            continue
        if len(present) < 0.5 * rows and rows >= 10:
            issues.append((1, f"'{c}' is {100 - len(present) * 100 // rows}% empty."))
        if not _is_text_column(s):
            if present.nunique() == 1 and rows > 5:
                issues.append((1, f"'{c}' has the same value in every row."))
            continue
        text = present.astype(str)
        stripped = text.str.strip()
        messy = int((text != stripped).sum() + stripped.str.contains(r"\s{2,}").sum())
        if messy:
            issues.append((2, f"'{c}': {messy} cell(s) have extra spaces (they stop matching: 'North' vs 'North ')."))
        fake = int(stripped.str.lower().isin(PLACEHOLDERS).sum())
        if fake:
            issues.append((4, f"'{c}': {fake} cell(s) say N/A, '-', none or similar instead of being empty; they break totals and counts."))
        numeric = A._numeric(stripped)
        is_dates = A._looks_like_dates(s)
        if not is_dates and numeric.notna().mean() >= 0.8 and not _has_leading_zero(stripped):
            odd = stripped[numeric.isna() & ~stripped.str.lower().isin(PLACEHOLDERS)]
            formatted = stripped[stripped.str.contains(r"[,$₱€£%()\s]", regex=True) & numeric.notna()]
            if len(formatted) or len(odd):          # plain digits are fine (a CSV file is all text); symbols and words are not
                example = formatted.iloc[0] if len(formatted) else stripped.iloc[0]
                extra = f" ({len(odd)} cells are words, e.g. '{odd.iloc[0]}')" if len(odd) else ""
                issues.append((5, f"'{c}' stores numbers as text (e.g. '{example}'){extra}, so totals and charts may ignore them."))
            continue
        if is_dates:
            parsed = A._dates(s)
            bad = s.notna() & parsed.isna()
            if bad.any():
                issues.append((5, f"'{c}': {int(bad.sum())} values aren't real dates (e.g. '{s[bad].iloc[0]}')."))
            styles = _date_styles(v for v in present if isinstance(v, str))
            if len(styles) > 1:
                issues.append((3, f"'{c}': dates are written in {len(styles)} styles ({', '.join(f'{k} x{v}' for k, v in styles.items())}); "
                                  "day/month vs month/day can silently swap."))
            continue
        unique = stripped.nunique()
        if 1 < unique <= 300 and numeric.notna().mean() < 0.5:
            groups: dict[str, list[str]] = {}
            for v in stripped.unique():
                groups.setdefault(_normal(v), []).append(v)
            variants = [vs for vs in groups.values() if len(vs) > 1]
            if variants:
                shown = "; ".join(" / ".join(f"'{v}'" for v in vs[:4]) for vs in variants[:3])
                issues.append((4, f"'{c}': {len(variants)} category(ies) are spelled more than one way: {shown}."))
            counts = stripped.value_counts()
            names = [v for v in counts.index if _normal(v)]
            typos = []
            for rare in names:
                if counts[rare] > 3:
                    continue
                near = [m for m in get_close_matches(rare, [v for v in names if v != rare and counts[v] >= 5 * counts[rare]], n=1, cutoff=0.86)
                        if _normal(m) != _normal(rare)]
                if near:
                    typos.append(f"'{rare}' ({counts[rare]}) looks like '{near[0]}' ({counts[near[0]]})")
            if typos:
                issues.append((3, f"'{c}': possible typos: " + "; ".join(typos[:4]) + "."))
    dups = int(df.duplicated().sum()) if rows else 0
    if dups:
        issues.append((6, f"{dups} row{'s are' if dups != 1 else ' is'} an exact copy of another row (counted twice in totals)."))
    issues.sort(key=lambda p: -p[0])
    return [text for _, text in issues]


def cleaned_copy(df):
    """Returns (clean table, list of what was fixed). The original table is not changed."""
    pd = A._pd()
    out = df.copy()
    done: list[str] = []
    for c in list(out.columns):
        s = out[c]
        if not _is_text_column(s):
            continue
        was_text = s.where(s.isna(), s.astype(str))
        stripped = was_text.str.strip().str.replace(r"\s{2,}", " ", regex=True)
        trimmed = int((was_text.notna() & (was_text != stripped)).sum())
        blanks = stripped.where(stripped.isna(), stripped.str.lower()).isin(PLACEHOLDERS) | (stripped == "")
        stripped = stripped.mask(blanks & stripped.notna())
        if trimmed:
            done.append(f"{c}: trimmed spaces in {trimmed} cells")
        n_blank = int((blanks & was_text.notna()).sum())
        if n_blank:
            done.append(f"{c}: turned {n_blank} 'N/A'-style cells into real blanks")
        present = stripped.dropna()
        numeric = A._numeric(stripped)
        if len(present) and A._looks_like_dates(stripped):
            parsed = A._dates(stripped)
            if parsed.notna().sum() >= 0.9 * len(present):
                out[c] = parsed
                done.append(f"{c}: dates made consistent")
                continue
        if (len(present) and numeric.notna().sum() >= 0.8 * len(present) and not A._looks_like_dates(stripped)
                and not _has_leading_zero(present)):
            out[c] = numeric
            if present.str.contains(r"[,$₱€£%()\s]", regex=True).any():
                done.append(f"{c}: text like '{present[present.str.contains(r'[,$₱€£%()\s]', regex=True)].iloc[0]}' turned into numbers")
            continue
        if 1 < present.nunique() <= 300:
            counts = present.value_counts()
            best: dict[str, str] = {}
            for v in counts.index:                    # biggest first, so the most common spelling wins
                best.setdefault(_normal(v), v)
            mapping = {v: best[_normal(v)] for v in counts.index if best[_normal(v)] != v}
            if mapping:
                stripped = stripped.replace(mapping)
                done.append(f"{c}: {len(mapping)} spelling variant(s) merged (" + ", ".join(f"'{k}'->'{v}'" for k, v in list(mapping.items())[:3]) + ")")
        out[c] = stripped
    n_before = len(out)
    out = out.drop_duplicates()
    if len(out) < n_before:
        done.append(f"removed {n_before - len(out)} duplicate rows")
    return out.reset_index(drop=True), done


def cleanup_report(df, label: str, save: bool = False, stem: str = "data"):
    """(text, saved path or None). Saves only a NEW file; the original is never touched."""
    issues = find_issues(df)
    lines = [f"Data check of {label}: {len(df)} rows, {df.shape[1]} columns"]
    if not issues:
        lines.append("Looks clean: no obvious problems found (spaces, text numbers, dates, spelling, duplicates).")
    else:
        lines.append(f"{len(issues)} thing(s) to look at, most important first:")
        lines.extend(f"- {text}" for text in issues[:12])
        if len(issues) > 12:
            lines.append(f"... and {len(issues) - 12} smaller ones")
    path = None
    if save:
        clean, done = cleaned_copy(df)
        if done:
            path = _save_path(stem, "clean")
            _write_xlsx(clean, path, "Clean data")
            lines.append("Cleaned copy made (your original is untouched): " + "; ".join(done[:8]))
        else:
            lines.append("There was nothing I could fix automatically, so I made no copy.")
    return "\n".join(lines)[:MAX_OUT], path


# ======================================================================== join
def join(df_a, df_b, key: str, key_b: str = "", how: str = "inner", label_a: str = "A", label_b: str = "B"):
    """(joined table, summary text)."""
    how = (how or "inner").lower()
    if how not in ("inner", "left", "outer"):
        raise ValueError("'how' must be inner (only matches), left (everything from the first file) or outer (everything).")
    ka = A._col(df_a, key)
    kb = A._col(df_b, key_b or key)
    a = df_a.copy()
    b = df_b.copy()
    a["__k"], b["__k"] = _norm_key(a[ka]), _norm_key(b[kb])
    a, b = a[a["__k"] != ""], b[b["__k"] != ""]
    keys_a, keys_b = set(a["__k"]), set(b["__k"])
    dup_b = int(b["__k"].duplicated().sum())
    dup_a = int(a["__k"].duplicated().sum())
    b["__kb"] = b[kb]
    b = b.drop(columns=[kb])
    merged = a.merge(b, on="__k", how=how, suffixes=("", f" ({label_b})"))
    merged[ka] = merged[ka].where(merged[ka].notna(), merged["__kb"])      # rows only in B still show their key
    merged = merged.drop(columns=["__k", "__kb"])
    lines = [
        f"Joined {label_a} ({len(a)} rows) with {label_b} ({len(b)} rows) on '{ka}'" + (f" = '{kb}'" if kb != ka else ""),
        f"Matching keys: {len(keys_a & keys_b)}; only in {label_a}: {len(keys_a - keys_b)}; only in {label_b}: {len(keys_b - keys_a)}.",
        f"Result ({how} join): {len(merged)} rows, {merged.shape[1]} columns.",
    ]
    if dup_b:
        lines.append(f"Careful: '{kb}' repeats {dup_b} time(s) in {label_b}, so rows from {label_a} were repeated to match each one.")
    if how == "inner" and len(keys_a - keys_b) > 0.3 * max(1, len(keys_a)):
        lines.append(f"{len(keys_a - keys_b)} keys from {label_a} found no match - check that the key is spelled the same way in both files.")
    return merged, "\n".join(lines)


# ==================================================================== runners
def _int(value, default: int, low: int = 0) -> int:
    try:
        return max(low, int(value))
    except (TypeError, ValueError):
        return default


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "1", "y")


def run_pivot(path: Path, **a):
    """(text, saved Excel path or None)"""
    df, notes = A.prepare(path, a.get("sheet", ""), a.get("filter_column", ""), a.get("filter_value", ""))
    res = pivot_table(df, a.get("rows", ""), a.get("columns", ""), a.get("value", ""), a.get("how", "sum"),
                      a.get("period", ""), _int(a.get("top"), 15, 1), _truthy(a.get("percent")))
    text = res.text + ("\n" + "; ".join(notes) if notes else "")
    return text, (save_pivot(res, path.stem) if _truthy(a.get("save")) else None)


def run_compare(path: Path, path2: Path, **a) -> str:
    df_a, _ = A.prepare(path, a.get("sheet", ""))
    df_b, _ = A.prepare(path2, a.get("sheet2", ""))
    la = path.name + (f" [{a['sheet']}]" if a.get("sheet") else "")
    lb = path2.name + (f" [{a['sheet2']}]" if a.get("sheet2") else "")
    return compare(df_a, df_b, la, lb, a.get("key", ""), a.get("key2", ""))


def run_trend(path: Path, **a) -> str:
    df, notes = A.prepare(path, a.get("sheet", ""), a.get("filter_column", ""), a.get("filter_value", ""))
    text = trend(df, a.get("value", ""), a.get("date", ""), a.get("period", "month"), a.get("how", "sum"),
                 _int(a.get("forecast"), 3))
    return text + ("\n(" + "; ".join(notes) + ")" if notes else "")


def run_relate(path: Path, **a) -> str:
    df, notes = A.prepare(path, a.get("sheet", ""), a.get("filter_column", ""), a.get("filter_value", ""))
    return relate(df, a.get("x", ""), a.get("y", ""), a.get("at", ""))


def run_cleanup(path: Path, **a):
    """(text, saved clean copy path or None)"""
    df, _ = A.prepare(path, a.get("sheet", ""))
    return cleanup_report(df, path.name, _truthy(a.get("save")), path.stem)


def run_join(path: Path, path2: Path, **a):
    """(text, saved Excel path)"""
    df_a, _ = A.prepare(path, a.get("sheet", ""))
    df_b, _ = A.prepare(path2, a.get("sheet2", ""))
    merged, text = join(df_a, df_b, a.get("key", ""), a.get("key2", ""), a.get("how", "inner"), path.stem, path2.stem)
    if merged.empty:
        raise ValueError(text + "\nNo rows came out, so I saved nothing.")
    out = _save_path(f"{path.stem}+{path2.stem}", "joined")
    _write_xlsx(merged, out, "Joined")
    return text, out
