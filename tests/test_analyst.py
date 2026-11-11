import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import sys, os, tempfile, random
from pathlib import Path
sys.path.insert(0, SRC)
import config
tmp = Path(tempfile.mkdtemp()); config.REPORTS_DIR = tmp / "reports"
import pandas as pd, numpy as np
import analysis as A, analyst as T

random.seed(1)
rows = []
for m in range(1, 11):
    for d in (3, 11, 19, 27):
        for region in ("North", "South", "East"):
            for prod in ("Shirt", "Pants"):
                rows.append({"Date": f"2025-{m:02d}-{d:02d}", "Region": region, "Product": prod,
                             "Sales": round((100 + m * 12 + (30 if region == "North" else 0)) * random.uniform(.8, 1.2), 2),
                             "Units": random.randint(1, 20)})
csv = tmp / "sales.csv"; pd.DataFrame(rows).to_csv(csv, index=False)

# ---- pivot
text, p = T.run_pivot(csv, rows="Region", columns="Product", value="Sales")
print(text); assert "TOTAL" in text and "Total" in text and p is None
text, p = T.run_pivot(csv, rows="Region", columns="Product", value="Sales", percent="true", save=True)
assert "%" in text and p.exists() and p.suffix == ".xlsx"
import openpyxl
wb = openpyxl.load_workbook(p); ws = wb["Pivot"]; assert len(ws._charts) == 1, "native chart"
assert ws["A2"].value is None or ws["A2"].value == "" ; assert ws["B2"].value in ("Pants", "Shirt")
text, _ = T.run_pivot(csv, rows="Date", columns="Region", value="Sales", period="month")
print(text.splitlines()[:5]); assert "2025-01" in text
text, _ = T.run_pivot(csv, rows="Region", value="Units", how="mean"); assert "TOTAL" not in text
text, _ = T.run_pivot(csv, rows="Region", columns="Product", how="count"); assert "TOTAL" in text
text, _ = T.run_pivot(csv, rows="Date", columns="Region", value="Sales", period="month")
try: T.run_pivot(csv, rows="Nope", value="Sales"); raise SystemExit("x")
except ValueError as e: assert "columns are" in str(e)
# too many columns / rows collapse
df = pd.DataFrame({"a": [f"r{i}" for i in range(40)]*2, "b": [f"c{i%12}" for i in range(80)], "v": range(80)})
res = T.pivot_table(df, "a", "b", "v", top=5, max_cols=4); assert "Other" in res.text and res.table.shape[1] <= 6, res.text
print("pivot ok")

# ---- trend
print(T.run_trend(csv, value="Sales", forecast=3))
t = T.run_trend(csv, value="Sales", date="Date", period="month", forecast=2)
assert "2025-10" in t and "Forecast" in t and "2025-11" in t and "2025-12" in t, t
assert "Average growth" in t
assert "not finished" in t or "2025-10" in t
t = T.run_trend(csv, value="Sales", period="quarter", forecast=1); assert "Q" in t
# partial last month dropped
df2 = pd.DataFrame({"d": pd.date_range("2025-01-01", "2025-06-10", freq="D"), "v": 1.0})
df2p = tmp / "p.csv"; df2.to_csv(df2p, index=False)
t = T.run_trend(df2p, value="v", date="d"); assert "2025-06 is not finished" in t, t
# gaps
df3 = pd.DataFrame({"d": ["2025-01-05", "2025-02-05", "2025-04-05", "2025-05-05", "2025-06-05", "2025-07-05"], "v": [1, 2, 4, 5, 6, 7]})
df3p = tmp / "g.csv"; df3.to_csv(df3p, index=False)
t = T.run_trend(df3p, value="v", date="d"); assert "no rows" in t, t
try: T.run_trend(csv, value="Sales", date="Region"); raise SystemExit("x")
except ValueError: pass
tiny = tmp / "t.csv"; pd.DataFrame({"d": ["2025-01-31", "2025-02-28"], "v": [1, 2]}).to_csv(tiny, index=False)
try: T.run_trend(tiny, value="v"); raise SystemExit("x")
except ValueError as e: assert "at least 3" in str(e)
print("trend ok")

# ---- relate
r = T.run_relate(csv, x="Units", y="Sales"); print(r); assert "Correlation" in r
lin = tmp / "l.csv"; pd.DataFrame({"x": range(20), "y": [3 * i + 5 for i in range(20)]}).to_csv(lin, index=False)
r = T.run_relate(lin, x="x", y="y", at="10, 100"); assert "+3.000" in r and "about 35" in r and "outside" in r, r
try: T.run_relate(lin, x="x", y="x"); raise SystemExit("x")
except ValueError: pass
print("relate ok")

# ---- cleanup
messy = pd.DataFrame({
    "Region": ["North", "north", "North ", "South", "South", "Mannila", "Manila", "Manila", "Manila", "Manila", "Manila", "Manila", "Manila", "Manila"],
    "Amount": ["1,200", "$300", "N/A", "450", "500", "700", "800", "900", "1000", "1100", "1200", "1300", "1400", "1500"],
    "Date": ["2025-01-02", "03/02/2025", "Jan 5, 2025", "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10", "2025-01-11", "2025-01-12", "2025-01-13", "2025-01-14", "2025-01-15", "2025-01-16"],
    "ZIP": ["01234", "02345", "01234", "03456", "01234", "02345", "01234", "02345", "01234", "02345", "01234", "02345", "01234", "02345"],
    "Empty": [None] * 14,
})
messy.loc[len(messy)] = messy.iloc[0]   # duplicate row
mp = tmp / "messy.csv"; messy.to_csv(mp, index=False)
text, path = T.run_cleanup(mp); print(text); assert path is None
for needle in ("extra spaces", "N/A", "numbers as text", "styles", "spelled", "typo", "exact copy", "completely empty"):
    assert needle in text, needle
assert "ZIP" not in text.split("numbers as text")[0].split("\n")[-1] and "'ZIP' stores numbers" not in text
text, path = T.run_cleanup(mp, save="yes"); assert path.exists()
clean = pd.read_excel(path)
assert clean["Amount"].dtype.kind in "if" and clean["Amount"].iloc[0] == 1200
assert set(clean["Region"].dropna().unique()) <= {"North", "South", "Manila", "Mannila"}, clean["Region"].unique()
assert len(clean) == len(messy) - 1 and str(clean["ZIP"].iloc[0]) in ("1234", "01234")
print(open(mp).read()[:0] or "orig untouched:", pd.read_csv(mp).shape == messy.shape)
clean_csv = tmp / "ok.csv"; pd.DataFrame({"a": ["x", "y", "z"] * 3, "n": range(9)}).to_csv(clean_csv, index=False)
text, _ = T.run_cleanup(clean_csv); assert "Looks clean" in text, text
text, path = T.run_cleanup(clean_csv, save=True); assert path is None and "nothing I could fix" in text
print("cleanup ok")

# ---- compare
a = pd.DataFrame({"ID": [1, 2, 3, 4], "Name": ["Ann", "Bob", "Cy", "Di"], "Amt": [10, 20, 30, 40]})
b = pd.DataFrame({"id": ["1", "2", "3", "5"], "name": ["Ann", "Bobby", "cy ", "Ed"], "Amt": [10, 25, 30, 50], "Extra": 1})
pa, pb = tmp / "a.csv", tmp / "b.csv"; a.to_csv(pa, index=False); b.to_csv(pb, index=False)
t = T.run_compare(pa, pb, key="ID"); print(t)
assert "1 only in A" in t and "1 only in B" in t and "total 10 -> 11" not in t
assert "Bob" in t and "Bobby" in t and "20 -> 25" in t and "Extra" in t
assert "1 of 3 matched rows differ" in t, t
t = T.run_compare(pa, pb); assert "Whole rows" in t and "Tip" in t
t = T.run_compare(pa, pa, key="ID"); assert "0 of 4 matched rows differ" in t, t
# sheets in one workbook
xl = tmp / "w.xlsx"
with pd.ExcelWriter(xl) as w: a.to_excel(w, "Jan", index=False); a.assign(Amt=[10, 21, 30, 40]).to_excel(w, "Feb", index=False)
t = T.run_compare(xl, xl, sheet="Jan", sheet2="Feb", key="ID"); assert "Amt" in t and "20 -> 21" in t and "[Jan]" in t, t
print("compare ok")

# ---- join
cust = pd.DataFrame({"CustID": [1, 2, 3, 9], "City": ["Manila", "Cebu", "Davao", "Baguio"]})
orders = pd.DataFrame({"cust": ["1", "1", "2", "7"], "Amount": [5, 6, 7, 8], "City": ["x", "y", "z", "w"]})
pc, po = tmp / "cust.csv", tmp / "orders.csv"; cust.to_csv(pc, index=False); orders.to_csv(po, index=False)
t, out = T.run_join(po, pc, key="cust", key2="CustID", how="left"); print(t)
j = pd.read_excel(out); assert len(j) == 4 and "City (cust)" in j.columns, j.columns
t, out = T.run_join(po, pc, key="cust", key2="CustID", how="inner"); assert len(pd.read_excel(out)) == 3
t, out = T.run_join(po, pc, key="cust", key2="CustID", how="outer"); j = pd.read_excel(out); assert len(j) == 6 and j["cust"].notna().all(), j
try: T.run_join(po, pc, key="cust", key2="CustID", how="sideways"); raise SystemExit("x")
except ValueError: pass
none = tmp / "n.csv"; pd.DataFrame({"k": [100, 200], "z": [1, 2]}).to_csv(none, index=False)
try: T.run_join(po, none, key="cust", key2="k"); raise SystemExit("x")
except ValueError as e: assert "saved nothing" in str(e)
print("join ok")
print("ALL PASSED")

# ---- wired into ToolBox
import tools
box = tools.ToolBox.__new__(tools.ToolBox)
names = {s["name"] for s in tools.ToolBox.SPECS}
for n in ("data_pivot", "data_trend", "data_relate", "data_compare", "data_cleanup", "data_join"):
    assert n in names and hasattr(tools.ToolBox, f"_tool_{n}"), n
    assert tools.ToolBox.status_for(box, n, {}) != "Working on it...", n
picked = box.pick("make a pivot of sales by region") ; assert "data_pivot" in picked, picked
assert "data_trend" in box.pick("what is the sales trend and forecast?")
assert "data_cleanup" in box.pick("is my file messy, any duplicates?")
assert {"data_compare", "data_join"} <= set(box.pick("compare jan and feb files"))
print(len(box.pick("compare the trend and pivot and clean it")), "tools for a long ask")
print("WIRING OK")

# ---- end to end through ToolBox.run (real FileStore)
opened = []
tools._open_path = lambda p: opened.append(Path(p).name)
home = tempfile.mkdtemp()
store = tools.FileStore(db_path=f"{home}/t.db")
store.add([str(csv), str(mp), str(pa), str(pb), str(pc), str(po)])
box = tools.ToolBox(store)
r = box.run("data_pivot", {"name": "sales.csv", "rows": "Region", "columns": "Product", "value": "Sales", "save": True})
assert "TOTAL" in r and "Saved as" in r and opened[-1].endswith(".xlsx"), r
r = box.run("data_trend", {"name": "sales.csv", "value": "Sales"}); assert "Forecast" in r, r
r = box.run("data_relate", {"name": "sales.csv", "x": "Units", "y": "Sales"}); assert "Correlation" in r
r = box.run("data_compare", {"name": "a.csv", "name2": "b.csv", "key": "ID"}); assert "matched rows differ" in r, r
r = box.run("data_cleanup", {"name": "messy.csv", "save": True}); assert "Cleaned copy made" in r and "added to the file list" in r, r
assert any("clean" in rec.name for rec in store.all()), [x.name for x in store.all()]
r = box.run("data_join", {"name": "orders.csv", "name2": "cust.csv", "key": "cust", "key2": "CustID", "how": "left"})
assert "Result (left join)" in r and "added to the file list" in r, r
r = box.run("data_pivot", {"name": "nope.csv", "rows": "x"}); assert "No added file" in r, r
r = box.run("data_pivot", {"name": "sales.csv", "rows": "Bogus"}); assert r.startswith("Could not do that"), r
r = box.run("data_compare", {"name": "a.csv", "name2": "ghost.csv"}); assert "No added file" in r, r
print("E2E OK")
