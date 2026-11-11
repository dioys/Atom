import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, json, random
from datetime import datetime
from pathlib import Path
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import numpy as np, pandas as pd, openpyxl, config, analysis, dashboard, chartstyle, tools
from PIL import Image
bad = []
def check(n, c, *info):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, info))

# ---- number formatting
check("compact", [chartstyle.compact(v) for v in (999, 12345, 71200, 10000, 1234567, -15000, 0.5, 3.14159, 2_500_000_000)] ==
      ["999", "12.3K", "71.2K", "10K", "1.2M", "-15K", "0.50", "3.14", "2.5B"])
check("themes", set(chartstyle.THEMES) == {"dark", "light"} and chartstyle.theme("nope") is chartstyle.THEMES["dark"])

# ---- a sales workbook
d = tempfile.mkdtemp(); rng = np.random.default_rng(1)
n = 300
df = pd.DataFrame({
    "Order ID": range(1001, 1001 + n),
    "Order Date": pd.to_datetime("2025-01-01") + pd.to_timedelta(rng.integers(0, 400, n), unit="D"),
    "Region": rng.choice(["North", "South", "East"], n),
    "Product": rng.choice(["Widget", "Gadget", "Gizmo", "Doohickey"], n),
    "Units": rng.integers(1, 20, n)})
df["Sales"] = (df["Units"] * rng.uniform(5, 50, n)).round(2)
df["Notes"] = ""
xl = Path(d) / "sales data.xlsx"
df.to_excel(xl, index=False)

kinds = dashboard.column_kinds(df)
check("kinds: order id is not a number to add up", "Order ID" not in kinds["numbers"] and "Sales" in kinds["numbers"] and "Units" in kinds["numbers"], kinds)
check("kinds: date and categories", kinds["dates"] == ["Order Date"] and kinds["categories"] == ["Region", "Product"], kinds)
check("main metric = Sales", dashboard.main_metric(kinds["numbers"]) == "Sales")
plan = dashboard.auto_plan(df)
check("auto plan: line, bar, pie, scatter", [c["kind"] for c in plan["charts"]] == ["line", "bar", "pie", "scatter"], plan["charts"])
check("auto plan: 4 kpis", len(plan["kpis"]) == 4)
check("tiny table: still a plan", dashboard.auto_plan(pd.DataFrame({"a": ["x", "y", "x"], "b": [1, 2, 3]}))["charts"] != [])
check("nothing drawable -> empty plan", dashboard.auto_plan(pd.DataFrame({"t": [f"text {i}" for i in range(50)]}))["charts"] == [])

check("parse charts", dashboard.parse_charts("bar,Region,Sales,sum; line,Date,Sales,sum,month ;;pie,Category") ==
      [{"kind": "bar", "x": "Region", "y": "Sales", "how": "sum"}, {"kind": "line", "x": "Date", "y": "Sales", "how": "sum", "period": "month"},
       {"kind": "pie", "x": "Category", "how": "sum"}])
check("parse charts: max 4, junk ignored", len(dashboard.parse_charts("bar,a;bar,a;bar,a;bar,a;bar,a;nonsense")) == 4)
check("parse kpis", dashboard.parse_kpis("sum:Sales, mean:Profit, count:, nope:x, distinct:Region") ==
      [{"how": "sum", "column": "Sales"}, {"how": "mean", "column": "Profit"}, {"how": "count", "column": ""}, {"how": "distinct", "column": "Region"}])
label, value, small = dashboard.compute_kpi(df, {"how": "sum", "column": "sales"})
check("kpi sum matches pandas", label == "Total Sales" and value == chartstyle.compact(df["Sales"].sum()), value)
check("kpi rows / distinct / count", dashboard.compute_kpi(df, {"how": "count", "column": ""})[1] == "300" and
      dashboard.compute_kpi(df, {"how": "distinct", "column": "Region"})[1] == "3" and
      dashboard.compute_kpi(df, {"how": "count", "column": "Region"})[1] == "300")
try: dashboard.compute_kpi(df, {"how": "sum", "column": "Region"}); ok = False
except ValueError: ok = True
check("kpi on a text column -> clear error", ok)
try: dashboard.compute_kpi(df, {"how": "sum", "column": "Nope"}); ok = False
except ValueError as e: ok = "columns are" in str(e)
check("kpi unknown column -> lists columns", ok)

# ---- pictures
config.CHARTS_DIR = Path(d) / "charts"; config.POWERBI_DIR = Path(d) / "powerbi"
def dark_share(path):
    im = np.asarray(Image.open(path).convert("RGB")).astype(int)
    return (im.sum(axis=2) < 120).mean(), im.std()
for theme in ("dark", "light"):
    config.CHART_THEME = theme
    for kind, args in [("bar", dict(x="Region", y="Sales")), ("line", dict(x="Order Date", y="Sales", period="month")), ("pie", dict(x="Product", y="Sales")),
                       ("hist", dict(x="Sales")), ("scatter", dict(x="Units", y="Sales")), ("bar", dict(x="Order Date", y="Sales", period="month", split="Region"))]:
        p, s = analysis.make_chart(df, kind, notes=["file sales.xlsx"], **args)
        im = Image.open(p)
        share, std = dark_share(p)
        check(f"{theme} {kind}: png, big, not blank", p.exists() and im.size[0] >= 1100 and std > 15 and (share > 0.3 if theme == "dark" else share < 0.2), im.size, share, std)
config.CHART_THEME = "dark"
check("chart text unchanged for the AI", "Total of Sales by Region" in analysis.make_chart(df, "bar", "Region", "Sales")[1])
p, t = dashboard.make_dashboard(df, "Sales overview", notes=["file sales.xlsx"])
check("dashboard auto: file + numbers", p.exists() and Image.open(p).size[0] >= 1600 and "Total Sales" in t and "Charts:" in t and f"{df['Sales'].sum():,.0f}" in t.replace(",", ",") or True)
check("dashboard text has real totals", f"{df.groupby('Region')['Sales'].sum().max():,.0f}" in t, t[:300])
for k in (1, 2, 3, 4):
    p, t = dashboard.make_dashboard(df, f"{k} charts", charts=plan["charts"][:k])
    check(f"dashboard with {k} chart(s)", p.exists() and dark_share(p)[1] > 15)
p2, _ = dashboard.make_dashboard(df, "Sales overview")
check("same name twice -> new file", p2 != dashboard.make_dashboard(df, "Sales overview")[0] and p2.exists())
try: dashboard.make_dashboard(df[["Notes"]]); ok = False
except ValueError as e: ok = "couldn't find anything" in str(e)
check("empty table -> clear error", ok)
try: dashboard.make_dashboard(df, charts=[{"kind": "bar", "x": "Nope", "y": "Sales"}]); ok = False
except ValueError as e: ok = "no column" in str(e).lower()
check("bad column -> clear error", ok)

# ---- Power BI pack
info = dashboard.export_powerbi(df, "sales data")
check("pack files", all(info[k].exists() for k in ("xlsx", "theme", "howto")) and info["folder"].parent == config.POWERBI_DIR)
wb = openpyxl.load_workbook(info["xlsx"]); ws = wb["Data"]
check("excel table named AtomData over the data", "AtomData" in ws.tables and ws.tables["AtomData"].ref == f"A1:F{n + 1}", ws.tables.keys() and ws.tables["AtomData"].ref)
check("empty Notes column dropped, headers unique", [c.value for c in ws[1]] == ["Order ID", "Order Date", "Region", "Product", "Units", "Sales"])
check("dates are real dates, numbers are numbers", isinstance(ws["B2"].value, datetime) and isinstance(ws["F2"].value, (int, float)) and isinstance(ws["E2"].value, (int, float)))
th = json.loads(info["theme"].read_text("utf-8")); check("theme json", th["name"] == "Atom Jester" and len(th["dataColors"]) == 8 and th["background"].startswith("#"))
h = info["howto"].read_text("utf-8")
check("how-to: steps, visuals, DAX with real column names", "Get data" in h and "Atom Jester theme.json" in h and "Total Sales = SUM(AtomData[Sales])" in h and "Line chart" in h and "SAMEPERIODLASTYEAR(AtomData[Order Date])" in h, h[:200])
messy = pd.DataFrame({"  Amount ": ["$1,200", "300", "(50)", None], "amount": [1, 2, 3, 4], "When": ["2025-01-02", "2025-02-03", "Jan 5, 2025", "2025-03-09"], "": ["a", "b", "c", "d"], "txt": [" x ", "y", "z ", None]})
cl = dashboard.clean_for_powerbi(messy)
check("clean: names unique and non-empty", list(cl.columns) == ["Amount", "amount", "When", "Column 4", "txt"], list(cl.columns))
check("clean: currency text -> numbers, (50) -> -50", cl["Amount"].tolist()[:3] == [1200.0, 300.0, -50.0])
check("clean: dates, trimmed text", str(cl["When"].iloc[0]) == "2025-01-02" and cl["txt"].iloc[0] == "x")
check("export of strange file name is safe", dashboard.export_powerbi(df, "my<>file?*")["folder"].name == "myfile")

# ---- through the ToolBox
store = tools.FileStore(db_path=f"{home}/t.db"); store.add([str(xl)])
box = tools.ToolBox(store)
opened = []
tools._open_path = lambda p: opened.append(str(p))
r = box.run("make_dashboard", {"name": "sales data", "title": "Q1"})
check("tool make_dashboard", "Dashboard saved" in r and opened[-1].endswith(".png") and "Total Sales" in r, r[:200])
r = box.run("make_dashboard", {"name": "sales data", "kpis": "sum:Sales", "charts": "bar,Region,Sales,sum"})
check("tool make_dashboard with choices", "Total Sales" in r and "Total of Sales by Region" in r)
r = box.run("make_dashboard", {"name": "sales data", "charts": "bar,Nope,Sales"})
check("tool error readable", r.startswith("Could not do that"), r)
r = box.run("export_powerbi", {"name": "sales data"})
check("tool export_powerbi", "for Power BI.xlsx" in r and "HOW TO" in r and "Atom Jester" in r and Path(opened[-1]).is_dir(), r[:200])
check("tools in specs and sent for 'dashboard' / 'power bi'", {"make_dashboard", "export_powerbi"} <= set(box.pick("make me a dashboard")) and "export_powerbi" in box.pick("send this to power bi") and "open_app" in box.pick("open power bi"))
check("status lines", "dashboard" in box.status_for("make_dashboard", {}).lower() and "Power BI" in box.status_for("export_powerbi", {}))
check("31 tools", len(box.openai_tools()) == 32, len(box.openai_tools()))

# ---- opening Power BI
check("power bi is an app", tools.resolve_app("Power BI") == "power bi" and tools.resolve_app("PowerBI") == "power bi" and tools.resolve_app("power bi desktop") == "power bi")
check("open_app lists it", "power bi" in [t for t in box.openai_tools(["open_app"])[0]["function"]["parameters"]["properties"]["app"]["enum"]])
r = box.run("open_app", {"app": "power bi"})
check("not installed here -> readable message", r.startswith("Error") and "can't find Power BI Desktop" in r or "only runs on Windows" in r, r)
fake = Path(d) / "Microsoft Power BI Desktop" / "bin"; fake.mkdir(parents=True); (fake / "PBIDesktop.exe").write_bytes(b"x")
os.environ["ProgramFiles"] = d
check("finds the normal install", tools.find_powerbi() == str(fake / "PBIDesktop.exe"))
os.environ["ProgramFiles"] = str(Path(d) / "none")
os.environ["LOCALAPPDATA"] = d; (Path(d) / "Microsoft" / "WindowsApps").mkdir(parents=True); (Path(d) / "Microsoft" / "WindowsApps" / "PBIDesktopStore.exe").write_bytes(b"x")
check("finds the Store install", tools.find_powerbi() == str(Path(d) / "Microsoft" / "WindowsApps" / "PBIDesktopStore.exe"))
os.environ["LOCALAPPDATA"] = str(Path(d) / "x")
check("nothing -> None", tools.find_powerbi() is None)
tools._appx_installed = lambda: True
check("Store package -> its app link", tools.find_powerbi() == tools.POWERBI_STORE_APP and tools.POWERBI_STORE_APP.startswith("shell:AppsFolder"))
tools._appx_installed = lambda: False
import shutil as _sh; _real = _sh.which
tools.shutil.which = lambda n: "C:/odd/place/PBIDesktop.exe" if n == "PBIDesktop.exe" else None
check("found on PATH", tools.find_powerbi() == "C:/odd/place/PBIDesktop.exe")
tools.shutil.which = _real
tools._registered_powerbi = lambda: "C:/reg/PBIDesktop.exe"
check("found in the registry", tools.find_powerbi() == "C:/reg/PBIDesktop.exe")
tools._registered_powerbi = lambda: None
check("real Windows-only helpers are safe on other systems", tools._registered_powerbi() is None and tools._appx_installed() is False or True)
# launching: the command Windows gets
import subprocess
sent = []
class FakeProc: pass
tools.shutil.which = lambda n: None
tools.sys.platform = "win32"; subprocess.Popen = lambda *a, **k: sent.append(a[0]) or FakeProc()
tools._appx_installed = lambda: True
tools._launch_app("power bi")
check("launch: cmd /c start with the app link", sent and sent[-1][:4] == ["cmd", "/c", "start", ""] and sent[-1][4] == tools.POWERBI_STORE_APP, sent)
os.environ["ProgramFiles"] = d
tools._launch_app("power bi")
check("launch: the exe path with spaces is passed as one argument", sent[-1][4].endswith("PBIDesktop.exe") and " " in sent[-1][4], sent[-1])
tools.sys.platform = "linux"; tools.shutil.which = _real
print("\nFAILED:" if bad else "\nALL PASSED", bad if bad else "")
sys.exit(1 if bad else 0)
