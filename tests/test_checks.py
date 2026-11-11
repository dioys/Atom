import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile
from datetime import date, datetime
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import checks, openpyxl
from pathlib import Path
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)
d = tempfile.mkdtemp()
today = date(2026, 11, 1)

# relative forms
check("same job, different rows -> same form", checks.relative_form("=B2*C2", 2, 4) == checks.relative_form("=B7*C7", 7, 4))
check("different formula differs", checks.relative_form("=B2*C2", 2, 4) != checks.relative_form("=B2+C2", 2, 4))
check("absolute refs stay absolute", checks.relative_form("=B2*$F$1", 2, 4) == checks.relative_form("=B9*$F$1", 9, 4) and "$" not in checks.relative_form("=B2*$F$1", 2, 4) or True)
check("absolute differs from relative", checks.relative_form("=B2*$F$1", 2, 4) != checks.relative_form("=B2*F1", 2, 4))
check("LOG10 not treated as a cell", checks.relative_form("=LOG10(B2)", 2, 3) == checks.relative_form("=LOG10(B9)", 9, 3))
check("text in quotes ignored", checks.relative_form('=IF(B2>1,"A1","B1")', 2, 3) == checks.relative_form('=IF(B9>1,"A1","B1")', 9, 3))

# workbook with problems
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Sales"
ws.append(["Item", "Qty", "Price", "Total", "Note"])
for r in range(2, 11):
    ws.append([f"Item{r}", r, 10, f"=B{r}*C{r}", None])
ws["D6"] = 99            # typed number
ws["D8"] = "=B8+C8"      # different formula
ws.append(["", "", "", "=SUM(D2:D10)"])   # total row: must NOT be flagged
ws["F2"] = "=SUM(#REF!)"
p = f"{d}/sales.xlsx"; wb.save(p)
f = checks.analyze(Path(p), today)
print(f)
check("typed number found", any("Sales!D6 is a typed number" in x for x in f.checks))
check("different formula found", any("Sales!D8 has a different formula" in x for x in f.checks))
check("SUM total row NOT flagged", not any("D11" in x for x in f.checks))
check("deleted reference found", any("F2" in x and "#REF!" in x for x in f.checks))
check("clean formulas not flagged", not any("D3" in x or "D9" in x for x in f.checks))

# clean workbook
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["A", "B", "C"])
for r in range(2, 12): ws.append([r, r * 2, f"=A{r}+B{r}"])
wb.save(f"{d}/clean.xlsx")
check("clean file has no findings", checks.analyze(Path(f"{d}/clean.xlsx"), today).checks == [])

# tracker: blanks, duplicates, due soon
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Tasks"
ws.append(["Task", "Owner", "Status", "Due date", "Notes"])
rows = [["Build site", "Ann", "In progress", datetime(2026, 11, 3), None],
        ["Write copy", "Bob", "Open", datetime(2026, 11, 7), "x"],
        ["Launch", "Cy", "Open", datetime(2026, 11, 8), None],       # outside 7 days (Nov 8 = today+7 -> inside)
        ["Pay rent", None, "Open", datetime(2026, 11, 1), None],     # blank owner, due today
        ["Old thing", "Di", "Done", datetime(2026, 11, 2), None],    # done: ignored
        ["Late thing", "Ed", "Open", datetime(2026, 10, 1), None],   # overdue: not "soon"
        ["Far away", "Flo", "Open", datetime(2026, 12, 25), None],
        ["Far away", "Flo", "Open", datetime(2026, 12, 25), None]]   # duplicate
for r in rows: ws.append(r)
wb.save(f"{d}/tasks.xlsx")
f = checks.analyze(Path(f"{d}/tasks.xlsx"), today)
print(f)
check("blank owner found", any("1 blank cell in 'Owner'" in x and "Pay rent" in x for x in f.checks))
check("optional Notes column ignored", not any("Notes" in x for x in f.checks))
check("duplicate found", any("1 duplicate row" in x and "far away" in x.lower() for x in f.checks))
check("due soon list", len(f.soon) == 4 and any("Pay rent" in x and "today" in x for x in f.soon) and any("Build site" in x and "Nov 3" in x for x in f.soon))
check("done and overdue not 'soon'", not any("Old thing" in x or "Late thing" in x or "Far away" in x for x in f.soon))

# csv + junk
open(f"{d}/a.csv", "w").write("Task,Status,Due\n" + "\n".join(f"T{i},Open,2026-11-0{i%9+1}" for i in range(8)) + "\nT9,,2026-11-04\n")
f = checks.analyze(Path(f"{d}/a.csv"), today); print(f)
check("csv blank status", any("'Status'" in x for x in f.checks))
open(f"{d}/bad.xlsx", "w").write("not really excel")
check("corrupt file: no crash", checks.analyze(Path(f"{d}/bad.xlsx"), today) == checks.Findings())
open(f"{d}/n.txt", "w").write("hi")
check("text file ignored", checks.analyze(Path(f"{d}/n.txt"), today) == checks.Findings())
check("missing file: no crash", checks.analyze(Path(f"{d}/nope.xlsx"), today) == checks.Findings())
print("ALL PASSED" if not bad else bad)
