import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, time, threading
sys.path.insert(0, SRC)
import config
tmp = tempfile.mkdtemp()
config.DATA_DIR = type(config.DATA_DIR)(tmp); config.LIBRARY_DIR = config.DATA_DIR / "library"; config.FILES_DB = config.DATA_DIR / "atom.db"
config.PROFILE_DB = config.DATA_DIR / "profile.db"; config.CALL_DB = config.DATA_DIR / "calls.db"
import tools, userprofile, callmode as cm

# ---------- requests: what the caller asks YOU to do
R = cm.find_requests
assert R("Can you send me the report by Friday?") == ["Send me the report by Friday"], R("Can you send me the report by Friday?")
assert R("Could you please update the slides before the meeting tomorrow?")[0].startswith("Update the slides")
assert R("I need you to fix the login bug by end of day.") == ["Fix the login bug by end of day"], R("I need you to fix the login bug by end of day.")
assert R("We'd like you to prepare a short demo for next week.")[0].startswith("Prepare a short demo")
assert R("Don't forget to email the client about the invoice.")[0].startswith("Email the client")
assert R("Send me the contract by Monday.") == ["Send me the contract by Monday"]
assert R("The proposal is due by Friday.") == ["The proposal is due by Friday"], R("The proposal is due by Friday.")
assert R("Let me know if you have any questions.") != []
# interview questions are NOT jobs
for q in ["Can you tell me about yourself?", "Could you explain how you handle deadlines?", "Can you walk me through your resume?",
          "Can you hear me?", "Can you see my screen?", "Tell me about a time you failed.", "What are your skills?", "How are you today?",
          "Can you describe your last project?", "Can you give me an example of teamwork?"]:
    assert R(q) == [], (q, R(q))

# ---------- questions / classification
C = cm.classify
assert C("Hi, thanks for joining. Can you tell me about yourself?") == ("question", "Can you tell me about yourself?")
assert C("What are your main skills?")[0] == "question"
assert C("Tell me about a time you worked in a team.")[0] == "question"
assert C("Describe your experience with SQL.")[0] == "question"
assert C("Can you hear me?")[0] == "smalltalk"
assert C("How are you doing today?")[0] == "smalltalk"
assert C("Do you have any questions for us?")[0] == "smalltalk"
assert C("Can you send me the report by Friday?")[0] == "request"
assert C("Great, that makes sense.")[0] == "statement"
assert C("We are a company of about two hundred people.")[0] == "statement"
assert C("Why do you want this job? And what is your expected salary?") == ("question", "And what is your expected salary?")
assert cm.quick_answer("Can you hear me okay?") == "Yes, I can hear you clearly."
assert cm.quick_answer("Tell me about yourself") is None
assert cm.needs_screen("Can you look at this code and tell me what's wrong?")
assert cm.needs_screen("As you can see on the slide, sales dropped.")
assert not cm.needs_screen("What are your strengths?")
assert cm.stall_answer("x") in cm._STALL
ctxq = cm.question_context("We use Power BI a lot. Do you know it?", "question", "Do you know it?")
assert ctxq == "We use Power BI a lot. Do you know it?", ctxq

# ---------- call log
log = cm.CallLog()
cid = log.start_call("interview")
log.add_line(cid, "them", "hello"); log.add_line(cid, "me", "hi")
assert log.lines(cid) == [("them", "hello"), ("me", "hi")] and log.lines(cid, 1) == [("me", "hi")]
assert log.add_task(cid, "Send me the report by Friday") is True
assert log.add_task(cid, "send me the report by friday!") is False          # duplicate
assert log.add_task(cid, "Send the report by Friday please") is False       # nearly the same
assert log.add_task(cid, "Book a second interview") is True
t = log.tasks(cid); assert [x[1] for x in t] == ["Send me the report by Friday", "Book a second interview"]
item, err = log.find_task(cid, "report"); assert item and not err
log.set_done(item[0]); assert log.tasks(cid, include_done=False)[0][1] == "Book a second interview"
assert "[x]" in log.tasks_text(cid)
assert "Nobody asked" in log.tasks_text(log.start_call())

# ---------- answers: always something
store = tools.FileStore(config.FILES_DB)
prof = userprofile.Profile(store)
a = cm.instant_answer("What are your skills?", prof); assert a.source == "stall" and a.text            # empty profile -> still answers
prof.add_many("Python, SQL and Power BI", "skill"); prof.add("2 years building reports for a logistics company", "experience")
a = cm.instant_answer("What are your skills?", prof); assert a.source == "profile" and "Python" in a.text and a.grounded
a = cm.instant_answer("Can you hear me?", prof); assert a.source == "quick"
a = cm.instant_answer("What's your favourite colour?", prof); assert a.source == "stall"
good = cm.ai_answer("What are your skills?", profile=prof, ask=lambda s, u: "**I work mostly with Python and SQL.**", who="Joyce")
assert good.text == "I work mostly with Python and SQL." and good.source == "ai" and good.grounded
seen = {}
def spy(system, user): seen["s"], seen["u"] = system, user; return "(not in your profile) Honestly I haven't used Rust yet, but I learn quickly."
na = cm.ai_answer("Do you know Rust?", profile=prof, ask=spy, who="Joyce", screen_text="fn main() {}", recent=[("them", "We use Rust."), ("me", "ok")])
assert not na.grounded and "Joyce" in seen["s"] and "PROFILE:" in seen["u"] and "fn main" in seen["u"] and "Them: We use Rust." in seen["u"]
assert cm.ai_answer("x", profile=prof, ask=lambda s, u: (_ for _ in ()).throw(RuntimeError("down"))) is None
assert cm.ai_answer("x", profile=prof, ask=None) is None
assert cm.tidy_answer("  Answer: \"Yes.\" ").text == "Yes."
assert cm.tidy_answer("   ") is None
sm, tk = cm.ai_summary(lambda s, u: "SUMMARY:\n- talked about the role\nTASKS:\n- Send portfolio by Monday\n- none", [("them", "send portfolio by monday")])
assert "role" in sm and tk == ["Send portfolio by Monday"], (sm, tk)
assert cm.ai_summary(None, [("them", "x")]) == ("", [])

# ---------- controller: the whole flow with fakes
events = {"lines": [], "tasks": [], "answers": [], "errors": [], "summary": []}
gate = threading.Event()
def slow_ai(system, user):
    gate.wait(3); return "I mainly use Python, SQL and Power BI in my work."
ctl = cm.CallController(cm.CallLog(), prof, ask=slow_ai, transcribe=lambda pcm, hint: pcm.decode(), who=lambda: "Joyce")
ctl.on_line = lambda s, t: events["lines"].append((s, t)); ctl.on_task = events["tasks"].append
ctl.on_answer = lambda q, a, final: events["answers"].append((q, a.source, a.text, final)); ctl.on_error = events["errors"].append
ctl.on_summary = events["summary"].append

class FakeListener:
    def __init__(s, c): s.c = c; s.started = s.stopped = False
    def start(s): s.started = True
    def stop(s): s.stopped = True
fl = []
ctl.start(lambda c: fl.append(FakeListener(c)) or fl)
assert ctl.active and fl[0].started
ctl.hear(b"Hi, thanks for joining. What are your main skills?", "them")
ctl.hear(b"Can you send me the report by Friday?", "them")
for _ in range(100):
    if len(events["lines"]) >= 2: break
    time.sleep(0.02)
time.sleep(0.1)
assert [t for t in events["tasks"]] == ["Send me the report by Friday"], events["tasks"]
first = events["answers"][0]; assert first[0].endswith("What are your main skills?") and first[1] == "profile" and first[3] is False, first   # instant answer, AI still thinking
gate.set()
for _ in range(100):
    if any(a[3] for a in events["answers"]): break
    time.sleep(0.02)
finals = [a for a in events["answers"] if a[3]]
# the first question's AI answer is old news by now (a second question came in), the second one is current
assert finals and finals[-1][0].startswith("Can you send me"), events["answers"]
ctl.handle_text("them", "Can you hear me?"); assert events["answers"][-1][1] == "quick" and events["answers"][-1][3] is True
ctl.handle_text("them", "Can you hear me?"); n = len(events["answers"]); ctl.handle_text("them", "Can you hear me?"); assert len(events["answers"]) == n   # not twice in a row
ctl.handle_text("me", "I'd be glad to."); assert events["lines"][-1] == ("me", "I'd be glad to.") and events["answers"][-1][0] != "I'd be glad to."
ctl.auto_answer = False; before = len(events["answers"]); ctl.handle_text("them", "Why do you want this job?"); assert len(events["answers"]) == before
ctl.ask_now("Why do you want this job?"); assert len(events["answers"]) == before + 1
cid = ctl.call_id
ctl.stop(wait=True)
assert fl[0].stopped and not ctl.active and events["summary"], events
call = ctl.log.call(cid); assert call["ended"] and call["summary"]
assert any("report" in t[1].lower() for t in ctl.log.tasks(cid))
assert [l for l in ctl.log.lines(cid) if l[0] == "them"][0][1].startswith("Hi, thanks")

# a transcription failure is reported once, not once per sentence
ctl2 = cm.CallController(cm.CallLog(), None, transcribe=lambda pcm, hint: (_ for _ in ()).throw(RuntimeError("no internet")))
errs = []; ctl2.on_error = errs.append
ctl2.start(lambda c: [])
for _ in range(3): ctl2.hear(b"x", "them")
time.sleep(0.3); ctl2.stop(wait=True)
assert len(errs) == 1 and "no internet" in errs[0], errs
# screen text only when asked about
screens = []
ctl3 = cm.CallController(cm.CallLog(), prof, ask=lambda s, u: "It looks like a null reference.", screen=lambda: screens.append(1) or "NullPointerException at line 4")
got = []; ctl3.on_answer = lambda q, a, f: got.append((a.text, f))
ctl3.call_id = ctl3.log.start_call()
ctl3.answer_async("Can you look at this error and tell me what it means?"); time.sleep(0.3)
assert screens == [1] and got[-1] == ("It looks like a null reference.", True), (screens, got)
ctl3.answer_async("What are your strengths?"); time.sleep(0.3); assert screens == [1]
print("CALLMODE OK")
