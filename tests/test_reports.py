import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile
from datetime import date, datetime
from pathlib import Path
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, reports, tools
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)

import openpyxl
d = tempfile.mkdtemp()
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Tasks"
ws.append(["Project Alpha tracker"])             # title row above the table
ws.append([])
ws.append(["Task", "Owner", "Status", "Due date", "Budget"])
ws.append(["Design logo", "Ana", "Done", datetime(2026, 10, 1), 1000])
ws.append(["Build site", "Ben", "In progress", datetime(2026, 10, 20), 5000])   # overdue
ws.append(["Write copy", "Ana", "Blocked", datetime(2026, 9, 15), 800])          # overdue
ws.append(["Launch", "Cy", "Not started", datetime(2026, 12, 15), 2200.5])
ws.append(["Old thing", "Cy", "Completed", datetime(2026, 8, 1), 300])           # past, but done
ws2 = wb.create_sheet("Notes"); ws2.append(["Note", "Who"]); ws2.append(["hello", "x"])
wb.save(f"{d}/tracker.xlsx")
open(f"{d}/people.csv", "w").write("Name,Score\nA,10\nB,20\nC,30\n")
open(f"{d}/doc.pdf", "wb").write(b"%PDF")

today = date(2026, 11, 1)
out = reports.summarize_table(Path(f"{d}/tracker.xlsx"), today)
print(out)
check("finds header under title row", 'Sheet "Tasks": 5 rows' in out and "columns: Task, Owner, Status, Due date, Budget" in out)
check("status counts", "Done (1)" in out and "Blocked (1)" in out and "In progress (1)" in out and "Completed (1)" in out)
check("budget math", "total 9,300" in out.replace("9,300.5", "9,300") or "total 9,300.50" in out or "9,300" in out)
check("due range + before today", "2026-08-01 to 2026-12-15" in out and "4 before today" in out)
check("overdue not done = 2", "Past due and not done: 2" in out and "Build site / Ben" in out and "Write copy / Ana" in out and "Old thing" not in out.split("Past due and not done")[1] and "Design logo" not in out.split("Past due and not done")[1])
many = Path(f"{d}/many.csv"); many.write_text("Task,Status\n" + "\n".join(f"job {i},Done" for i in range(10)))
mo = reports.summarize_table(many, today)
check("long unique-name column summarised, status still counted", "- Task: 10 different values" in mo and "Done (10)" in mo)
check("second sheet listed", 'Sheet "Notes": 1 rows' in out)

csvout = reports.summarize_table(Path(f"{d}/people.csv"), today)
check("csv numbers", "total 60" in csvout and "3 rows" in csvout and "Past due" not in csvout)
try: reports.summarize_table(Path(f"{d}/doc.pdf")); check("pdf rejected", False)
except ValueError as e: check("pdf rejected", "Excel" in str(e))

# --- Word report
p = reports.write_report("Project Alpha status", "# Summary\nThings are **mostly** fine.\n## Problems\n- Build site is late\n- Write copy is blocked\n1. Fix it\nPlain line")
from docx import Document
doc = Document(p)
styles = [(x.style.name, x.text) for x in doc.paragraphs]
check("docx written", p.suffix == ".docx" and p.parent == config.REPORTS_DIR)
check("docx headings/bullets", ("Heading 1", "Summary") in styles and ("List Bullet", "Build site is late") in styles and ("Title", "Project Alpha status") in styles and ("List Number", "Fix it") in styles)
check("docx bold run", any(r.bold and r.text == "mostly" for x in doc.paragraphs for r in x.runs))
p2 = reports.write_report("Project Alpha status", "# x")
check("no overwrite", p2 != p and p2.exists())

# --- ToolBox wiring
store = tools.FileStore(db_path=f"{home}/t.db")
store.add([f"{d}/tracker.xlsx", f"{d}/people.csv"])
opened = []
tools._open_path = lambda path: opened.append(path.name)
box = tools.ToolBox(store)
r = box.run("table_summary", {"name": "tracker"})
check("tool table_summary", "Past due and not done: 2" in r)
check("tool table_summary errors nicely", "No added file" in box.run("table_summary", {"name": "nope"}))
r = box.run("save_report", {"title": "Weekly", "content": "# Summary\n- ok"})
check("tool save_report opens doc", r.startswith("Saved the report") and "opened it" in r and opened and opened[-1].endswith(".docx"))
check("empty report rejected", box.run("save_report", {"title": "x", "content": " "}).startswith("Error"))
check("9 tools offered", len(box.openai_tools()) == 32)
print("ALL PASSED" if not bad else bad)
