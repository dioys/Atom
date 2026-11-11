import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, random
from datetime import datetime
from pathlib import Path
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, analysis, tools
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)

import openpyxl
d = tempfile.mkdtemp()
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Sales"
ws.append(["Company sales export"]); ws.append([])
ws.append(["Order Date", "Region", "Product", "Sales", "Units"])
random.seed(3)
expected = {"2025": 0, "2026": 0}; by_region = {}; jan = {"2025": 0, "2026": 0}
for year in (2025, 2026):
    for month in range(1, 13):
        for region in ("North", "South"):
            sales = 1000 * month + (500 if region == "North" else 0) + (3000 if year == 2026 else 0)
            ws.append([datetime(year, month, 5), region, "Widget" if month % 2 else "Gadget", sales, sales // 100])
            expected[str(year)] += sales; by_region[region] = by_region.get(region, 0) + sales
            if month == 1: jan[str(year)] += sales
ws.append([datetime(2026, 5, 5), "North", "Widget", None, None])        # blank value
ws.append(["not a date", "East", "Widget", "$1,200", 12])               # text date + currency text
wb.save(f"{d}/sales.xlsx")
path = Path(f"{d}/sales.xlsx")

# ---- totals by year (the original question)
out = analysis.run_aggregate(path, value="Sales", by="Order Date", period="year", how="sum")
print(out)
check("2025 total", f"{expected['2025']:,}" in out)
check("2026 total", f"{expected['2026']:,}" in out)
check("year change shown", "+" in out and "% vs 2025" in out)
check("skipped rows reported", "skipped" in out)

# ---- compare years month by month
out = analysis.run_aggregate(path, value="sales", by="order date", period="month", split="year")
print(out)
check("pivot has both years", "2025 | 2026" in out and "Jan | " in out and f"{jan['2025']:,}" in out and f"{jan['2026']:,}" in out)
check("months in calendar order", out.index("Jan |") < out.index("Feb |") < out.index("Dec |"))
check("pivot total row", "TOTAL" in out)

# ---- categories, filter, other measures
out = analysis.run_aggregate(path, value="Sales", by="Region")
check("by region biggest first", out.index("North") < out.index("South") and f"{by_region['North']:,}" in out)
out = analysis.run_aggregate(path, value="Sales", by="Order Date", period="year", filter_column="Region", filter_value="north")
check("filter works", "only rows where Region = north" in out)
out = analysis.run_aggregate(path, value="Sales", how="mean")
check("overall mean", "Average of Sales" in out)
out = analysis.run_aggregate(path, by="Region", how="count")
check("count rows per region", "Count of rows by Region" in out and "North: 24" in out.replace("North: 25", "North: 24") or "North: 25" in out)
out = analysis.run_aggregate(path, value="Sals", by="Regon")   # typos resolved
check("typo-tolerant columns", "Total of Sales by Region" in out)
try: analysis.run_aggregate(path, value="Profit"); check("unknown column error", False)
except ValueError as e: check("unknown column error", "Order Date, Region, Product, Sales, Units" in str(e))
try: analysis.run_aggregate(path, value="Sales", by="Region", period="month"); check("period on non-date error", False)
except ValueError as e: check("period on non-date error", "doesn't look like dates" in str(e))

# ---- statistics
st = analysis.run_stats(path)
print(st)
check("stats numbers", "- Sales:" in st and "median" in st and "outliers" in st)
check("correlation found", "Sales and Units" in st and "strongly" in st)
st2 = analysis.run_stats(path, columns="Region,Product")
check("text columns counted", "2 different values" in st2 or "3 different values" in st2)

# ---- charts
for kind, kw in [
    ("bar", dict(x="Order Date", y="Sales", period="year")),
    ("bar", dict(x="Order Date", y="Sales", period="month", split="year")),
    ("line", dict(x="Order Date", y="Sales", period="month", split="year", title="Sales: 2025 vs 2026")),
    ("pie", dict(x="Region", y="Sales")),
    ("scatter", dict(x="Units", y="Sales")),
    ("hist", dict(x="Sales")),
]:
    png, text = analysis.run_chart(path, kind=kind, **kw)
    check(f"chart {kind} {kw.get('period','')}{kw.get('split','')}", png.exists() and png.stat().st_size > 5000 and png.suffix == ".png" and text)
try: analysis.run_chart(path, kind="pie", x="Order Date", y="Sales", period="month", split="year"); check("pie+split rejected", False)
except ValueError as e: check("pie+split rejected", "pie chart" in str(e))

# ---- CSV
open(f"{d}/p.csv", "w").write("Title row\nName,Score,Joined\nA,10,2025-01-05\nB,20,2025-06-01\nC,30,2026-02-01\nD,5,2026-03-01\n")
out = analysis.run_aggregate(Path(f"{d}/p.csv"), value="Score", by="Joined", period="year")
check("csv by year", "2025: 30" in out and "2026: 35" in out)

# ---- through the ToolBox
store = tools.FileStore(db_path=f"{home}/t.db")
store.add([str(path)])
opened = []
tools._open_path = lambda p: opened.append(p.name)
box = tools.ToolBox(store)
r = box.run("data_aggregate", {"name": "sales", "value": "Sales", "by": "Order Date", "period": "year"})
check("tool data_aggregate", f"{expected['2026']:,}" in r)
r = box.run("data_aggregate", {"name": "sales", "value": "Nope"})
check("tool error is readable", r.startswith("Could not do that") and "The columns are" in r)
r = box.run("make_chart", {"name": "sales", "kind": "bar", "x": "Region", "y": "Sales"})
check("tool make_chart opens png", opened and opened[-1].endswith(".png") and "open on the user's screen" in r)
check("tool data_stats", "Statistics" in box.run("data_stats", {"name": "sales"}))
check("12 tools", len(box.openai_tools()) == 32)
print("ALL PASSED" if not bad else bad)
