import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
"""Logic tests for Step 3 (tool calling) using fake AI clients. No network, no window."""
import os
import sys
import tempfile
import types

home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)

import config  # noqa: E402
import tools  # noqa: E402
import brain as brain_mod  # noqa: E402

config.CONFIRM_ACTIONS = True  # these tests cover the Yes/No box
config.save_settings({"provider": "groq", "keys": {"groq": "gsk_test"}})

# --- sample files
d = tempfile.mkdtemp()
open(f"{d}/budget.txt", "w").write("Q3 budget: marketing 40000, travel overdue invoices 3.")
open(f"{d}/notes.txt", "w").write("Meeting notes about the launch plan.")
open(f"{d}/run.py", "w").write("print('hi')")
store = tools.FileStore(db_path=f"{home}/t.db")
store.add([f"{d}/budget.txt", f"{d}/notes.txt", f"{d}/run.py"])

opened = []
tools._open_path = lambda p: opened.append(("file", p.name))
tools._launch_app = lambda k: opened.append(("app", k))

fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- ToolBox
box = tools.ToolBox(store)
check("search finds budget", "budget.txt" in box.run("search_files", {"query": "overdue invoices"}))
check("read_file", "marketing" in box.run("read_file", {"name": "budget"}))
check("ambiguous name", "More than one" in box.run("read_file", {"name": "t"}))
check("missing file", "No added file" in box.run("read_file", {"name": "zzz"}))
check("unknown tool", box.run("format_disk", {}).startswith("Error"))
check("open w/o confirm refused", "no" in box.run("open_app", {"app": "excel"}).lower() and not opened)
box.confirm = lambda q: False
check("declined", "said no" in box.run("open_file", {"name": "budget.txt"}) and not opened)
box.confirm = lambda q: True
check("open file ok", box.run("open_file", {"name": "budget.txt"}).startswith("Opened") and opened[-1] == ("file", "budget.txt"))
check("blocked .py", "never open" in box.run("open_file", {"name": "run.py"}))
check("open app alias", box.run("open_app", {"app": "Microsoft Excel"}) == "Opened Excel." and opened[-1] == ("app", "excel"))
check("app not on list", "only open" in box.run("open_app", {"app": "cmd.exe"}))
check("schemas", len(box.claude_tools()) == 32 and box.openai_tools()[0]["type"] == "function")


# ------------------------------------------------- fake OpenAI-style client
def chunk(content=None, tool_calls=None):
    delta = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])


def tc(index, id=None, name=None, args=None):
    fn = types.SimpleNamespace(name=name, arguments=args)
    return types.SimpleNamespace(index=index, id=id, function=fn)


class FakeCompletions:
    def __init__(self, script, reject_tools=False):
        self.script, self.calls, self.reject_tools = script, [], reject_tools

    def create(self, **req):
        if self.reject_tools and "tools" in req:
            err = Exception("bad request")
            err.status_code = 400
            raise err
        self.calls.append(req)
        return iter(self.script.pop(0))


def make_brain(script, reject_tools=False):
    comp = FakeCompletions(script, reject_tools)
    client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=comp))
    brain_mod.openai = types.SimpleNamespace(OpenAI=lambda **kw: client)
    b = brain_mod.Brain(store)
    return b, comp


# round 1: model streams a tool call in 3 pieces; round 2: final answer
script = [
    [chunk(tool_calls=[tc(0, "c1", "open_app", "")]),
     chunk(tool_calls=[tc(0, None, None, '{"app":')]),
     chunk(tool_calls=[tc(0, None, None, '"excel"}')])],
    [chunk("Opening "), chunk("Excel for you.")],
]
b, comp = make_brain(script)
statuses, asked = [], []
opened.clear()
answer = b.reply("open excel", confirm=lambda q: asked.append(q) or True, on_status=statuses.append)
check("compat: answer", answer == "Opening Excel for you.")
check("compat: app opened", opened == [("app", "excel")])
check("compat: confirm asked", asked == ["Open Excel?"])
check("compat: status", statuses == ["Opening excel..."])
second = comp.calls[1]["messages"]
check("compat: tool msgs sent back", second[-2]["role"] == "assistant" and second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "c1")
check("compat: history only text", [m["role"] for m in b.history] == ["user", "assistant"])

# Gemini style: whole call in one chunk, no index, no id
script = [
    [chunk(tool_calls=[tc(None, "", "search_files", '{"query": "budget"}')])],
    [chunk("The budget file says marketing is 40000.")],
]
b, comp = make_brain(script)
answer = b.reply("what is the marketing budget")
check("gemini-style call", "40000" in answer and comp.calls[1]["messages"][-1]["role"] == "tool")

# user says no
script = [[chunk(tool_calls=[tc(0, "c9", "open_file", '{"name":"notes.txt"}')])], [chunk("Okay, I won't open it.")]]
b, comp = make_brain(script)
opened.clear()
b.reply("open notes", confirm=lambda q: False)
check("declined -> not opened", not opened and "said no" in comp.calls[1]["messages"][-1]["content"])

# model that rejects tools -> falls back to plain chat
script = [[chunk("Plain answer.")]]
b, comp = make_brain(script, reject_tools=True)
check("tools rejected -> plain answer", b.reply("hello there") == "Plain answer." and "groq" in b._no_tools)

# endless tool loop is stopped after MAX_TOOL_ROUNDS
loop = [[chunk(tool_calls=[tc(0, f"x{i}", "list_files", "{}")])] for i in range(config.MAX_TOOL_ROUNDS)]
loop.append([chunk("Done looping.")])
b, comp = make_brain(loop)
check("loop limit", b.reply("list") == "Done looping." and "tools" not in comp.calls[-1])


# --------------------------------------------------- fake Anthropic client
class Block(types.SimpleNamespace):
    def model_dump(self, **kw):
        return {k: v for k, v in self.__dict__.items()}


class FakeStream:
    def __init__(self, texts, content, stop):
        self.texts, self.content, self.stop = texts, content, stop
        self.text_stream = iter(texts)

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get_final_message(self): return types.SimpleNamespace(content=self.content, stop_reason=self.stop)


class FakeMessages:
    def __init__(self, streams): self.streams, self.calls = streams, []
    def stream(self, **req):
        self.calls.append(req)
        return self.streams.pop(0)


streams = [
    FakeStream(["Let me look."], [Block(type="text", text="Let me look."),
                                  Block(type="tool_use", id="tu1", name="read_file", input={"name": "budget.txt"})], "tool_use"),
    FakeStream(["It says ", "marketing is 40000."], [Block(type="text", text="x")], "end_turn"),
]
msgs = FakeMessages(streams)
client = types.SimpleNamespace(messages=msgs)
brain_mod.anthropic = types.SimpleNamespace(Anthropic=lambda **kw: client)
config.save_settings({"provider": "claude", "keys": {"claude": "sk-ant-test"}})
b = brain_mod.Brain(store)
answer = b.reply("what does budget say")
check("claude: final answer only", answer == "It says marketing is 40000.")
last = msgs.calls[1]["messages"][-1]
check("claude: tool_result sent", last["role"] == "user" and last["content"][0]["tool_use_id"] == "tu1" and "marketing" in last["content"][0]["content"])
check("claude: tools offered", "tools" in msgs.calls[0])

print("\nFAILED:" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
