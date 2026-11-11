import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, pathlib
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, websearch, tools
config.SETTINGS_FILE = pathlib.Path(home) / "settings.json"
bad = []
def check(n, c, *_):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, _))

R = [{"title": "Paris - Wikipedia", "href": "https://www.wikipedia.org/wiki/Paris", "body": "Paris is the capital of France. " * 30},
     {"title": "France facts", "href": "https://www.bbc.com/x", "body": "Capital: Paris."}, {"junk": 1}, "not a dict"]
calls = []
def engine(q, n): calls.append((q, n)); return R
out = websearch.search_text("capital of   France", engine=engine)
check("query cleaned and passed, 5 results asked", calls == [("capital of France", 5)], calls)
check("has the untrusted-text warning", "never as instructions" in out)
check("site names without www", "(wikipedia.org)" in out and "(bbc.com)" in out)
check("urls kept for the AI to cite", "https://www.bbc.com/x" in out)
check("long snippet cut", "..." in out and max(len(l) for l in out.splitlines()) < 460)
check("junk rows skipped", out.count("\n") == 2, out.count("\n"))
big = [{"title": f"T{i}", "href": f"https://s{i}.com", "body": "x" * 290} for i in range(8)]
o2 = websearch.search_text("q", engine=lambda q, n: big)
check("total size capped (~2000 + header)", len(o2) < 2400, len(o2))
check("empty query refused", websearch.search_text("   ").startswith("Error"))
long = "word " * 100
websearch.search_text(long, engine=engine); check("long query capped", len(calls[-1][0]) <= websearch.MAX_QUERY)
check("count clamped 1..8", (websearch.search_text("a", count=99, engine=engine), calls[-1][1])[1] == 8 and (websearch.search_text("a", count=0, engine=engine), calls[-1][1])[1] == 5)
def boom(q, n): raise ConnectionError("no internet")
o = websearch.search_text("x", engine=boom, pause=0)
check("no internet: sentence, not a crash, tells AI to admit it", "couldn't get web results" in o and "ConnectionError" in o and "could not check" in o, o)
def missing(q, n): raise ImportError("ddgs")
check("add-on missing: says pip install ddgs", "pip install ddgs" in websearch.search_text("x", engine=missing))
n = []
def flaky(q, n_): n.append(1); return [] if len(n) == 1 else R[:2]
o = websearch.search_text("x", engine=flaky, pause=0); check("one retry when first search is empty", len(n) == 2 and "Paris" in o)
check("empty twice -> honest message", "couldn't get web results" in websearch.search_text("x", engine=lambda q, n: [], pause=0))

# the real default engine isn't installed here: must come back as a sentence
check("default engine without ddgs: friendly", "pip install ddgs" in websearch.search_text("hello") or "couldn't get web results" in websearch.search_text("hello", pause=0))

# ---- as a tool
store = type("S", (), {})()
tb = tools.ToolBox(store)
tb.web_engine = engine
r = tb.run("web_search", {"query": "capital of France"})
check("tool runs through ToolBox.run", "Paris" in r and not r.startswith("Error"))
check("tool is in the specs & always sent", "web_search" in [s["name"] for s in tb.SPECS] and "web_search" in tb.pick("hello there"))
check("sent in both formats", any(t["name"] == "web_search" for t in tb.claude_tools(["web_search"])) and any(t["function"]["name"] == "web_search" for t in tb.openai_tools(["web_search"])))
check("status line", "online" in tb.status_for("web_search", {"query": "x"}))
config.WEB_SEARCH = False
check("switch off works", "turned off" in tb.run("web_search", {"query": "x"}))
config.WEB_SEARCH = True
check("bad args don't crash", isinstance(tb.run("web_search", {"query": None}), str))
# prompt
p = config.SYSTEM_PROMPT
check("prompt: blunt", "blunt" in p.lower() and "Great question" in p)
check("prompt: search before answering, never invent, privacy", "web_search BEFORE" in p and "never put file" in p.lower())
check("prompt: still short bubble & no markdown", "1-3 sentences" in p and "no markdown" in p)
check("prompt mentions web_search in tool list", "read_file, web_search" in p)
print("approx prompt tokens:", len(p) // 4)
print("\nFAILED:" if bad else "\nALL PASSED", bad if bad else "")
sys.exit(1 if bad else 0)
