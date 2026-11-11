import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
"""Run ui.py's character code against stand-in Qt classes (the real Qt isn't in the sandbox)."""
import sys, types, time
sys.path.insert(0, SRC)

class _Any:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Any()
    def __call__(self, *a, **k): return _Any()
    def __mul__(self, o): return self
    def __or__(self, o): return self
    def __iter__(self): return iter(())

def _dummy(name):
    return type(name, (_Any,), {})

class FakeTimer:
    created = []
    def __init__(self, *a): self.interval = 0; self.cb = None; self.active = False; self.timeout = self; FakeTimer.created.append(self)
    def setInterval(self, v): self.interval = v
    def setSingleShot(self, v): pass
    def connect(self, cb): self.cb = cb
    def start(self, ms=None): self.active = True; self.ms = ms
    def stop(self): self.active = False
    def fire(self): self.active = False; self.cb()
    @staticmethod
    def singleShot(*a): pass

class FakePix:
    def __init__(self, path=None):
        self.p = path; self._w, self._h = 396, 340
        try:
            from PIL import Image as _I
            self._w, self._h = _I.open(path).size
        except Exception:
            pass
    def isNull(self): return False
    def height(self): return self._h
    def width(self): return self._w
    def size(self): return (self._w, self._h)
    def scaled(self, w, h, *a): q = FakePix(self.p); q._w, q._h = w, h; q.box = getattr(self, "box", None); return q
    def setDevicePixelRatio(self, r): pass
    def devicePixelRatio(self): return 1.0
    def copy(self, x, y, w, h): q = FakePix(self.p); q._w, q._h = w, h; q.box = (x, y, w, h); return q

class FakeWidget:
    def __init__(self, *a, **k): self._size = (0, 0)
    def setFixedSize(self, w, h): self._size = (w, h)
    def width(self): return self._size[0]
    def height(self): return self._size[1]
    def mapFromGlobal(self, p): return types.SimpleNamespace(x=lambda: 100, y=lambda: 100)
    def update(self): pass
    def devicePixelRatioF(self): return 1.0

def make_mod(name, **explicit):
    m = types.ModuleType(name)
    m.__getattr__ = lambda n: explicit.get(n) or _dummy(n)
    for k, v in explicit.items(): setattr(m, k, v)
    return m

class Signal:
    def __init__(self, *a): pass
    def __get__(self, o, t): return _Any()
core = make_mod("PySide6.QtCore", QTimer=FakeTimer, Signal=lambda *a: _Any(), Qt=_Any(), QPointF=_dummy("QPointF"), QRectF=_dummy("QRectF"), QThread=FakeWidget, QObject=FakeWidget, QUrl=_dummy("QUrl"))
gui = make_mod("PySide6.QtGui", QPixmap=FakePix, QCursor=types.SimpleNamespace(pos=lambda: None))
widgets = make_mod("PySide6.QtWidgets", QWidget=FakeWidget, QMainWindow=FakeWidget, QDialog=FakeWidget,
                   QApplication=types.SimpleNamespace(primaryScreen=lambda: None))
for n, m in {"PySide6": make_mod("PySide6"), "PySide6.QtCore": core, "PySide6.QtGui": gui, "PySide6.QtWidgets": widgets,
             "PySide6.QtMultimedia": make_mod("PySide6.QtMultimedia"), "PySide6.QtTextToSpeech": make_mod("PySide6.QtTextToSpeech"),
             "PySide6.QtNetwork": make_mod("PySide6.QtNetwork")}.items():
    sys.modules[n] = m

import os, tempfile
from datetime import datetime, date, timedelta
from pathlib import Path
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
import config
config.DATA_DIR = Path(home) / ".atom"; config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.SETTINGS_FILE = config.DATA_DIR / "settings.json"
import daily, timeparse, tools

bad = []
def check(n, c, *info):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, info))

now = datetime.now().replace(second=0, microsecond=0)
d = daily.Daily(Path(home) / "d.db")

# ---- reminders
r1 = d.add_reminder("call mom", now + timedelta(minutes=30))
r2 = d.add_reminder("send report", now - timedelta(minutes=5))
r3 = d.add_reminder("stand up", now - timedelta(days=1), "daily")
check("due = past ones only", [r.text for r in d.due(now)] == ["stand up", "send report"], [r.text for r in d.due(now)])
d.fire(r2.id, now); check("one-off finished", r2.id not in [r.id for r in d.reminders()])
d.fire(r3.id, now); nxt = [r for r in d.reminders() if r.id == r3.id][0]
check("daily moves to next time", nxt.due > now and (nxt.due - now) <= timedelta(days=1) and nxt.due.hour == r3.due.hour, nxt.due)
check("not due again", [r.id for r in d.due(now)] == [])
check("text", "call mom" in d.reminders_text(now) and "repeats daily" in d.reminders_text(now))
gone = d.cancel_reminder("mom"); check("cancel by words", gone.text == "call mom" and all(r.text != "call mom" for r in d.reminders()))
d.add_reminder("pay rent", now + timedelta(hours=2)); d.add_reminder("pay phone bill", now + timedelta(hours=3))
try: d.cancel_reminder("pay"); check("ambiguous cancel", False)
except ValueError as e: check("ambiguous cancel asks", "More than one" in str(e) and "#" in str(e), str(e))
try: d.cancel_reminder("zzz"); check("no match", False)
except ValueError as e: check("no match message", "No reminder matches" in str(e))
rid = [r for r in d.reminders() if r.text == "pay rent"][0].id
check("cancel by number", d.cancel_reminder(f"#{rid}").text == "pay rent")
try: d.add_reminder("  ", now); check("empty text", False)
except ValueError: check("empty text refused", True)
d.snooze(r3.id, 10, now); check("snooze", abs(([r for r in d.reminders() if r.id == r3.id][0].due - now).total_seconds() - 600) < 5)

# ---- todos
a, existed = d.add_todo("write budget", date.today() + timedelta(days=2)); check("todo added", not existed)
_, existed = d.add_todo("Write Budget"); check("duplicate noticed", existed)
d.add_todo("buy milk"); d.add_todo("renew passport", date.today() - timedelta(days=3))
texts = [t.text for t in d.todos()]
check("sorted: dated first, overdue first", texts == ["renew passport", "write budget", "buy milk"], texts)
check("todos text shows overdue", "OVERDUE" in d.todos_text() and "#" in d.todos_text())
check("done by words", d.complete_todo("milk").text == "buy milk" and len(d.todos()) == 2)
check("done by number", d.complete_todo(str(a.id)).text == "write budget")
try: d.complete_todo("milk"); check("already done not found", False)
except ValueError: check("already done not found", True)
check("remove", d.remove_todo("passport").text == "renew passport" and d.todos() == [])
check("clear done", d.clear_done() == 2)
check("empty list text", d.todos_text() == "The to-do list is empty.")

# ---- briefing
fresh = daily.Daily(Path(home) / "b.db")
check("empty briefing", "Nothing is scheduled" in fresh.briefing(now))
fresh.add_reminder("dentist", now.replace(hour=15, minute=0) if now.hour < 15 else now + timedelta(minutes=1))
fresh.add_reminder("old one", now - timedelta(days=2))
fresh.add_todo("file taxes", date.today() - timedelta(days=1)); fresh.add_todo("water plants")
text = fresh.briefing(now, ["sales.xlsx has 2 items past due, like Bob."])
print(text)
check("briefing parts", all(w in text for w in ("dentist", "slipped by", "2 open items", "1 overdue", "file taxes", "sales.xlsx")), text)
check("greeting by hour", fresh.briefing(now.replace(hour=8)).startswith("Good morning") and fresh.briefing(now.replace(hour=20)).startswith("Good evening"))

# ---- tools
box = tools.ToolBox(tools.FileStore(db_path=f"{home}/t.db"), daily=daily.Daily(Path(home) / "t.db2"))
run = box.run
r = run("reminder", {"action": "add", "text": "call the bank", "when": "tomorrow 9am"}); print(r)
check("tool: reminder set", r.startswith("Reminder set (#1)") and "tomorrow 9:00 AM" in r, r)
r = run("reminder", {"action": "add", "text": "stretch", "when": "every weekday 10am"}); check("tool: weekdays repeat", "repeating weekdays" in r, r)
r = run("reminder", {"action": "add", "text": "standup", "when": "9am", "repeat": "daily"}); check("tool: explicit repeat", "repeating daily" in r, r)
r = run("reminder", {"action": "add", "text": "x", "when": "blah blah"}); check("tool: bad time explained", r.startswith("Could not do that") and "couldn't understand" in r, r)
r = run("reminder", {"action": "add", "text": "x", "when": ""}); check("tool: needs a time", "I need a time" in r, r)
r = run("reminder", {"action": "add", "text": "x", "when": "2020-01-01 10:00"}); check("tool: past refused", "already passed" in r, r)
r = run("reminder", {"action": "add", "text": "", "when": "tomorrow 9am"}); check("tool: empty text", "what to remind" in r, r)
r = run("reminder", {"action": "list"}); check("tool: list", "#1" in r and "call the bank" in r, r)
r = run("reminder", {"action": "cancel", "text": "bank"}); check("tool: cancel", r.startswith("Cancelled reminder #1"), r)
r = run("todo", {"action": "add", "text": "email Ana", "due": "friday"}); check("tool: todo add with due", "Added to the list (#1)" in r and "due" in r, r)
r = run("todo", {"action": "add", "text": "email Ana"}); check("tool: dup", "already on the list" in r, r)
r = run("todo", {"action": "add", "text": "x", "due": "never-ever"}); check("tool: bad due", "couldn't understand the due date" in r, r)
r = run("todo", {"action": "list"}); check("tool: todo list", "email Ana" in r, r)
r = run("todo", {"action": "done", "text": "ana"}); check("tool: done", r.startswith("Ticked off"), r)
r = run("todo", {"action": "remove", "text": "nothing"}); check("tool: remove none", r.startswith("Could not do that"), r)
r = run("todo", {"action": "clear_done"}); check("tool: clear", "Cleared 1" in r, r)
r = run("todo", {"action": "wat"}); check("tool: bad action", "action must be" in r, r)
r = run("briefing", {}); check("tool: briefing", "Good" in r or "Nothing" in r, r)
lazy = tools.ToolBox(tools.FileStore(db_path=f"{home}/t2.db")); check("tool: lazy daily", lazy.daily is None and "No reminders" in lazy.run("reminder", {"action": "list"}))
names = {s["name"] for s in tools.ToolBox.SPECS}
check("specs", {"reminder", "todo", "briefing"} <= names and len(box.openai_tools()) == 32, len(box.openai_tools()))
check("pick: remind", "reminder" in box.pick("remind me to call mom tomorrow"))
check("pick: to-do", "todo" in box.pick("add buy milk to my to-do list") and "todo" in box.pick("what is on my todo"))
check("pick: unrelated has none", "reminder" not in box.pick("show sales by region"))
check("pick: briefing", "briefing" in box.pick("give me my briefing"))


# ---- snooze
sn = daily.Daily(Path(home) / "s.db")
try: sn.snooze("", 10); check("snooze before anything rang", False)
except ValueError as e: check("snooze before anything rang", "nothing to snooze" in str(e))
x = sn.add_reminder("take pills", now - timedelta(minutes=1)); sn.fire(x.id, now)
check("fired one is gone", sn.reminders() == [])
back = sn.snooze("", 15, now); check("snooze the one that just rang", back.id == x.id and abs((back.due - now).total_seconds() - 900) < 2 and len(sn.reminders()) == 1)
y = sn.add_reminder("meeting", now + timedelta(hours=2)); sn.snooze("meet", 30, now)
check("snooze by words", [r for r in sn.reminders() if r.id == y.id][0].due == now + timedelta(minutes=30))
check("snooze by number", sn.snooze(y.id, 5, now).due == now + timedelta(minutes=5))
rep = sn.add_reminder("daily thing", now - timedelta(minutes=1), "daily"); sn.fire(rep.id, now); sn.snooze(rep.id, 20, now)
check("repeat stays after snooze", [r for r in sn.reminders() if r.id == rep.id][0].repeat == "daily")
box2 = tools.ToolBox(tools.FileStore(db_path=f"{home}/t3.db"), daily=daily.Daily(Path(home) / "t3.db2"))
r = box2.run("reminder", {"action": "snooze"}); check("tool: snooze none", r.startswith("Could not do that"), r)
a = box2.daily.add_reminder("ring", now - timedelta(minutes=1)); box2.daily.fire(a.id, now)
r = box2.run("reminder", {"action": "snooze", "when": "15 minutes"}); check("tool: snooze last", r.startswith("Snoozed: 'ring'") and "again" in r, r)
r = box2.run("reminder", {"action": "snooze", "text": "ring"}); check("tool: snooze default 10 min", r.startswith("Snoozed"), r)

# ---- UI behaviour (stand-in Qt)
import ui
class Btn:
    def __init__(s, on): s.on = on
    def isChecked(s): return s.on
class Fake:
    def __init__(s, book, speak=False, busy=False):
        s.brain = types.SimpleNamespace(daily=book); s.said = []; s.tray_msgs = []; s.spoken = []; s._indexing = None
        s.speak_btn = Btn(speak); s.speaker = types.SimpleNamespace(available=True, say=lambda t: s.spoken.append(t))
        s._busy = lambda: busy; s._holds_chat = lambda: False; s._notify = lambda t: False; s.show_briefing = lambda: None; s.suggester = types.SimpleNamespace(overview_lines=lambda: ["f.xlsx has 1 item past due, like A."])
        s.say = lambda text, mood=None, spoken=False, live=False: s.said.append((text, mood, spoken))
        s._tell_hidden = lambda m: s.tray_msgs.append(m); s.shown = False; s.show_atom = lambda: setattr(s, "shown", True)
book = daily.Daily(Path(home) / "u.db")
book.add_reminder("water the plants", datetime.now() - timedelta(seconds=30))
book.add_reminder("old thing", datetime.now() - timedelta(hours=3))
book.add_reminder("later", datetime.now() + timedelta(hours=1))
f = Fake(book, speak=True, busy=True); ui.MainWindow._check_reminders(f)
check("ui: busy -> waits, nothing lost", f.said == [] and len(book.due()) == 2)
f = Fake(book, speak=True); ui.MainWindow._check_reminders(f)
check("ui: shows one reminder, speaks it, tray note", len(f.said) == 1 and f.said[0][0].startswith("Reminder") and f.spoken and f.tray_msgs, f.said)
check("ui: one-off shows the snooze hint, voice does not read it", "snooze" in f.said[0][0] and all("snooze" not in t for t in f.spoken))
ui.MainWindow._check_reminders(f)
check("ui: next tick shows the next one", len(f.said) == 2 and any("it was for" in t for t, *_ in f.said), f.said)
ui.MainWindow._check_reminders(f); check("ui: nothing left", len(f.said) == 2 and len(book.reminders()) == 1)
f = Fake(book, speak=False); book.add_reminder("silent", datetime.now() - timedelta(seconds=5)); ui.MainWindow._check_reminders(f)
check("ui: no voice when speaker is off", f.said and not f.spoken)

b2 = daily.Daily(Path(home) / "v.db"); b2.add_todo("pack bag")
f = Fake(b2); ui.MainWindow.show_briefing(f, True)
check("ui: forced briefing says it and shows window", f.said and "pack bag" in f.said[0][0] and "f.xlsx" in f.said[0][0] and f.shown and "last_briefing" not in config.load_settings())
f = Fake(b2); ui.MainWindow.show_briefing(f)
hour = datetime.now().hour
if hour >= config.BRIEFING_FROM_HOUR:
    check("ui: first start of day -> briefing + remembered", f.said and config.load_settings().get("last_briefing") == date.today().isoformat())
    f = Fake(b2); ui.MainWindow.show_briefing(f); check("ui: only once a day", f.said == [])
else:
    check("ui: too early -> no briefing", f.said == [])
config.save_settings({}); f = Fake(b2, busy=True); ui.MainWindow.show_briefing(f); check("ui: busy -> briefing waits", f.said == [])
f = Fake(None); ui.MainWindow._check_reminders(f); ui.MainWindow.show_briefing(f); check("ui: no daily file -> quiet", f.said == [])
print("FAILED:" if bad else "ALL PASSED", bad)
