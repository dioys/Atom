import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, time
from datetime import date, datetime
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, tools, suggestions, watcher
import openpyxl
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)

# ---------------- watcher
d = tempfile.mkdtemp()
a, b, other = f"{d}/a.txt", f"{d}/b.txt", f"{d}/untracked.txt"
for p in (a, b, other): open(p, "w").write("x")
hits = []
w = watcher.FileWatcher(lambda p: hits.append(os.path.basename(p)), delay=0.6)
check("available", w.available and w.start())
w.watch([a, b])
time.sleep(0.3)
for i in range(5):                      # a burst of saves of one file
    open(a, "a").write("more"); time.sleep(0.1)
open(other, "a").write("ignored")
open(f"{d}/~$a.txt", "w").write("lock")
time.sleep(1.6)
check("burst counted once", hits == ["a.txt"])
# editor-style atomic save: write temp file, rename over the original
hits.clear()
open(f"{d}/b.tmp", "w").write("new content"); os.replace(f"{d}/b.tmp", b)
time.sleep(1.5)
check("rename-over save noticed", hits == ["b.txt"])
hits.clear(); os.remove(a); time.sleep(1.2)
check("delete ignored", hits == [])
w.watch([f"{d}/never_existed_folder/x.txt"])   # missing folder: no crash
w.stop(); w.stop()
check("stop twice is safe", True)
nw = watcher.FileWatcher(lambda p: None); nw._observer = None
check("watch before start is safe", nw.watch([a]) is None)

# fallback when watchdog missing
saved = watcher.Observer; watcher.Observer = None
check("no watchdog -> start() False", watcher.FileWatcher(lambda p: None).start() is False)
watcher.Observer = saved

# ---------------- suggester with the new findings
def tracker(path, rows):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Tasks"
    ws.append(["Task", "Owner", "Status", "Due date"])
    for r in rows: ws.append(r)
    wb.save(path)
rows = [[f"Task {i}", "Ann", "Open", datetime(2026, 12, 20)] for i in range(6)]
rows[2][1] = None
rows.append(["Soon thing", "Bob", "Open", datetime(2026, 11, 4)])
tp = f"{d}/plan.xlsx"; tracker(tp, rows)
sales = f"{d}/sales.xlsx"
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["Item", "Qty", "Price", "Total"])
for r in range(2, 10): ws.append([f"I{r}", r, 5, f"=B{r}*C{r}"])
ws["D5"] = 77
wb.save(sales)
store = tools.FileStore(db_path=f"{home}/s.db"); store.add([tp, sales])
s = suggestions.Suggester(store, date(2026, 11, 1))
msg = s.check(); print(msg)
check("check + soon both mentioned", msg and "blank cell in 'Owner'" in msg and "due in the next 7 days" in msg and "Soon thing / Bob (Nov 4)" in msg)
check("typed number mentioned", msg and "D5 is a typed number" in msg)
check("Report offered for due items", msg and "Press Report" in msg)
check("repeats until acknowledged", s.check() == msg)
s.acknowledge()
check("told once, then quiet", s.check() is None)
# fix the typed number -> the sales findings vanish; plan unchanged
time.sleep(0.05)
wb = openpyxl.load_workbook(sales); wb.active["D5"] = "=B5*C5"; wb.save(sales)
os.utime(sales, (time.time() + 30, time.time() + 30))
msg = s.check(); print(msg)
check("fixed file: only 'changed' line", msg == "I noticed sales.xlsx changed, so I read it again.")
s.acknowledge(); check("quiet after", s.check() is None)
# a NEW problem appears -> mentioned again even though the file was mentioned before
time.sleep(0.05)
wb = openpyxl.load_workbook(sales); wb.active["D6"] = "=B6+C6"; wb.save(sales)
os.utime(sales, (time.time() + 60, time.time() + 60))
msg = s.check(); print(msg)
check("new problem mentioned", msg and "D6 has a different formula" in msg)
s.acknowledge()
# many findings: at most 3 lines per message, the rest next time
many = []
for i in range(5):
    p = f"{d}/m{i}.xlsx"; tracker(p, [[f"T{j}", None if j == 1 else "x", "Open", datetime(2026, 12, 20)] for j in range(6)]); many.append(p)
added, _ = store.add(many); s.scan_soon([r.name for r in added])
m1 = s.check(); s.acknowledge(); m2 = s.check(); s.acknowledge(); m3 = s.check()
check("limited per message", m1.count("In m") == 3 and m2 and m2.count("In m") == 2 and m3 is None)
print("ALL PASSED" if not bad else bad)
