import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
"""Step 13: Brain.ask_once (no history, no tools) and the profile hint in normal chat. Fake AI clients, no network."""
import os, sys, tempfile, types
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, tools, brain as brain_mod
config.save_settings({"provider": "groq", "keys": {"groq": "gsk_test"}})
d = tempfile.mkdtemp(); open(f"{d}/cv.txt", "w").write("Skills: Python and SQL. Experience: two years of reporting.")
store = tools.FileStore(db_path=f"{home}/t.db"); store.add([f"{d}/cv.txt"])
fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

def chunk(content=None):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=content, tool_calls=None))])
class Comp:
    def __init__(s, script): s.script, s.calls = script, []
    def create(s, **req): s.calls.append(req); return iter(s.script.pop(0))
def make(script):
    comp = Comp(script); client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=comp))
    brain_mod.openai = types.SimpleNamespace(OpenAI=lambda **kw: client)
    return brain_mod.Brain(store), comp

b, comp = make([[chunk("I use "), chunk("Python daily.")], [chunk("Hi, I'm Joyce.")]])
check("brain has profile and call log", b.profile is not None and b.calls is not None and b.profile.ask == b.ask_once)
b.history = [{"role": "user", "content": "earlier chat"}, {"role": "assistant", "content": "earlier reply"}]
out = b.ask_once("You help in a call.", "What are your skills?")
req = comp.calls[0]
check("once: answer", out == "I use Python daily.")
check("once: only system + this question", [m["role"] for m in req["messages"]] == ["system", "user"] and req["messages"][1]["content"] == "What are your skills?")
check("once: no tools offered", "tools" not in req)
check("once: chat history untouched", len(b.history) == 2 and b.history[0]["content"] == "earlier chat")
check("once: memory untouched", b.memory is None or not any("skills" in t for _, _, t in b.memory.notes()))
# a normal chat afterwards still offers tools and keeps its history
b.reply("what is in my files")
check("normal chat still has tools", "tools" in comp.calls[1] and len(b.history) >= 3)

# the profile hint reaches the system prompt only when the question is about the user
b, comp = make([[chunk("ok")], [chunk("ok")]])
b.profile.add_many("Python, SQL", "skill")
check("hint: skills question", "Python" in b._system("what are my skills?").split("skills profile")[1])
check("hint: other question", "skills profile" not in b._system("how is the weather today"))
bb = make([[chunk('x')]])[0]; bb.profile.remove("python"); bb.profile.remove("sql")      # (the file is shared by both brains)
check("hint: not when profile empty", bb.profile.is_empty() and "skills profile" not in bb._system("what are my skills?"))

# no AI available: ask_once says so (callers fall back to the profile)
config.save_settings({}); b2, _ = make([[chunk("x")]])
try: b2.ask_once("s", "u"); check("once: no key -> error", False)
except RuntimeError as e: check("once: no key -> error", "No AI" in str(e))

# claude path: no history mixing, no tools
class Block(types.SimpleNamespace): pass
class FStream:
    def __init__(s): s.text_stream = iter(["Yes, ", "I can."])
    def __enter__(s): return s
    def __exit__(s, *a): return False
    def get_final_message(s): return types.SimpleNamespace(content=[Block(type="text", text="Yes, I can.")], stop_reason="end_turn")
class Msgs:
    calls = []
    def stream(s, **req): Msgs.calls.append(req); return FStream()
brain_mod.anthropic = types.SimpleNamespace(Anthropic=lambda **kw: types.SimpleNamespace(messages=Msgs()))
config.save_settings({"provider": "claude", "keys": {"claude": "sk-ant-test"}})
b3 = brain_mod.Brain(store); b3.history = [{"role": "user", "content": "old"}]
check("claude once: answer", b3.ask_once("sys", "question?") == "Yes, I can.")
check("claude once: clean request", Msgs.calls[0]["messages"] == [{"role": "user", "content": "question?"}] and "tools" not in Msgs.calls[0])
print("\nFAILED:" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
