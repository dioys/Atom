"""checks.py - Step 6: Atom looks for problems in your spreadsheets.

Everything here runs on your computer with plain rules (no AI, no internet),
so your files are not sent anywhere just to be checked. Atom only reports;
he never changes a file.

  analyze(path)  ->  Findings(checks=[...], soon=[...])

  checks: formula errors (#REF!, #DIV/0!), a formula that differs from its
          neighbours, a typed number in the middle of a column of formulas,
          blank cells in an otherwise full column, duplicate rows
  soon:   items due within the next few days that are not done yet
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import reports
from reports import DONE_WORDS, DUE_HINTS, STATUS_HINTS

EXCEL = {".xlsx", ".xlsm"}
TABLES = {".xlsx", ".xlsm", ".csv", ".tsv"}
ERROR_VALUES = {"#REF!", "#DIV/0!", "#N/A", "#VALUE!", "#NAME?", "#NUM!", "#NULL!"}
OPTIONAL_COLUMNS = ("note", "comment", "remark", "description", "detail", "link", "url")
AGGREGATES = ("SUM(", "SUBTOTAL(", "AVERAGE(", "COUNT(", "MIN(", "MAX(", "AGGREGATE(")
MAX_PER_FILE = 6
MAX_FORMULA_ROWS = 3000

# a cell reference like B7 or $B$7 (not inside a function name such as LOG10( )
_REF = re.compile(r"(?<![A-Za-z0-9_.])(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\d(A-Za-z_])")
_QUOTED = re.compile(r'"[^"]*"')


@dataclass
class Findings:
    checks: list[str] = field(default_factory=list)
    soon: list[str] = field(default_factory=list)


# ------------------------------------------------------------- helpers
def _column_number(letters: str) -> int:
    number = 0
    for ch in letters:
        number = number * 26 + (ord(ch) - 64)
    return number


def _column_letters(number: int) -> str:
    letters = ""
    while number > 0:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def relative_form(formula: str, row: int, col: int) -> str:
    """Write a formula so that references are relative to its own cell.
    '=B2*C2' in row 2 and '=B3*C3' in row 3 both become '=B[0]*C[0]'-like text,
    so two formulas that do the same job look the same."""
    text = _QUOTED.sub('""', formula.upper())

    def swap(match: re.Match) -> str:
        col_abs, letters, row_abs, number = match.groups()
        c = f"C{_column_number(letters)}" if col_abs else f"C[{_column_number(letters) - col}]"
        r = f"R{number}" if row_abs else f"R[{int(number) - row}]"
        return r + c

    return _REF.sub(swap, text)


def _is_formula(value) -> bool:
    return isinstance(value, str) and value.startswith("=") and len(value) > 1


def _is_aggregate(formula: str) -> bool:
    upper = formula.upper().lstrip("=")
    return any(upper.startswith(name) for name in AGGREGATES)


# ------------------------------------------------------------- formulas
def _formula_findings(path: Path) -> list[str]:
    import openpyxl

    found: list[str] = []
    formulas = openpyxl.load_workbook(path, read_only=True, data_only=False)
    values = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in formulas.worksheets[: reports.MAX_SHEETS]:
            cached = values[sheet.title]
            grid: dict[tuple[int, int], object] = {}
            for r, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if r > MAX_FORMULA_ROWS:
                    break
                for c, value in enumerate(row, start=1):
                    if value is not None:
                        grid[(r, c)] = value

            # 1. errors Excel already shows, or references to deleted cells
            shown = 0
            for r, row in enumerate(cached.iter_rows(values_only=True), start=1):
                if r > MAX_FORMULA_ROWS:
                    break
                for c, value in enumerate(row, start=1):
                    if isinstance(value, str) and value.strip() in ERROR_VALUES and shown < 3:
                        found.append(f"{sheet.title}!{_column_letters(c)}{r} shows {value.strip()}")
                        shown += 1
            for (r, c), value in sorted(grid.items()):
                if _is_formula(value) and "#REF!" in value.upper() and shown < 3:
                    found.append(f"{sheet.title}!{_column_letters(c)}{r} points at a deleted cell (#REF!)")
                    shown += 1

            # 2. odd one out inside a column of formulas
            columns: dict[int, list[int]] = {}
            for (r, c), value in grid.items():
                if _is_formula(value):
                    columns.setdefault(c, []).append(r)
            for c, rows in columns.items():
                rows.sort()
                if len(rows) < 4:
                    continue
                forms = {r: relative_form(grid[(r, c)], r, c) for r in rows}
                common, count = Counter(forms.values()).most_common(1)[0]
                if count < max(3, 0.6 * len(rows)):
                    continue  # a mixed column: nothing is clearly "the odd one"
                for r in rows:
                    formula = grid[(r, c)]
                    if forms[r] != common and not _is_aggregate(formula) and "#REF!" not in formula.upper():
                        found.append(
                            f"{sheet.title}!{_column_letters(c)}{r} has a different formula "
                            f"from the rest of column {_column_letters(c)}"
                        )
                for r in range(rows[0] + 1, rows[-1]):
                    value = grid.get((r, c))
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        found.append(
                            f"{sheet.title}!{_column_letters(c)}{r} is a typed number "
                            f"in a column of formulas"
                        )
    finally:
        formulas.close()
        values.close()
    return found


# ------------------------------------------------------------- table data
def _label(row: list, skip: set[int]) -> str:
    parts = [str(c).strip() for k, c in enumerate(row) if k not in skip and not reports._is_blank(c)]
    return " / ".join(parts[:2]) or "a row"


def _table_findings(path: Path) -> list[str]:
    found: list[str] = []
    for sheet_name, rows in reports._read_tables(path):
        names, data = reports._clean(rows)
        if not names or len(data) < 5:
            continue
        where = f'"{sheet_name}"' if sheet_name != "(whole file)" else path.name

        # blank cells in a column that is otherwise nearly full
        for i, name in enumerate(names):
            if any(word in name.lower() for word in OPTIONAL_COLUMNS):
                continue
            filled = [not reports._is_blank(row[i]) for row in data]
            blanks = filled.count(False)
            if blanks and sum(filled) >= 0.8 * len(data):
                example = next(_label(row, {i}) for row, ok in zip(data, filled) if not ok)
                found.append(
                    f"{where} has {blanks} blank cell{'s' if blanks != 1 else ''} in "
                    f"'{name}' (for example the row {example})"
                )

        # rows that appear twice
        seen = Counter(
            tuple(str(c).strip().lower() for c in row)
            for row in data
            if sum(not reports._is_blank(c) for c in row) >= 3
        )
        repeats = [(key, n) for key, n in seen.items() if n > 1]
        if repeats:
            key = repeats[0][0]
            example = " / ".join([k for k in key if k][:2])[:40]
            extra = sum(n - 1 for _, n in repeats)
            found.append(f"{where} has {extra} duplicate row{'s' if extra != 1 else ''}, like {example}")
    return found


def _due_soon(path: Path, today: date, days: int) -> list[str]:
    last = today + timedelta(days=days)
    out: list[str] = []
    for _sheet, rows in reports._read_tables(path):
        names, data = reports._clean(rows)
        if not names or not data:
            continue
        status_i = reports._find_column(names, STATUS_HINTS)
        due_i = reports._find_column(names, DUE_HINTS)
        if status_i is None or due_i is None:
            continue
        for row in data:
            due = reports._to_date(row[due_i])
            status = "" if reports._is_blank(row[status_i]) else str(row[status_i]).strip().lower()
            if due and today <= due <= last and status not in DONE_WORDS:
                when = "today" if due == today else due.strftime("%b %d").replace(" 0", " ")
                out.append(f"{_label(row, {status_i, due_i})} ({when})")
    return out


# ------------------------------------------------------------- entry point
def analyze(path: Path, today: date | None = None, days: int = 7) -> Findings:
    """Problems and soon-due items in one spreadsheet. Never raises: a file
    that can't be read simply has no findings."""
    path = Path(path)
    today = today or date.today()
    result = Findings()
    if path.suffix.lower() not in TABLES:
        return result
    if path.suffix.lower() in EXCEL:
        try:
            result.checks.extend(_formula_findings(path))
        except Exception:
            pass
    try:
        result.checks.extend(_table_findings(path))
    except Exception:
        pass
    try:
        result.soon.extend(_due_soon(path, today, days))
    except Exception:
        pass
    result.checks = result.checks[:MAX_PER_FILE]
    return result
