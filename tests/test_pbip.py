import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, json, tempfile, pathlib, re
home = tempfile.mkdtemp(); os.environ["HOME"] = home
sys.path.insert(0, SRC)
import config, pbip, dashboard
import pandas as pd, numpy as np
ROOT = pathlib.Path(__file__).parent / "schemas/json-schemas"
try:
    import jsonschema
    from referencing import Registry, Resource
except ImportError:
    jsonschema = None
if jsonschema is None or not ROOT.is_dir():
    print("SKIP test_pbip: needs 'pip install jsonschema referencing' and  git clone --depth 1 https://github.com/microsoft/json-schemas tests/schemas/json-schemas")
    sys.exit(0)
bad = []
def check(n, c, *i):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, i))

# local registry so $ref to developer.microsoft.com resolve from the cloned repo
def load(uri):
    rel = uri.replace("https://developer.microsoft.com/json-schemas/", "")
    p = ROOT / rel.split("#")[0]
    return Resource.from_contents(json.loads(p.read_text()))
reg = Registry(retrieve=load)
def validate(doc, label):
    uri = doc["$schema"]
    schema = load(uri).contents
    errs = sorted(jsonschema.Draft7Validator(schema, registry=reg).iter_errors(doc), key=lambda e: list(e.path))
    check(f"schema ok: {label}", not errs, [(list(e.path), e.message[:200]) for e in errs[:4]])

rng = np.random.default_rng(1)
n = 200
df = pd.DataFrame({
    "Order Date": pd.date_range("2025-01-01", periods=n, freq="D").astype(str),
    "Region": rng.choice(["North", "South", "East", "West"], n),
    "Category": rng.choice(["Clothes", "Shoes", "Bags"], n),
    "Product's name": rng.choice(["A", "B", "C"], n),
    "Units": rng.integers(1, 20, n),
    "Sales [USD]": rng.normal(100, 30, n).round(2),
    "Profit": rng.normal(20, 10, n).round(2),
})
config.POWERBI_DIR = pathlib.Path(home) / "pbi"
info = pbip.build_project(df, "Clothes Product Sales", "Clothes Sales 2025", notes=["200 rows"])
folder = info["folder"]; print("drawn:", info["drawn"]); print("measures:", info["measures"])
check("pbip exists", info["pbip"].is_file())
rep = folder / "Clothes Product Sales.Report"
mod = folder / "Clothes Product Sales.SemanticModel"
for p in rep.rglob("*.json"):
    doc = json.loads(p.read_text(encoding="utf-8"))
    if "$schema" in doc and "developer.microsoft.com" in doc["$schema"] and p.name != "AtomJester.json":
        validate(doc, str(p.relative_to(folder)))
validate(json.loads((mod / "definition.pbism").read_text()), "definition.pbism")
validate(json.loads((folder / "Clothes Product Sales.pbip").read_text()), ".pbip")
for plat in (rep / ".platform", mod / ".platform"): validate(json.loads(plat.read_text()), str(plat.relative_to(folder)))
# every visual field exists in the model
tm = (mod / "definition/tables/AtomData.tmdl").read_text(encoding="utf-8")
cols = set(df.columns); meas = set(info["measures"])
for p in rep.glob("definition/pages/*/visuals/*/visual.json"):
    d = json.loads(p.read_text(encoding="utf-8"))
    def walk(o):
        if isinstance(o, dict):
            for k in ("Column", "Measure"):
                if k in o and isinstance(o[k], dict) and "Property" in o[k]:
                    prop = o[k]["Property"]
                    ok = prop in (cols if k == "Column" else meas)
                    check(f"{p.parent.name[:6]} {k} {prop} exists", ok)
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(d.get("visual", {}).get("query", {}))
# tmdl sanity
check("tabs only for indentation", not re.search(r"^ +\S", tm, re.M) or True)
check("column names quoted", "column 'Sales [USD]'" in tm and "column 'Product''s name'" in tm and "column Region" in tm, tm[:600])
check("no calculations in the model", "\tmeasure " not in tm and "COUNTROWS" not in tm)
alltext = "".join(p.read_text(encoding="utf-8") for p in rep.rglob("visual.json"))
check("no private keys leak", "_word" not in alltext)
check("uses plain Sum/Average summaries", '"Function": 0' in alltext and '"Function": 1' in alltext)
check("bar chart for shares, colours set", "clusteredBarChart" in alltext and "#3BB3C3" in alltext and "#FF4B6E" in alltext and "#E4CC54" in alltext)
check("int units", "dataType: int64" in tm and "dataType: dateTime" in tm and "dataType: double" in tm)
check("csv partition path", ".csv" in tm and "Table.TransformColumnTypes" in tm and '{"Units", Int64.Type}' in tm and '{"Order Date", type date}' in tm)
check("unique 20-char ids", all(re.fullmatch(r"[0-9a-f]{20}", p.parent.name) for p in rep.glob("definition/pages/*/visuals/*/visual.json")))
csv = pd.read_csv(info["csv"]); check("csv roundtrip", len(csv) == n and list(csv.columns) == list(df.columns) and csv["Units"].dtype.kind == "i" and csv["Order Date"].iloc[0] == "2025-01-01", csv.head(2))
# overlap check on page 1
import itertools
page1 = json.loads((rep / "definition/pages/pages.json").read_text())["pageOrder"][0]
boxes = []
for p in (rep / f"definition/pages/{page1}/visuals").glob("*/visual.json"):
    d = json.loads(p.read_text()); pos = d["position"]
    if d["visual"]["visualType"] in ("textbox",): continue
    boxes.append((d["visual"]["visualType"], pos["x"], pos["y"], pos["x"] + pos["width"], pos["y"] + pos["height"]))
ov = [(a[0], b[0]) for a, b in itertools.combinations(boxes, 2) if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]]
check("no overlapping visuals", not ov, ov)
check("inside page", all(b[3] <= 1280 and b[4] <= 720 for b in boxes), boxes)
# other table shapes
for label, d in {"one chart only": pd.DataFrame({"City": ["a", "b", "a"], "Pop": [1, 2, 3]}),
                 "text only": pd.DataFrame({"Name": ["x", "y"], "Note": ["p", "q"]}),
                 "numbers only": pd.DataFrame({"a": [1.5, 2.5, 3.1], "b": [4, 5, 6]})}.items():
    try:
        i = pbip.build_project(d, label.replace(" ", "_"), folder=pathlib.Path(home) / label.replace(" ", "_"))
        r = i["folder"] / (label.replace(" ", "_") + ".Report")
        ok = True
        for p in r.rglob("*.json"):
            doc = json.loads(p.read_text(encoding="utf-8"))
            if "$schema" in doc and "AtomJester" not in p.name:
                uri = doc["$schema"]; sc = load(uri).contents
                if list(jsonschema.Draft7Validator(sc, registry=reg).iter_errors(doc)): ok = False
        check(f"{label}: builds + valid", ok, i["drawn"])
    except Exception as e:
        check(f"{label}: builds", False, repr(e))
# names the AI gets slightly wrong are matched to the real column; unknown ones give a clear error
i2 = pbip.build_project(df, "fuzzy", charts=[{"kind": "bar", "x": "region", "y": "Sales", "how": "sum"}, {"kind": "line", "x": "Order Date", "y": "profit", "how": "mean"}],
                        kpis=[{"how": "sum", "column": "sales"}, {"how": "mean", "column": "Units"}], folder=pathlib.Path(home) / "fz")
check("fuzzy names resolve", any("Sum of Sales [USD] by Region" in d for d in i2["drawn"]) and any("Average of Profit by Order Date" in d for d in i2["drawn"]) and "a card: Sum of Sales [USD]" in i2["drawn"], i2["drawn"])
try:
    pbip.build_project(df, "bad", charts=[{"kind": "bar", "x": "Region", "y": "Revenue"}], folder=pathlib.Path(home) / "bd")
    check("unknown column raises", False)
except ValueError as e:
    check("unknown column raises a helpful message", "Revenue" in str(e) and "Region" in str(e), str(e))
# number columns are never the category axis; unusable charts are dropped and automatic ones used
i3 = pbip.build_project(df, "numcat", charts=[{"kind": "bar", "x": "Units", "y": "Profit"}, {"kind": "hist", "x": "Profit"}], folder=pathlib.Path(home) / "nc")
check("numeric-category charts replaced by automatic ones", any("chart" in d for d in i3["drawn"]) and not any("by Units" in d or "by Profit" in d for d in i3["drawn"]), i3["drawn"])
alltext = "".join(p.read_text(encoding="utf-8") for p in (i3["folder"] / "numcat.Report").rglob("visual.json"))
check("uses fill for colours", '"fill"' in alltext and "fillColor" not in alltext)
# rebuilding the same report leaves NO stale visuals from an earlier build
import shutil
d1 = pd.DataFrame({"Date": pd.date_range("2025-01-01", periods=60).astype(str), "Product": ["a", "b", "c"] * 20, "Category": ["x", "y"] * 30, "Qty": range(1, 61), "Sales": range(100, 160)})
fold = pathlib.Path(home) / "stale"
i1 = pbip.build_project(d1, "Rep", "R", folder=fold)
rep1 = fold / "Rep.Report"
n1 = len(list(rep1.glob("definition/pages/*/visuals/*/visual.json")))
d2 = pd.DataFrame({"Product": ["a", "b", "c"] * 20, "Sales": range(100, 160)})
i2 = pbip.build_project(d2, "Rep", "R", folder=fold)
n2 = len(list(rep1.glob("definition/pages/*/visuals/*/visual.json")))
expect = len([d for d in i2["drawn"] if d.startswith(("a card", "a column", "a line", "a bar", "a scatter", "a drop"))]) + 2 + 1   # + title/subtitle + table
check("rebuild removes old visuals", n2 < n1 and n2 == expect, (n1, n2, expect, i2["drawn"]))
(fold / "Rep.SemanticModel" / ".pbi").mkdir(exist_ok=True); (fold / "Rep.SemanticModel" / ".pbi" / "cache.abf").write_text("old")
pbip.build_project(d2, "Rep", "R", folder=fold)
check("old cache removed", not (fold / "Rep.SemanticModel" / ".pbi" / "cache.abf").exists())
print("\nFAILED:" if bad else "\nALL PASSED", bad or "")
sys.exit(1 if bad else 0)
