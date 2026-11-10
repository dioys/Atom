"""pbip.py - Atom builds a whole Power BI report by himself, as files, and opens it in Power BI Desktop.

Power BI Desktop can't be remote-controlled (Microsoft offers no way to click or draw in it from outside),
but it opens a "Power BI Project" (.pbip): a folder of plain text files that describe the data model,
the report pages, every chart and the colours. Atom writes those files, so when Power BI opens them the
report is already designed. It follows Microsoft's published formats (TMDL for the model, PBIR for the report).

  build_project(df, stem, title, kpis, charts, notes)  ->  {"pbip": path, "folder": path, ...}

What he makes:  page "Overview" (title, a filter box, up to 4 number cards, up to 4 charts) and
page "Data" (the whole table), all in the jester's dark colours.

If Power BI says something is wrong when it opens the file, tell Atom's builder the message: the data
(a .csv) and the explanation are always saved next to it, so nothing is lost.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import config
import dashboard

TABLE = "AtomData"
PAGE_W, PAGE_H = 1280, 720
MARGIN, GAP = 32, 16
BG, PANEL, TEXT, MUTED = "#12060B", "#1C1216", "#FFF4EC", "#B79BA1"

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/"
S_PBIR = SCHEMA + "definitionProperties/2.0.0/schema.json"
S_REPORT = SCHEMA + "definition/report/2.0.0/schema.json"
S_VERSION = SCHEMA + "definition/versionMetadata/1.0.0/schema.json"
S_PAGES = SCHEMA + "definition/pagesMetadata/1.0.0/schema.json"
S_PAGE = SCHEMA + "definition/page/2.0.0/schema.json"
S_VISUAL = SCHEMA + "definition/visualContainer/2.0.0/schema.json"
S_PBISM = "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json"
S_PBIP = "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json"
S_PLATFORM = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"

# ------------------------------------------------------------------------------------------ small helpers


def _id(*parts) -> str:
    """A stable 20-character name for a page or visual (letters and digits only)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, "atom/" + "/".join(str(p) for p in parts)).hex[:20]


def _guid(*parts) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "atom-guid/" + "/".join(str(p) for p in parts)))


def tmdl_name(name: str) -> str:
    """A name as TMDL wants it: always in single quotes unless it is plain letters, digits and _."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return name
    return "'" + name.replace("'", "''") + "'"




def m_text(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def literal(value) -> dict:
    """A fixed value inside a visual's formatting ('text', 1D, true...)."""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, int):
        text = f"{value}L"
    elif isinstance(value, float):
        text = f"{value}D"
    else:
        text = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": text}}}


def solid(color: str) -> dict:
    return {"solid": {"color": literal(color)}}


def _write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(content, indent=2, ensure_ascii=False) if not isinstance(content, str) else content
    path.write_text(text, encoding="utf-8", newline="\n")


# ------------------------------------------------------------------------------------------ the data model


def column_types(df) -> dict:
    """{column: 'int64' | 'double' | 'dateTime' | 'string'} - what Power BI should treat each column as."""
    pd = dashboard._pd()
    kinds = dashboard.column_kinds(df)
    types = {}
    for c in df.columns:
        s = df[c]
        if c in kinds["dates"]:
            types[c] = "dateTime"
        elif pd.api.types.is_bool_dtype(s):
            types[c] = "string"
        elif pd.api.types.is_numeric_dtype(s):
            values = s.dropna()
            whole = len(values) > 0 and bool(((values % 1) == 0).all()) and float(values.abs().max()) < 2**53
            types[c] = "int64" if whole else "double"
        else:
            types[c] = "string"
    return types


class Measures:
    """The numbers the report needs. Row Count is a calculation in the model; every other number is a plain
    Power BI summary of a column (Sum, Average, ...), exactly like dragging the column into a visual."""

    NAMES = {"sum": "Sum of", "mean": "Average of", "min": "Lowest", "max": "Biggest", "median": "Median of",
             "count": "Count of", "distinct": "Different"}
    FUNCTION = {"sum": 0, "mean": 1, "distinct": 2, "min": 3, "max": 4, "count": 5, "median": 6}
    WORD = {"sum": "Sum", "mean": "Average", "distinct": "CountNonNull", "min": "Min", "max": "Max", "count": "Count",
            "median": "Median"}

    def __init__(self, types: dict, rows_column: str = ""):
        self.types = types
        self.items: dict[str, tuple[str, str]] = {}       # no calculations in the model at all: nothing there can go wrong
        self.rows_column = rows_column or next(iter(types), "")     # counting its filled-in cells counts the rows

    def get(self, how: str, column: str = "") -> tuple[dict, str]:
        """(the field to put in a visual, its plain name) for `how` of `column` ('' = count the rows)."""
        how = how if how in self.FUNCTION else "sum"
        if not column:
            return field_aggregate(self.FUNCTION["count"], self.rows_column, "Count", "Row Count"), "Row Count"
        kind = self.types.get(column, "string")
        if how in ("sum", "mean", "median") and kind not in ("int64", "double"):
            how = "distinct" if how == "sum" else "count"        # text can't be added up
        if how in ("min", "max") and kind == "string":
            how = "count"
        label = f"{self.NAMES[how]} {column}"
        return field_aggregate(self.FUNCTION[how], column, self.WORD[how], label), label


def semantic_model_files(df, types: dict, measures: Measures, csv_path: Path) -> dict:
    """{relative path: text} for the data model (TMDL)."""
    columns = list(df.columns)
    lines = [f"table {TABLE}", f"\tlineageTag: {_guid('table')}", ""]
    for name, (dax, fmt) in measures.items.items():
        lines += [f"\tmeasure {tmdl_name(name)} = {dax}", f"\t\tformatString: {fmt}", f"\t\tlineageTag: {_guid('measure', name)}", ""]
    for c in columns:
        kind = types[c]
        lines.append(f"\tcolumn {tmdl_name(c)}")
        lines.append(f"\t\tdataType: {kind}")
        if kind == "dateTime":
            lines.append("\t\tformatString: Short Date")
        elif kind == "int64":
            lines.append("\t\tformatString: 0")
        lines.append(f"\t\tlineageTag: {_guid('column', c)}")
        lines.append(f"\t\tsummarizeBy: {'sum' if kind in ('int64', 'double') else 'none'}")
        lines.append(f"\t\tsourceColumn: {c}")
        if kind == "dateTime":
            lines += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
        lines.append("")
    m_types = {"int64": "Int64.Type", "double": "type number", "dateTime": "type date", "string": "type text"}
    conversions = ", ".join("{" + f"{m_text(c)}, {m_types[types[c]]}" + "}" for c in columns)
    lines += [
        f"\tpartition {TABLE} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f"\t\t\t\t    Source = Csv.Document(File.Contents({m_text(str(csv_path))}), [Delimiter=\",\", Columns={len(columns)}, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),",
        "\t\t\t\t    #\"Promoted Headers\" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        f"\t\t\t\t    #\"Changed Type\" = Table.TransformColumnTypes(#\"Promoted Headers\", {{{conversions}}}, \"en-US\")",
        "\t\t\t\tin",
        "\t\t\t\t    #\"Changed Type\"",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return {
        "definition.pbism": json.dumps({"$schema": S_PBISM, "version": "4.0", "settings": {}}, indent=2),
        "definition/database.tmdl": "database\n\tcompatibilityLevel: 1567\n",
        "definition/model.tmdl": (
            "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n\n"
            f"annotation PBI_QueryOrder = [\"{TABLE}\"]\n\nref table {TABLE}\n"
        ),
        f"definition/tables/{TABLE}.tmdl": "\n".join(lines),
    }


# ------------------------------------------------------------------------------------------ the report


def field_column(column: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": TABLE}}, "Property": column}}




def field_aggregate(function: int, column: str, word: str, label: str = "") -> dict:
    inner = field_column(column)
    return {"Aggregation": {"Expression": inner, "Function": function}, "_word": word, "_label": label}


def projection(field: dict, active: bool = False) -> dict:
    if "Aggregation" in field:
        word = field["_word"]
        prop = field["Aggregation"]["Expression"]["Column"]["Property"]
        clean = {"Aggregation": field["Aggregation"]}
        label = {"Sum": "Sum of", "Average": "Average of", "Min": "Min of", "Max": "Max of", "Count": "Count of",
                 "CountNonNull": "Count of", "Median": "Median of"}[word]
        out = {"field": clean, "queryRef": f"{word}({TABLE}.{prop})", "nativeQueryRef": f"{label} {prop}"}
        if field.get("_label"):
            out["displayName"] = field["_label"]
    else:
        kind = "Column" if "Column" in field else "Measure"
        prop = field[kind]["Property"]
        out = {"field": field, "queryRef": f"{TABLE}.{prop}", "nativeQueryRef": prop}
    if active:
        out["active"] = True
    return out


def plain(field: dict) -> dict:
    """The field without Atom's private notes (what goes into a sort definition)."""
    return {k: v for k, v in field.items() if not k.startswith("_")}


def _container(position: dict, title: str = "", fill: bool = True) -> dict:
    """Formatting of the box around a visual: its dark panel, a thin edge and its title."""
    objects = {
        "background": [{"properties": {"show": literal(fill), "color": solid(PANEL), "transparency": literal(0.0)}}],
        "border": [{"properties": {"show": literal(fill), "color": solid("#2B1D22"), "radius": literal(8)}}],
        "title": [{"properties": (
            {"show": literal(True), "text": literal(title), "fontColor": solid(TEXT), "fontSize": literal(12.0),
             "bold": literal(True)} if title else {"show": literal(False)})}],
    }
    return objects


def visual_file(page: str, key: str, kind: str, position: dict, query: dict | None = None, title: str = "",
                objects: dict | None = None, fill: bool = True, z: int = 0) -> tuple[str, dict]:
    name = _id(page, key)
    visual = {"visualType": kind}
    if query:
        visual["query"] = query
    if objects:
        visual["objects"] = objects
    visual["visualContainerObjects"] = _container(position, title, fill)
    visual["drillFilterOtherVisuals"] = True
    body = {"$schema": S_VISUAL, "name": name, "position": {**position, "z": z, "tabOrder": z}, "visual": visual}
    return name, body


def _box(x, y, w, h) -> dict:
    return {"x": float(x), "y": float(y), "width": float(w), "height": float(h)}


def chart_slots(n: int, top: float, bottom: float) -> list[dict]:
    """Where the charts go: one wide, two side by side, one tall + two small, or a 2 x 2 grid."""
    width = PAGE_W - 2 * MARGIN
    height = bottom - top
    half_w = (width - GAP) / 2
    half_h = (height - GAP) / 2
    if n <= 1:
        return [_box(MARGIN, top, width, height)]
    if n == 2:
        return [_box(MARGIN, top, half_w, height), _box(MARGIN + half_w + GAP, top, half_w, height)]
    if n == 3:
        return [_box(MARGIN, top, half_w, height), _box(MARGIN + half_w + GAP, top, half_w, half_h),
                _box(MARGIN + half_w + GAP, top + half_h + GAP, half_w, half_h)]
    return [_box(MARGIN, top, half_w, half_h), _box(MARGIN + half_w + GAP, top, half_w, half_h),
            _box(MARGIN, top + half_h + GAP, half_w, half_h), _box(MARGIN + half_w + GAP, top + half_h + GAP, half_w, half_h)]


def _sort(field: dict, direction: str) -> dict:
    return {"sort": [{"field": plain(field), "direction": direction}], "isDefaultSort": True}


PINK, GOLD, TEAL, PURPLE = "#FF4B6E", "#E4CC54", "#3BB3C3", "#9B6BDC"
COLORS = [PINK, GOLD, TEAL, PURPLE, "#43B581", "#F2A33A", "#5B8CFF", "#FF8FA6"]


def axes() -> dict:
    """Quiet axis text and grid lines that suit the dark page."""
    return {
        "categoryAxis": [{"properties": {"labelColor": solid(MUTED), "showAxisTitle": literal(False)}}],
        "valueAxis": [{"properties": {"labelColor": solid(MUTED), "gridlineColor": solid("#3A2A30"),
                                      "showAxisTitle": literal(False)}}],
        "legend": [{"properties": {"labelColor": solid(MUTED)}}],
    }


def one_color(color: str) -> dict:
    return {"dataPoint": [{"properties": {"fill": solid(color)}}]}




def chart_visual(page: str, index: int, spec: dict, box: dict, measures: Measures, types: dict, z: int, df=None):
    """One chart from a spec like {'kind': 'bar', 'x': 'Region', 'y': 'Sales', 'how': 'sum'}. None if it can't be drawn.
    Number columns are never used as the category axis (Power BI refuses to group by a summed column)."""
    kind = spec.get("kind", "bar")
    x, y, how = spec.get("x", ""), spec.get("y", ""), spec.get("how", "sum")
    if x not in types or (kind != "scatter" and types[x] in ("int64", "double")):
        return None
    if y and y not in types:
        y = ""
    value, label = measures.get(how if y else "count", y)
    category = field_column(x)
    title = spec.get("title") or f"{label} by {x}"
    cat = {"projections": [projection(category, True)]}
    if kind in ("bar", "column", "hist"):
        query = {"queryState": {"Category": cat, "Y": {"projections": [projection(value)]}},
                 "sortDefinition": _sort(value, "Descending")}
        visual_type, objects = "clusteredColumnChart", {**one_color(PINK), **axes()}
    elif kind == "line":
        query = {"queryState": {"Category": cat, "Y": {"projections": [projection(value)]}}}
        if types[x] != "dateTime":
            query["sortDefinition"] = _sort(category, "Ascending")
        series = value["Aggregation"] if "Aggregation" in value else None
        objects = {**one_color(GOLD), **axes()}
        if series is not None:                     # colour THIS line (the series is named by its query reference)
            objects["dataPoint"][0]["selector"] = {"metadata": projection(value)["queryRef"]}
        visual_type = "lineChart"
    elif kind == "pie":                        # shares of a total: a sorted bar chart reads better than a donut
        query = {"queryState": {"Category": cat, "Y": {"projections": [projection(value)]}},
                 "sortDefinition": _sort(value, "Descending")}
        visual_type, objects = "clusteredBarChart", {**one_color(TEAL), **axes()}
    elif kind == "scatter":
        if not y or types.get(x) not in ("int64", "double") or types.get(y) not in ("int64", "double"):
            return None
        fx, lx = measures.get("mean", x)
        fy, ly = measures.get("mean", y)
        first = next((c for c, t in types.items() if t == "string"), "")
        state = {"X": {"projections": [projection(fx)]}, "Y": {"projections": [projection(fy)]}}
        if first:
            state["Category"] = {"projections": [projection(field_column(first), True)]}
        query = {"queryState": state}
        visual_type, objects = "scatterChart", {**one_color(TEAL), **axes()}
        title = spec.get("title") or f"{ly} vs {lx}"
    else:
        return None
    return visual_file(page, f"chart{index}", visual_type, box, query, title, objects, z=z)


def card_visual(page: str, index: int, field: dict, box: dict, z: int, accent: str = GOLD):
    state = {"Values": {"projections": [projection(field)]}}
    objects = {
        "labels": [{"properties": {"color": solid(TEXT), "fontSize": literal(30.0)}}],
        "categoryLabels": [{"properties": {"show": literal(True), "color": solid(MUTED), "fontSize": literal(11.0)}}],
    }
    name, body = visual_file(page, f"card{index}", "card", box, {"queryState": state}, "", objects, z=z)
    body["visual"]["visualContainerObjects"]["border"] = [{"properties": {
        "show": literal(True), "color": solid(accent), "radius": literal(8)}}]
    return name, body


def text_visual(page: str, key: str, text: str, box: dict, size: str, color: str, z: int, bold: bool = True):
    style = {"fontSize": size, "color": color, "fontFamily": "Segoe UI Semibold" if bold else "Segoe UI"}
    objects = {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": text, "textStyle": style}]}]}}]}
    return visual_file(page, key, "textbox", box, None, "", objects, fill=False, z=z)


def slicer_visual(page: str, column: str, box: dict, z: int):
    state = {"Values": {"projections": [projection(field_column(column), True)]}}
    objects = {
        "data": [{"properties": {"mode": literal("Dropdown")}}],
        "header": [{"properties": {"show": literal(False)}}],
    }
    return visual_file(page, "slicer", "slicer", box, {"queryState": state}, "", objects, z=z)


def table_visual(page: str, columns: list, box: dict, z: int):
    state = {"Values": {"projections": [projection(field_column(c), i == 0) for i, c in enumerate(columns)]}}
    return visual_file(page, "table", "tableEx", box, {"queryState": state}, "All the data", z=z)


def page_file(name: str, display: str) -> dict:
    return {
        "$schema": S_PAGE, "name": name, "displayName": display, "displayOption": "FitToPage",
        "height": PAGE_H, "width": PAGE_W,
        "objects": {
            "background": [{"properties": {"color": solid(BG), "transparency": literal(0.0)}}],
            "outspace": [{"properties": {"color": solid(BG), "transparency": literal(0.0)}}],
        },
    }


THEME = {
    "name": "Atom Jester",
    "dataColors": ["#FF4B6E", "#E4CC54", "#3BB3C3", "#9B6BDC", "#43B581", "#F2A33A", "#5B8CFF", "#FF8FA6"],
    "background": PANEL, "foreground": TEXT, "tableAccent": "#E4CC54",
    "good": "#43B581", "neutral": "#E4CC54", "bad": "#FF4B6E",
    "maximum": "#E4CC54", "center": "#FF8FA6", "minimum": "#B3122F",
    "firstLevelElements": TEXT, "secondLevelElements": "#D9C4C0", "thirdLevelElements": "#3A2A30",
    "fourthLevelElements": "#B79BA1", "secondaryBackground": "#2B1D22", "tertiaryBackground": "#3A2A30",
    "backgroundLight": "#2B1D22", "backgroundNeutral": "#3A2A30",
    "textClasses": {
        "label": {"fontFace": "Segoe UI", "color": TEXT}, "callout": {"fontFace": "Segoe UI Semibold", "color": TEXT},
        "title": {"fontFace": "Segoe UI Semibold", "color": TEXT}, "header": {"fontFace": "Segoe UI Semibold", "color": TEXT},
    },
}


# ------------------------------------------------------------------------------------------ deciding what is worth showing

_AVERAGE = re.compile(r"\b(price|rate|percent|percentage|score|rating|average|avg|margin|age)\b|%", re.I)


def _how(column: str) -> str:
    """Sums make sense for money and amounts, averages for prices, rates and scores."""
    return "mean" if _AVERAGE.search(column) else "sum"


def _uniques(df, column: str) -> int:
    return int(df[column].dropna().astype(str).str.strip().nunique())


def smart_plan(df, types: dict) -> dict:
    """Look at THIS table and pick only what is useful: {'kpis': [...], 'charts': [...], 'slicer': column or ''}.

    Nothing is added just to fill a slot. A card or chart is only planned when the data can really fill it:
      - cards:  the row count, the main amount (total), a second amount, an average, how many different groups
      - charts: the trend over time, the main amount per group, a second grouping, a second amount per group,
                two amounts compared per group
    A table with little in it simply gets a smaller report, and what is there grows to use the room."""
    kinds = dashboard.column_kinds(df)
    numbers = [c for c in kinds["numbers"] if c in types and _uniques(df, c) > 1]
    dates = [c for c in kinds["dates"] if c in types and _uniques(df, c) >= 3]
    cats = [c for c in kinds["categories"] if c in types and types[c] == "string" and 2 <= _uniques(df, c) <= 20]
    metric = dashboard.main_metric(numbers)
    second = next((c for c in numbers if c != metric), None)

    def cat_score(column):                      # the groups people care about most come first
        name = column.lower()
        for rank, word in enumerate(("product", "category", "item", "region", "branch", "store", "customer", "type", "name")):
            if word in name:
                return rank
        return 50 + _uniques(df, column)

    cats = sorted(cats, key=cat_score)
    first = cats[0] if cats else ""
    other = cats[1] if len(cats) > 1 else ""

    kpis = [{"how": "count", "column": ""}]
    if metric:
        kpis.append({"how": _how(metric), "column": metric})
        if second:
            kpis.append({"how": _how(second), "column": second})
        if _how(metric) == "sum" and len(df) > 1:
            kpis.append({"how": "mean", "column": metric})
    if first and len(kpis) < dashboard.MAX_KPIS:
        kpis.append({"how": "distinct", "column": first})

    charts = []
    value = {"y": metric, "how": _how(metric)} if metric else {"y": "", "how": "count"}
    if dates:
        charts.append({"kind": "line", "x": dates[0], **value})
    if first:
        charts.append({"kind": "bar", "x": first, **value})
    if other:
        charts.append({"kind": "pie" if _uniques(df, other) <= 12 else "bar", "x": other, **value})
    if first and second:
        charts.append({"kind": "bar", "x": first, "y": second, "how": _how(second)})
    if first and metric and second and len(charts) < dashboard.MAX_CHARTS and _uniques(df, first) >= 3:
        charts.append({"kind": "scatter", "x": metric, "y": second})
    if not charts and metric and cats:
        charts.append({"kind": "bar", "x": cats[0], **value})
    slicer = next((c for c in cats if 2 <= _uniques(df, c) <= 12), "")
    return {"kpis": kpis[:dashboard.MAX_KPIS], "charts": charts[:dashboard.MAX_CHARTS], "slicer": slicer}



def report_files(df, title: str, kpis: list, charts: list, measures: Measures, types: dict, notes: list,
                 slicer: str = "") -> tuple[dict, list]:
    """{relative path: content} of the report folder, and plain sentences about what was drawn."""
    files: dict = {}
    drawn: list[str] = []
    p1, p2 = _id("page", "overview"), _id("page", "data")

    visuals: list[tuple[str, dict]] = []
    z = 0
    visuals.append(text_visual(p1, "title", title, _box(MARGIN, 14, 820, 44), "26pt", TEXT, z)); z += 1
    sub = f"{len(df):,} rows"
    dates = dashboard.column_kinds(df)["dates"]
    if dates:
        span = dashboard._dates(df[dates[0]]).dropna()
        if len(span):
            sub += f" · {span.min():%d %b %Y} to {span.max():%d %b %Y}"
    sub += " · built by Atom"
    visuals.append(text_visual(p1, "subtitle", sub, _box(MARGIN, 56, 820, 26), "11pt", MUTED, z, bold=False)); z += 1
    slicer_col = slicer if slicer in types else ""
    if slicer_col:
        visuals.append(slicer_visual(p1, slicer_col, _box(PAGE_W - MARGIN - 300, 24, 300, 46), z)); z += 1
        drawn.append(f"a drop-down filter on {slicer_col}")

    # cards: only the ones that can show a number; they share the width evenly
    top = 96
    card_h = 100
    cards = []
    for kpi in kpis:
        how, column = kpi.get("how", "count"), kpi.get("column", "")
        if column and column not in types:
            continue
        field, label = measures.get(how, column)
        if all(label != known[1] for known in cards):
            cards.append((field, label))
    card_w = (PAGE_W - 2 * MARGIN - GAP * (len(cards) - 1)) / max(1, len(cards))
    for i, (field, label) in enumerate(cards):
        visuals.append(card_visual(p1, i, field, _box(MARGIN + i * (card_w + GAP), top, card_w, card_h), z, COLORS[(i + 1) % 4])); z += 1
        drawn.append(f"a card: {label}")

    # charts: only the ones the data can fill; they share the page evenly
    area_top = top + card_h + GAP
    dummy = _box(0, 0, 1, 1)

    def usable(specs):
        return [sp for i, sp in enumerate(specs) if chart_visual(p1, i, sp, dummy, measures, types, 0, df)]

    use = usable(charts) or usable(smart_plan(df, types)["charts"])
    slots = chart_slots(len(use), area_top, PAGE_H - MARGIN)
    for i, (spec, box) in enumerate(zip(use, slots)):
        made = chart_visual(p1, i, spec, box, measures, types, z, df)
        visuals.append(made); z += 1
        kind = {"bar": "column chart", "line": "line chart", "pie": "bar chart", "scatter": "scatter chart"}.get(spec.get("kind"), "column chart")
        drawn.append(f"a {kind}: {made[1]['visual']['visualContainerObjects']['title'][0]['properties']['text']['expr']['Literal']['Value'].strip(chr(39)).replace(chr(39) * 2, chr(39))}")

    for name, body in visuals:
        files[f"definition/pages/{p1}/visuals/{name}/visual.json"] = body
    files[f"definition/pages/{p1}/page.json"] = page_file(p1, "Overview")

    name, body = table_visual(p2, list(df.columns)[:14], _box(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN), 0)
    files[f"definition/pages/{p2}/visuals/{name}/visual.json"] = body
    files[f"definition/pages/{p2}/page.json"] = page_file(p2, "Data")
    drawn.append("a Data page with the whole table")

    files["definition/pages/pages.json"] = {"$schema": S_PAGES, "pageOrder": [p1, p2], "activePageName": p1}
    files["definition/version.json"] = {"$schema": S_VERSION, "version": "2.0.0"}
    files["definition/report.json"] = {
        "$schema": S_REPORT,
        "themeCollection": {
            "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": "5.61", "type": "SharedResources"},
            "customTheme": {"name": "AtomJester.json", "reportVersionAtImport": "5.61", "type": "RegisteredResources"},
        },
        "resourcePackages": [{
            "name": "RegisteredResources", "type": "RegisteredResources",
            "items": [{"name": "AtomJester.json", "path": "AtomJester.json", "type": "CustomTheme"}],
        }],
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True},
    }
    files["StaticResources/RegisteredResources/AtomJester.json"] = THEME
    return files, drawn


# ------------------------------------------------------------------------------------------ the project


def clear_old_build(model_dir: Path, report_dir: Path) -> None:
    """Remove what an earlier build of this report left behind. Without this, old charts and cards stay in the
    folder and Power BI shows them too (as empty "Something's wrong" panels), because the new report no longer
    has the calculations they used."""
    import shutil

    for folder in (model_dir / "definition", model_dir / ".pbi", report_dir / "definition",
                   report_dir / "StaticResources", report_dir / ".pbi"):
        if folder.exists():
            try:
                shutil.rmtree(folder)
            except OSError as error:
                raise ValueError("I can't replace the old report because Power BI still has it open. "
                                 "Close the report in Power BI (File > Close), then ask me again.") from error


def build_project(df, stem: str, title: str = "", kpis: list | None = None, charts: list | None = None,
                  notes: list | None = None, folder: Path | None = None) -> dict:
    """Write the whole project. Returns {'pbip', 'folder', 'csv', 'rows', 'columns', 'drawn', 'measures'}."""
    pd = dashboard._pd()
    clean = dashboard.clean_for_powerbi(df)
    if clean.empty or clean.shape[1] == 0:
        raise ValueError("There is no data to build a report from.")
    safe = re.sub(r"[^\w\- ]+", "", stem).strip() or "data"
    folder = Path(folder) if folder else config.POWERBI_DIR / safe
    folder.mkdir(parents=True, exist_ok=True)

    import analysis

    types = column_types(clean)
    plan = smart_plan(clean, types)
    kpis = (kpis or plan["kpis"])[:dashboard.MAX_KPIS]
    charts = (charts or plan["charts"])[:dashboard.MAX_CHARTS]
    # the AI may say "Total Sales" for the column "Total Sales (PHP)": find the real column, or say which exist
    kpis = [{**k, "column": analysis._col(clean, k["column"]) if k.get("column") else ""} for k in kpis]
    charts = [{**c, **{key: analysis._col(clean, c[key]) for key in ("x", "y") if c.get(key)}} for c in charts]
    title = title or safe.replace("_", " ").title()

    # the data, next to the project, as a plain CSV file Power BI reads
    data = clean.copy()
    for c, t in types.items():
        if t == "int64":
            data[c] = data[c].astype("Int64")
    csv_path = folder / f"{safe} data.csv"
    data.to_csv(csv_path, index=False, encoding="utf-8", date_format="%Y-%m-%d")

    rows_column = max(clean.columns, key=lambda c: int(clean[c].notna().sum()))
    measures = Measures(types, rows_column)
    files_r, drawn = report_files(clean, title, kpis, charts, measures, types, notes or [], plan["slicer"])
    model_dir = folder / f"{safe}.SemanticModel"
    report_dir = folder / f"{safe}.Report"
    clear_old_build(model_dir, report_dir)
    for rel, content in semantic_model_files(clean, types, measures, csv_path.resolve()).items():
        _write(model_dir / rel, content)
    _write(model_dir / ".platform", {"$schema": S_PLATFORM, "metadata": {"type": "SemanticModel", "displayName": safe},
                                      "config": {"version": "2.0", "logicalId": _guid("model", safe)}})
    for rel, content in files_r.items():
        _write(report_dir / rel, content)
    _write(report_dir / "definition.pbir", {"$schema": S_PBIR, "version": "4.0",
                                            "datasetReference": {"byPath": {"path": f"../{safe}.SemanticModel"}}})
    _write(report_dir / ".platform", {"$schema": S_PLATFORM, "metadata": {"type": "Report", "displayName": safe},
                                       "config": {"version": "2.0", "logicalId": _guid("report", safe)}})
    pbip = folder / f"{safe}.pbip"
    _write(pbip, {"$schema": S_PBIP, "version": "1.0", "artifacts": [{"report": {"path": f"{safe}.Report"}}],
                  "settings": {"enableAutoRecovery": True}})
    (folder / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
    return {"pbip": pbip, "folder": folder, "csv": csv_path, "rows": len(clean), "columns": list(clean.columns),
            "drawn": drawn, "measures": list(measures.items), "title": title}
