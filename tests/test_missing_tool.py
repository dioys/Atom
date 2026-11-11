import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, pathlib
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, brain, tools
config.SETTINGS_FILE = pathlib.Path(home) / "settings.json"
bad = []
def check(n, c, *i):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, i))
MSG = "Error code: 400 - {'error': {'message': \"Tool call validation failed: attempted to call tool 'export_powerbi' which was not in request.tools\", 'type': 'invalid_request_error'}}"
class E(Exception):
    status_code = 400
store = tools.FileStore(db_path=f"{home}/t.db")
b = brain.Brain(store)
b._tool_names = b.tools.pick("the 2025 one")
check("follow-up message gets only core tools", "export_powerbi" not in b._tool_names, b._tool_names)
calls = []
def flaky(provider, model, system, on_text):
    calls.append(list(b._tool_names or []))
    if len(calls) == 1: raise E(MSG)
    return "done"
b._ask_compatible = flaky
check("retries with the missing tool added", b._call_model("groq", "m", "s", None) == "done" and "export_powerbi" in calls[1] and "export_powerbi" not in calls[0], calls)
# unknown tool name -> all tools
b._tool_names = ["list_files"]; calls.clear()
def flaky2(provider, model, system, on_text):
    calls.append(b._tool_names)
    if len(calls) == 1: raise E("tool call validation failed: attempted to call tool 'zzz_unknown' which was not in request.tools")
    return "ok"
b._ask_compatible = flaky2
check("unknown name -> every tool sent", b._call_model("groq", "m", "s", None) == "ok" and calls[1] is None)
# never loops forever
b._tool_names = []
def always(provider, model, system, on_text): raise E(MSG)
b._ask_compatible = always
try: b._call_model("groq", "m", "s", None); ok = False
except E: ok = True
check("gives up after a few tries and raises", ok)
# other errors are untouched
def other(provider, model, system, on_text): raise E("400 something else")
b._ask_compatible = other; b._tool_names = []
try: b._call_model("groq", "m", "s", None); ok = False
except E: ok = True
check("other errors pass through immediately", ok)
check("_allow_tool false for unrelated errors", b._allow_tool(Exception("rate limit")) is False)
# _open_stream: the error is NOT treated as "this model can't do tools"
class Chat:
    class completions:
        @staticmethod
        def create(**kw): raise E(MSG)
class Client: chat = Chat
b._tool_names = []; b._no_tools = set()
try: b._open_stream(Client(), "groq", "m", [], True); ok = False
except E: ok = True
check("tool error is re-raised, tools are not switched off for good", ok and "groq" not in b._no_tools)
# sticky tools
b2 = brain.Brain(store)
b2._on_status = None
b2._run_tool("export_powerbi", {"name": "nothing"})
check("used tools remembered", b2._used_tools == ["export_powerbi"])
b2.available  # property
import types
seen = []
b2._ask = lambda provider, system, on_text: seen.append(list(b2._tool_names)) or "hi"
b2.__class__.available = property(lambda self: True)
b2.reply("the 2025 one")
check("next question gets the tool used before", "export_powerbi" in seen[0], seen)
b2.reply("thanks")
check("...but only for one follow-up", "export_powerbi" not in seen[1], seen)
print("\nFAILED:" if bad else "\nALL PASSED", bad or "")
sys.exit(1 if bad else 0)
