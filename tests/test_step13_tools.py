import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile
sys.path.insert(0, SRC)
import config
tmp = tempfile.mkdtemp()
D = type(config.DATA_DIR)
config.DATA_DIR = D(tmp); config.LIBRARY_DIR = config.DATA_DIR / "library"; config.FILES_DB = config.DATA_DIR / "atom.db"
config.PROFILE_DB = config.DATA_DIR / "profile.db"; config.CALL_DB = config.DATA_DIR / "calls.db"; config.DAILY_DB = config.DATA_DIR / "daily.db"
import tools, userprofile, callmode, daily, screenreader

store = tools.FileStore(config.FILES_DB)
cv = os.path.join(tmp, "joyce_cv.txt"); open(cv, "w").write("Skills: Python, SQL. Experience: 2 years reporting.")
store.add([cv])
tb = tools.ToolBox(store, profile=userprofile.Profile(store), calls=callmode.CallLog(), daily=daily.Daily())
assert len(tb.SPECS) == 32 and {"read_screen", "profile", "call_notes"} <= {s["name"] for s in tb.SPECS}
# every tool in a group exists, and the new groups pick the right tools
names = {s["name"] for s in tb.SPECS}
assert all(m in names for _, (_, members) in tb.TOOL_GROUPS.items() for m in members)
assert "profile" in tb.pick("what skills do I have?") and "profile" in tb.pick("use my CV")
assert "read_screen" in tb.pick("what's on my screen?") and "call_notes" in tb.pick("what did the interviewer ask me to do?")
assert "read_screen" not in tb.pick("open excel") and "profile" not in tb.pick("play some music")

# profile tool
assert "Nothing in your profile" in tb.run("profile", {"action": "show"})
assert "Added to your profile (skill): Python; SQL; Power BI" in tb.run("profile", {"action": "add", "text": "Python, SQL and Power BI"})
assert "already" in tb.run("profile", {"action": "add", "text": "Python"})
assert "now part of your profile" in tb.run("profile", {"action": "use_file", "file": "joyce_cv"})
assert "Could not do that" in tb.run("profile", {"action": "use_file", "file": "nothing.pdf"})
assert "joyce_cv.txt" in tb.run("profile", {"action": "show"})
tb.profile.ask = lambda system, user: "experience: 2 years reporting for a logistics company\nskill: Excel dashboards"
out = tb.run("profile", {"action": "learn"}); assert "saved 2 new fact(s)" in out, out
tb.profile.ask = None
assert "Could not do that" in tb.run("profile", {"action": "learn"})
assert "Removed 1" in tb.run("profile", {"action": "remove", "text": "excel dashboards"})
assert "no longer" in tb.run("profile", {"action": "drop_file", "file": "joyce"})
assert tools.ToolBox(store).run("profile", {"action": "show"}).startswith("Could not do that: the skills profile is turned off")

# call notes tool
assert "no call on record" in tb.run("call_notes", {})
cid = tb.calls.start_call("interview")
tb.calls.add_line(cid, "them", "Can you send me the report by Friday?"); tb.calls.add_line(cid, "me", "Sure.")
tb.calls.add_task(cid, "Send me the report by Friday"); tb.calls.add_task(cid, "Book a second interview")
assert "#1 [ ] Send me the report by Friday" in tb.run("call_notes", {"action": "tasks"})
assert "No summary" in tb.run("call_notes", {"action": "summary"}) or "no summary" in tb.run("call_notes", {"action": "summary"})
assert "Them: Can you send me" in tb.run("call_notes", {"action": "transcript"})
assert "Ticked off: Send me the report" in tb.run("call_notes", {"action": "done", "which": "report"})
assert "Could not do that" in tb.run("call_notes", {"action": "done", "which": "nothing like it"})
assert "Added 1 task(s)" in tb.run("call_notes", {"action": "add_todo"})
assert "Book a second interview" in tb.run("todo", {"action": "list"})
tb.calls.end_call(cid, "Talked about the role.")
assert "Talked about the role" in tb.run("call_notes", {"action": "summary"})

# read_screen tool
tb.screen_reader = lambda: screenreader.ScreenResult("Q1: What is a JOIN?", "ocr")
out = tb.run("read_screen", {"focus": "the question"}); assert "OCR" in out and "What is a JOIN" in out and "the question" in out
tb.screen_reader = lambda: screenreader.ScreenResult(error="I need the Tesseract program")
assert tb.run("read_screen", {}).startswith("Could not do that: I need the Tesseract")
print("STEP13 TOOLS OK")
