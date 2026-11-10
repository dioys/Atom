"""reports.py - Step 4: turn your spreadsheets into real numbers, and write reports.

No window code and no AI code in here. The AI is bad at counting rows, so
Atom does the counting HERE and the AI only explains the result:

  summarize_table(path)  - for an Excel/CSV file: row counts, how many tasks
                           are Done / In progress, totals, date ranges, and
                           which items are past their due date and not done.
  write_report(title, text) - saves a report as a Word document.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import config

DONE_WORDS = {"done", "complete", "completed", "closed", "finished", "resolved", "delivered", "100%"}
DUE_HINTS = ("due", "deadline", "target", "end date", "finish")
STATUS_HINTS = ("status", "state", "stage", "progress")
MAX_ROWS = 5000        # rows read per sheet
MAX_SHEETS = 5
MAX_CHARS = 3000       # the summary handed to the AI is cut to this size
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y", "%Y/%m/%d")


# ------------------------------------------------------------- reading
def _read_tables(path: Path) -> list[tuple[str, list[list]]]:
    """Return [(sheet name, rows)] for an Excel or CSV file."""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        delimiter = "\t" if suffix == ".tsv" else ","
        rows = [r for _, r in zip(range(MAX_ROWS + 1), csv.reader(text.splitlines(), delimiter=delimiter))]
        return [("(whole file)", rows)]
    if suffix in (".xlsx", ".xlsm"):
        import openpyxl

        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
        tables = []
        for sheet in workbook.worksheets[:MAX_SHEETS]:
            rows = []
            for i, row in enumerate(sheet.iter_rows(values_only=True)):
                if i > MAX_ROWS:
                    break
                rows.append(list(row))
            tables.append((sheet.title, rows))
        workbook.close()
        return tables
    raise ValueError("table_summary only works on Excel (.xlsx) and CSV files. Use read_file for other types.")


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _clean(rows: list[list]) -> tuple[list[str], list[list]]:
    """Find the header row and return (column names, data rows)."""
    rows = [r for r in rows if any(not _is_blank(c) for c in r)]
    if not rows:
        return [], []
    start = next((i for i, r in enumerate(rows) if sum(not _is_blank(c) for c in r) >= 2), 0)
    header_row, data = rows[start], rows[start + 1 :]
    width = len(header_row)
    names = [str(c).strip() if not _is_blank(c) else f"Column {i + 1}" for i, c in enumerate(header_row)]
    data = [(list(r) + [None] * width)[:width] for r in data]
    return names, data


# ------------------------------------------------------------- values
def _to_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _to_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "").replace("₱", "").rstrip("%")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _fmt(number: float) -> str:
    return f"{number:,.0f}" if abs(number) >= 100 or number == int(number) else f"{number:,.2f}"


def _find_column(names: list[str], hints: tuple[str, ...]) -> int | None:
    for hint in hints:
        for i, name in enumerate(names):
            if hint in name.lower():
                return i
    return None


def _describe_column(name: str, values: list, today: date, is_due: bool) -> str:
    present = [v for v in values if not _is_blank(v)]
    if not present:
        return f"- {name}: (empty)"
    share = len(present)

    dates = [_to_date(v) for v in present]
    if sum(d is not None for d in dates) >= 0.7 * share:
        dates = [d for d in dates if d]
        text = f"- {name}: {min(dates)} to {max(dates)}"
        if is_due:
            late = sum(d < today for d in dates)
            text += f"; {late} before today ({today})"
        return text

    numbers = [_to_number(v) for v in present]
    if sum(n is not None for n in numbers) >= 0.7 * share:
        numbers = [n for n in numbers if n is not None]
        return (
            f"- {name}: total {_fmt(sum(numbers))}, average {_fmt(sum(numbers) / len(numbers))}, "
            f"lowest {_fmt(min(numbers))}, highest {_fmt(max(numbers))} ({len(numbers)} values)"
        )

    counts = Counter(str(v).strip() for v in present)
    # long columns where every value is different (task names, ids) are not worth counting
    looks_like_status = any(hint in name.lower() for hint in STATUS_HINTS)
    all_different = len(counts) == len(present) and len(present) >= 8 and not looks_like_status
    if len(counts) <= 12 and not all_different:
        parts = ", ".join(f"{label} ({n})" for label, n in counts.most_common())
        return f"- {name}: {parts}"
    sample = "; ".join(list(counts)[:3])
    return f"- {name}: {len(counts)} different values, e.g. {sample}"


# ------------------------------------------------------------- overdue
def _late_rows(names: list[str], data: list[list], today: date):
    """Rows whose due date has passed and whose status is not done.
    Returns [(what it is, due date, status)], or None if the sheet has no
    status column or no due-date column."""
    status_i = _find_column(names, STATUS_HINTS)
    due_i = _find_column(names, DUE_HINTS)
    if status_i is None or due_i is None:
        return None
    late = []
    for row in data:
        due = _to_date(row[due_i])
        status = "" if _is_blank(row[status_i]) else str(row[status_i]).strip()
        if due and due < today and status.lower() not in DONE_WORDS:
            label = [str(c).strip() for k, c in enumerate(row) if k not in (status_i, due_i) and not _is_blank(c)]
            late.append((" / ".join(label[:2]) or "row", due, status))
    return late


def overdue_items(path: Path, today: date | None = None) -> list[str]:
    """Short names of everything past due and not done in a spreadsheet.
    Never raises: a file that can't be read just has no overdue items."""
    today = today or date.today()
    found: list[str] = []
    try:
        for _sheet, rows in _read_tables(path):
            names, data = _clean(rows)
            late = _late_rows(names, data, today) if names and data else None
            found.extend(label for label, _due, _status in late or [])
    except Exception:
        return []
    return found


# ------------------------------------------------------------- summary
def summarize_table(path: Path, today: date | None = None) -> str:
    """Plain-text numbers about every sheet of a spreadsheet."""
    today = today or date.today()
    blocks = [f"File: {path.name} (numbers counted by Atom, as of {today})"]
    for sheet_name, rows in _read_tables(path):
        names, data = _clean(rows)
        if not names or not data:
            blocks.append(f'\nSheet "{sheet_name}": empty')
            continue
        due_i = _find_column(names, DUE_HINTS)
        lines = [f'\nSheet "{sheet_name}": {len(data)} rows, columns: {", ".join(names)}']
        for i, name in enumerate(names):
            lines.append(_describe_column(name, [row[i] for row in data], today, is_due=(i == due_i)))

        late = _late_rows(names, data, today)
        if late is not None:
            lines.append(f"Past due and not done: {len(late)}")
            lines.extend(f"  - {label} (due {due}, status: {status or 'none'})" for label, due, status in late[:10])
            if len(late) > 10:
                lines.append(f"  ... and {len(late) - 10} more")
        blocks.append("\n".join(lines))

    text = "\n".join(blocks)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n[cut off]"


# ------------------------------------------------------------- reports
def _add_runs(paragraph, text: str) -> None:
    """Write text into a Word paragraph, turning **bold** markers into bold."""
    for i, part in enumerate(text.split("**")):
        if part:
            paragraph.add_run(part).bold = bool(i % 2)


def write_report(title: str, content: str) -> Path:
    """Save a report as a Word document in the reports folder and return its path."""
    from docx import Document

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "report"
    path = config.REPORTS_DIR / f"{date.today():%Y-%m-%d}-{slug}.docx"
    number = 2
    while path.exists():
        path = config.REPORTS_DIR / f"{date.today():%Y-%m-%d}-{slug}-{number}.docx"
        number += 1

    doc = Document()
    doc.add_heading(title.strip() or "Report", 0)
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### "):
            doc.add_heading(line[4:], 3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], 2)
        elif line.startswith("# "):
            doc.add_heading(line[2:], 1)
        elif re.match(r"[-*•] ", line):
            _add_runs(doc.add_paragraph(style="List Bullet"), line[2:])
        elif re.match(r"\d+[.)] ", line):
            _add_runs(doc.add_paragraph(style="List Number"), re.sub(r"^\d+[.)] ", "", line))
        else:
            _add_runs(doc.add_paragraph(), line)
    doc.save(path)
    return path
