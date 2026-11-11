import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, time
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
os.environ["GROQ_API_KEY"] = "gsk_test"
sys.path.insert(0, SRC)
import config, memory, tools, brain as B
B.openai = object()  # pretend the package exists; the AI call itself is faked below
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)

# ---- Memory itself
m = memory.Memory(os.path.join(home, "m.db"))
check("new note saved", m.add_note("Project Orion is due 15 Dec", "deadline") == (True, "Project Orion is due 15 Dec"))
check("duplicate not added twice", m.add_note("project orion is due 15 dec")[0] is False)
m.add_note("Prefers short answers", "preference")
m.add_note("x", "nonsense-kind")
check("kinds fall back to fact", m.notes()[-1][1] == "fact")
check("notes_text lists them", "(deadline) Project Orion" in m.notes_text(900))
check("notes_text keeps newest when tight", m.notes_text(40).count("\n") == 0 and "- (fact) x" in m.notes_text(40))
check("forget by words", m.forget("orion") == 1 and all("Orion" not in t for _, _, t in m.notes()))
check("forget with no words does nothing", m.forget("") == 0)
for i in range(config.MAX_SAVED_MESSAGES + 30):
    m.add_message("user" if i % 2 == 0 else "assistant", f"message number {i} about budget")
check("old messages pruned", len(m.recent_messages(10000)) == config.MAX_SAVED_MESSAGES)
check("recent in order, newest last", m.recent_messages(2)[-1]["content"].endswith(str(config.MAX_SAVED_MESSAGES + 29) + " about budget"))
m.add_message("system", "hidden"); m.add_message("user", "   ")
check("bad role/empty ignored", all(x["content"] != "hidden" for x in m.recent_messages(5)))
check("recall finds a message", "message number 425" in m.recall("number 425 budget"))
check("recall nothing", m.recall("zebra giraffe") == "Nothing saved matches that.")
check("recall no query = latest", m.recall("").count("\n") == 5)
check("last message time set", abs(m.last_message_time() - time.time()) < 5)
check("clear messages", m.clear_messages() == config.MAX_SAVED_MESSAGES and m.recent_messages(5) == [])

# ---- tools
mem = memory.Memory(os.path.join(home, "t.db"))
box = tools.ToolBox(None, memory=mem)
check("remember tool", box.run("remember", {"note": "Boss is Anna", "kind": "fact"}).startswith("Saved: Boss is Anna"))
check("remember twice says known", "already knew" in box.run("remember", {"note": "boss is anna"}))
check("secrets refused", box.run("remember", {"note": "my password is hunter2"}).startswith("Not saved"))
check("card number refused", box.run("remember", {"note": "card 4111 1111 1111 1111"}).startswith("Not saved"))
check("empty note", box.run("remember", {"note": ""}).startswith("Error"))
check("recall tool sees note", "Boss is Anna" in box.run("recall", {"query": "anna"}))
check("forget tool", box.run("forget", {"what": "anna"}) == "Forgot 1 note.")
check("forget missing", box.run("forget", {"what": "anna"}) == "No saved note matches that.")
box.run("remember", {"note": "one"}); mem.add_message("user", "hi there")
check("forget everything", "Forgot everything" in box.run("forget", {"what": "Everything"}) and mem.notes() == [] and mem.recent_messages(3) == [])
nomem = tools.ToolBox(None)
check("no memory = polite error", nomem.run("remember", {"note": "a"}).startswith("Error"))
names = lambda t: set(box.pick(t))
check("remember word picks memory tools", {"remember", "forget", "recall"} <= names("remember that my deadline is Friday"))
check("memory tools not sent for small talk", "remember" not in names("hello there"))
check("yesterday picks memory", "recall" in names("what did we talk about yesterday"))
check("schemas valid", all(t["function"]["parameters"]["type"] == "object" for t in box.openai_tools(box.pick("remember this"))))
import json
check("recall schema has no required", json.dumps(box.claude_tools(["recall"])).count('"required": []') == 1)

# ---- brain: saves, restores after a "restart", puts notes in the prompt
seen = {}
def fake_ask(self, provider, system, on_text):
    seen["system"] = system; seen["history"] = list(self.history)
    return "Sure thing."
B.Brain._ask = fake_ask
store = tools.FileStore()
b1 = B.Brain(store)
check("starts empty", b1.history == [] and b1.memory is not None)
b1.memory.add_note("Prefers short answers", "preference")
b1.reply("My name is Delro and I like jazz")
b1.reply("What time is it?")
check("system prompt has date", "Now: " in seen["system"])
check("system prompt has notes", "(preference) Prefers short answers" in seen["system"])
check("two exchanges saved", len(b1.memory.recent_messages(10)) == 4)
b2 = B.Brain(store)  # restart
check("history restored after restart", [x["content"] for x in b2.history][:1] == ["My name is Delro and I like jazz"] and len(b2.history) == 4)
b2.reply("Do you remember my name?")
check("restored history reaches the AI", any("Delro" in x["content"] for x in seen["history"]))
check("prompt mentions earlier session", "earlier session" in seen["system"])
# a failed answer is not saved
def boom(self, provider, system, on_text): raise RuntimeError("network down")
B.Brain._ask = boom
before = len(b2.memory.recent_messages(100))
out = b2.reply("this will fail")
check("failed answer not saved", "couldn't reach" in out and len(b2.memory.recent_messages(100)) == before)
# restore never starts with an assistant message
b2.memory.clear_messages(); b2.memory.add_message("assistant", "orphan"); b2.memory.add_message("user", "u1"); b2.memory.add_message("assistant", "a1")
check("restored history starts with user", B.Brain(store).history[0]["role"] == "user")
# memory off
config.MEMORY = False
b3 = B.Brain(store)
B.Brain._ask = fake_ask
check("memory off: still replies", b3.memory is None and b3.reply("hi") == "Sure thing." and "Saved notes" not in seen["system"])
print("ALL PASSED" if not bad else bad)
