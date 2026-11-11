import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, types, json
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, tools, brain as B
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)
box = tools.ToolBox(None)
def names(text): return set(box.pick(text))
core = {"search_files", "list_files", "read_file", "web_search"}
check("plain question -> core only", names("who wrote the contract?") == core)
check("music", {"play_music", "music_control"} <= names("play ilomilo by billie eilish") and "make_chart" not in names("play ilomilo by billie eilish"))
check("open app", {"open_file", "open_app"} <= names("open excel") and "play_music" not in names("open excel"))
check("report", {"table_summary", "save_report"} <= names("Make a status report from all my files and save it as a document."))
check("data words", {"data_aggregate", "data_stats", "make_chart", "table_summary"} <= names("add the total sales and compare them"))
check("year alone triggers data", "data_aggregate" in names("what happened in 2025"))
check("spotify word opens music tools", "play_music" in names("spotify please"))
tokens = lambda n: len(json.dumps(box.openai_tools(box.pick(n)), separators=(",", ":"))) // 4
print("tokens: plain %d, music %d, report %d, analysis %d, ALL %d" % (
    tokens("hello"), tokens("play x"), tokens("status report"), tokens("total sales by year chart"), len(json.dumps(box.openai_tools(), separators=(",", ":"))) // 4))
check("plain request is small", tokens("hello") < 450)
check("filtering keeps schema valid", all(t["function"]["name"] in names("open excel") for t in box.openai_tools(box.pick("open excel"))))

# ---- rate limit parsing
class E(Exception): pass
def err(msg, retry=None, status=429):
    e = E(msg); e.status_code = status
    e.response = types.SimpleNamespace(headers={"retry-after": retry} if retry else {})
    return e
w = B.Brain._rate_limit_wait
check("header seconds", w(err("x", "7")) == 8)
check("message seconds", w(err("Rate limit. Please try again in 7.5s. Need more")) == 8.5)
check("message ms", abs(w(err("Please try again in 850ms.")) - 1.85) < 0.01)
check("long wait refused (daily limit)", w(err("Please try again in 12m3.2s")) is None)
check("minutes+seconds under limit not allowed >30", w(err("Please try again in 1m5s")) is None)
check("no info -> None", w(err("something else")) is None)

# ---- waiting and carrying on
b = B.Brain(types.SimpleNamespace(context_for=lambda t: "", describe=lambda: ""))
B.time.sleep = lambda s: slept.append(s)
slept, said = [], []
b._on_status = said.append
calls = []
def flaky():
    calls.append(1)
    if len(calls) < 3: raise err("Please try again in 3s")
    return "ok"
check("waits twice then succeeds", b._wait_if_rate_limited(flaky) == "ok" and len(calls) == 3 and slept == [4, 4] and "Waiting 4 seconds" in said[0])
calls.clear(); slept.clear()
def always():
    calls.append(1); raise err("Please try again in 3s")
try: b._wait_if_rate_limited(always); check("gives up after 3 tries", False)
except E: check("gives up after 3 tries", len(calls) == 3)
def other():
    raise err("bad key", status=401)
try: b._wait_if_rate_limited(other); check("other errors pass straight through", False)
except E: check("other errors pass straight through", True)
print("ALL PASSED" if not bad else bad)
