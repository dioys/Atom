import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")

import os, sys, tempfile, pathlib
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, tools
config.POWERBI_DIR = pathlib.Path(home) / "pbi"
bad = []
def check(n, c, *i):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, i))
import csv, random
p = pathlib.Path(home) / "Clothes Sales.csv"
random.seed(2)
with open(p, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["Date", "Region", "Item", "Sales", "Units"])
    for i in range(120): w.writerow([f"2025-{1 + i % 12:02d}-{1 + i % 27:02d}", random.choice(["N", "S", "E"]), random.choice(["Shirt", "Hat"]), round(random.random() * 100, 2), random.randint(1, 9)])
names = [s["name"] for s in tools.ToolBox.SPECS]
check("tool exists", "build_powerbi_report" in names)
box = tools.ToolBox.__new__(tools.ToolBox)
class R: pass
rec = R(); rec.path = str(p); rec.library_path = str(p); rec.name = p.name
box._find = lambda name: (rec, None)
opened = []
tools._open_path = lambda path: opened.append(pathlib.Path(path).name)
out = box._tool_build_powerbi_report({"name": "Clothes Sales", "title": "Clothes Sales 2025"})
print(out)
check("built and opened the .pbip", opened == ["Clothes Sales.pbip"] and "Built the Power BI report" in out, opened)
check("lists what is in it", "line chart" in out and "card" in out)
# custom spec
opened.clear()
out = box._tool_build_powerbi_report({"name": "Clothes Sales", "kpis": "sum:Sales", "charts": "bar,Region,Sales,sum; pie,Item,Units,sum"})
check("custom charts", "column chart: Sum of Sales by Region" in out and "bar chart: Sum of Units by Item" in out, out)
check("says it presses Refresh or how to enable it", "Refresh" in out, out)
opened.clear()
tools._open_path = lambda path: (_ for _ in ()).throw(OSError("no app")) if str(path).endswith(".pbip") else opened.append("folder")
out = box._tool_build_powerbi_report({"name": "Clothes Sales"})
check("falls back to folder", "opened the folder" in out and opened == ["folder"], out)
# unknown column message
out = box._tool_build_powerbi_report({"name": "Clothes Sales", "charts": "bar,Nope,Sales,sum"})
check("bad column: clear message with the real columns", "Could not do that" in out and "Region" in out, out)
print("\nFAILED:" if bad else "\nALL PASSED", bad or "")
sys.exit(1 if bad else 0)
