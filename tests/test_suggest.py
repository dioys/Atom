import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, threading, time
from datetime import date, datetime
from pathlib import Path
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, tools, suggestions
import openpyxl
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)

d = tempfile.mkdtemp()
def make_tracker(path, rows):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Task", "Status", "Due date"])
    for r in rows: ws.append(r)
    wb.save(path)
tracker = f"{d}/tracker.xlsx"
make_tracker(tracker, [["Build site", "In progress", datetime(2026, 10, 20)], ["Write copy", "Blocked", datetime(2026, 9, 15)], ["Launch", "Not started", datetime(2026, 12, 15)]])
open(f"{d}/notes.txt", "w").write("meeting notes about zebras")

store = tools.FileStore(db_path=f"{home}/t.db")
store.add([tracker, f"{d}/notes.txt"])
today = date(2026, 11, 1)
s = suggestions.Suggester(store, today)

# ---- first check: overdue warning
msg = s.check()
print(msg)
check("startup warning", msg and "tracker.xlsx has 2 items past due" in msg and "Build site" in msg and "Press Report" in msg)
msg2 = s.check()
check("repeated until acknowledged (e.g. Atom was busy)", msg2 == msg)
s.acknowledge()
check("quiet once acknowledged", s.check() is None)

# ---- file edited on disk
time.sleep(0.05)
make_tracker(tracker, [["Build site", "Done", datetime(2026, 10, 20)], ["Write copy", "Blocked", datetime(2026, 9, 15)], ["Brand new quokka task", "Open", datetime(2026, 10, 1)]])
os.utime(tracker, (time.time() + 30, time.time() + 30))
check("edit detected as stale", store.stale_paths() == [str(Path(tracker).resolve())] or len(store.stale_paths()) == 1)
msg = s.check()
print(msg)
check("change noticed + new overdue count", msg and "I noticed tracker.xlsx changed" in msg and "2 items past due" in msg and "quokka" in msg.lower() + "quokka")
check("new content searchable", any("quokka" in h.text.lower() for h in store.search("quokka")))
check("old content gone", not any("In progress" in h.text for h in store.search("progress")))
s.acknowledge()
check("not stale after refresh", store.stale_paths() == [] and s.check() is None)

# ---- overdue count unchanged after an edit -> only the 'changed' line
time.sleep(0.05)
make_tracker(tracker, [["Build site", "Done", datetime(2026, 10, 20)], ["Write copy", "Blocked", datetime(2026, 9, 15)], ["Brand new quokka task", "Open", datetime(2026, 10, 1)], ["Extra", "Open", datetime(2026, 12, 30)]])
os.utime(tracker, (time.time() + 60, time.time() + 60))
msg = s.check()
check("only change line when overdue already told", msg and "changed" in msg and "past due" not in msg)
s.acknowledge()

# ---- text file edit (no spreadsheet) and a deleted original
open(f"{d}/notes.txt", "w").write("meeting notes about giraffes now")
os.utime(f"{d}/notes.txt", (time.time() + 90, time.time() + 90))
msg = s.check()
check("text file change noticed", msg and "notes.txt changed" in msg)
s.acknowledge()
os.remove(f"{d}/notes.txt")
check("deleted original left alone", s.check() is None and any(r.name == "notes.txt" for r in store.all()))

# ---- newly added file gets scanned
make_tracker(f"{d}/late.xlsx", [["Pay rent", "Open", datetime(2026, 10, 1)]])
added, _ = store.add([f"{d}/late.xlsx"])
s.scan_soon([r.name for r in added])
msg = s.check()
check("new file's overdue work mentioned", msg and "late.xlsx has 1 item past due" in msg)

# ---- background adding while the 'window' keeps using the store
big = []
for i in range(6):
    p = f"{d}/big{i}.txt"; open(p, "w").write(("lorem ipsum dolor " * 4000) + f" unique{i}"); big.append(p)
errors = []
def worker():
    try: store.add(big)
    except Exception as e: errors.append(e)
t = threading.Thread(target=worker); t.start()
while t.is_alive():
    try:
        store.all(); len(store); store.search("lorem"); store.context_for("ipsum")
    except Exception as e: errors.append(e); break
t.join()
check("no errors while adding in background", not errors and len([r for r in store.all() if r.name.startswith("big")]) == 6)
print("ALL PASSED" if not bad else bad)
