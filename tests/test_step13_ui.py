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

import os, tempfile, threading, time
from pathlib import Path
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
import config
config.DATA_DIR = Path(home) / ".atom"; config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.SETTINGS_FILE = config.DATA_DIR / "settings.json"
import ui, callpanel, callmode, speaker as speaker_mod

bad = []
def check(n, c, *info):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, info))

# ---- callpanel pure helpers
check("label: profile", callpanel.source_label("profile") == "from your profile")
check("label: ungrounded warns", "NOT in your profile" in callpanel.source_label("ai", False))
check("label: stall no warning", "NOT in" not in callpanel.source_label("stall", False))

# ---- speaker mute
sp = speaker_mod.Speaker.__new__(speaker_mod.Speaker)
sp.mode = "windows"; sp._tts = object(); sp.muted = False
check("speaker available when not muted", sp.available is True)
sp.muted = True
check("muted: not available", sp.available is False)
check("muted: say refuses", sp.say("hello") is False)
sp.mode = "boy"; sp.boy = types.SimpleNamespace(available=True)
check("muted: cannot stream", sp.can_stream() is False)

# ---- MainWindow call methods on a stand-in
class FakeSignal:
    def __init__(s): s.calls = []; s.slots = []
    def emit(s, *a): s.calls.append(a)
    def connect(s, f): s.slots.append(f)
class FakePanel:
    def __init__(s):
        s.problem = FakeSignal(); s.status_changed = FakeSignal(); s.running = None; s.began = 0
        s.auto = types.SimpleNamespace(isChecked=lambda: True)
    def begin_call(s): s.began += 1
    def set_running(s, v): s.running = v
class FakeLoop:
    pass
class FakeListener:
    def __init__(s): s.alive = True; s.started = False
    def start(s): s.started = True
    def stop(s): s.alive = False
    def is_alive(s): return s.alive

class Win:
    def __init__(s):
        s.said = []; s.speaker = types.SimpleNamespace(muted=False, stopped=0)
        s.speaker.stop = lambda: setattr(s.speaker, "stopped", s.speaker.stopped + 1)
        s._call_panel = FakePanel()
        log = callmode.CallLog(Path(home) / "c.db")
        s._call_ctl = callmode.CallController(log, None)
        s._call_engine = lambda: s._call_ctl
        s.say = lambda text, mood=None, spoken=False, live=False: s.said.append((text, spoken))
        s.screen_hide = FakeSignal(); s.screen_show = FakeSignal()
        s.brain = types.SimpleNamespace(profile=None, calls=log)
        s.stop_call = lambda: ui.MainWindow.stop_call(s)
        s._sync_hear_button = lambda: ui.MainWindow._sync_hear_button(s)

import loopback
made = []
def fake_listeners(controller, hear_me=None, source_factory=None):
    l = FakeListener(); made.append(l); return [l]
loopback.make_listeners = fake_listeners

w = Win()
ui.MainWindow.start_call(w)
check("start: muted", w.speaker.muted is True)
check("start: running", w._call_ctl.active and w._call_panel.running is True and w._call_panel.began == 1)
check("start: listener started", made and made[0].started)
check("start: told the user quietly", w.said and w.said[0][1] is False)
ui.MainWindow.stop_call(w)
check("stop: unmuted", w.speaker.muted is False)
check("stop: not running", not w._call_ctl.active and w._call_panel.running is False)

# audio that could not be opened: the window stops pretending to listen
made.clear(); w = Win()
ui.MainWindow.start_call(w)
made[0].alive = False
timers = []
ui.QTimer.singleShot = staticmethod(lambda ms, fn: timers.append(fn))
ui.MainWindow._on_call_problem(w, "no audio")
for fn in timers: fn()
check("dead listener -> call stopped and voice back", not w._call_ctl.active and w.speaker.muted is False)

# start failing must not leave him muted
def boom(c): raise RuntimeError("no device")
w = Win(); w._call_ctl.start = lambda *a, **k: boom(None)
ui.MainWindow.start_call(w)
check("start failure unmutes + reports", w.speaker.muted is False and w._call_panel.problem.calls and "no device" in w._call_panel.problem.calls[0][0])

# screen hiding
class Win2:
    def __init__(s):
        s.ops = []
        class Wd:
            def __init__(me, name): me.name = name
            def isVisible(me): return True
            def setWindowOpacity(me, v): s.ops.append((me.name, v))
        s._call_panel, s._profile_dialog = Wd("panel"), None
        s._screen_hidden = []
w2 = Win2(); w2.__class__.__bases__
me = types.SimpleNamespace(**{})
def hide(self):
    return ui.MainWindow._hide_for_screen(self)
class Self(Win2): pass
sf = Self()
class Main(Self):
    def isVisible(s): return True
    def setWindowOpacity(s, v): s.ops.append(("main", v))
m = Main()
ui.QApplication = types.SimpleNamespace(processEvents=lambda: None)
ui.MainWindow._hide_for_screen(m)
check("hide: both windows invisible", sorted(o for o in m.ops if o[1] == 0.0) == [("main", 0.0), ("panel", 0.0)], m.ops)
ui.MainWindow._show_after_screen(m)
check("show: restored", [o for o in m.ops if o[1] == 1.0] and m._screen_hidden == [], m.ops)

# read_screen_now uses the hide/show signals
import screenreader
seen = {}
def fake_read(before=None, after=None, **k):
    seen["b"], seen["a"] = before, after
    return screenreader.ScreenResult("hello world text")
screenreader.read_screen = fake_read
w = Win()
r = ui.MainWindow.read_screen_now(w)
check("read_screen_now passes hide/show", seen["b"] == w.screen_hide.emit and seen["a"] == w.screen_show.emit and r.ok)
w._call_panel.problem = FakeSignal()
screenreader.read_screen = lambda **k: screenreader.ScreenResult(error="no tesseract")
check("_screen_words error goes to panel", ui.MainWindow._screen_words(types.SimpleNamespace(read_screen_now=lambda: screenreader.ScreenResult(error="no tesseract"), _call_panel=w._call_panel)) == "" and w._call_panel.problem.calls == [("no tesseract",)])

# show_call / show_profile when turned off
w = Win(); w.brain = types.SimpleNamespace(profile=None, calls=None)
ui.MainWindow.show_call(w); ui.MainWindow.show_profile(w)
check("turned-off messages", len(w.said) == 2 and "turned off" in w.said[0][0] and "turned off" in w.said[1][0], w.said)

# ---- build the two windows with stand-in widgets: catches typos and wrong names in callpanel.py
import userprofile, tools as tools_mod
FakeWidget.__getattr__ = lambda self, n: _Any()      # the stand-in widget accepts any Qt call
panel = callpanel.CallPanel(None)
check("panel builds", hasattr(panel, "answer") and hasattr(panel, "tasks") and hasattr(panel, "heard"))
class Rec:
    def __init__(s): s.t = None; s.cleared = 0; s.lines = []
    def setPlainText(s, t): s.t = t
    def setText(s, t): s.t = t
    def appendPlainText(s, t): s.lines.append(t)
    def clear(s): s.cleared += 1
    def addItem(s, i): s.lines.append(i)
panel.answer, panel.asked, panel.source, panel.note, panel.status, panel.heard, panel.tasks = (Rec() for _ in range(7))
panel.start_btn = Rec()
panel._on_answer("what are your skills", "I work with Python.", "profile", True, False)
check("answer shown", panel.answer.t == "I work with Python." and "better answer" in panel.source.t and panel.asked.t.startswith("They asked"))
panel._on_answer("q", "x", "ai", False, True)
check("ungrounded warning", "NOT in your profile" in panel.source.t and "better answer" not in panel.source.t)
panel._on_line("them", "hello"); panel._on_line("me", "hi")
check("lines", panel.heard.lines == ["THEM: hello", "ME:   hi"], panel.heard.lines)
panel._on_problem("no sound"); panel._on_summary("- talked")
check("summary keeps the problem note", "no sound" in panel.note.t and "Summary:" in panel.note.t)
panel.begin_call(); panel._on_summary("- again")
check("new call clears old problem", "no sound" not in panel.note.t)
panel.set_running(True); check("button says stop", "Stop" in panel.start_btn.t)
panel.set_running(False); check("button says start", "Start" in panel.start_btn.t)
class Ctl: pass
c = Ctl(); panel.attach(c)
got = []
panel.answer_ready = types.SimpleNamespace(emit=lambda *a: got.append(a))
c.on_answer("q", callmode.Answer("t", "quick"), True)
check("attach routes answers", got == [("q", "t", "quick", True, True)], got)

store = tools_mod.FileStore(db_path=f"{home}/pd.db")
book = userprofile.Profile(store, Path(home) / "pd2.db")
dlg = callpanel.ProfileDialog(None, book)
check("profile dialog builds", hasattr(dlg, "facts") and hasattr(dlg, "files"))
dlg.message = Rec(); dlg.refresh = lambda: None
dlg.kind = types.SimpleNamespace(currentData=lambda: "skill")
dlg.new_fact = types.SimpleNamespace(text=lambda: "Python, Power BI, SQL", clear=lambda: None)
dlg._add_fact()
check("add several skills", [i.text for i in book.items("skill")] == ["Python", "Power BI", "SQL"], [i.text for i in book.items()])
first_id = book.items()[0].id
dlg.facts = types.SimpleNamespace(currentItem=lambda: types.SimpleNamespace(data=lambda role: first_id))
dlg._remove_fact()
check("remove a skill", [i.text for i in book.items()] == ["Power BI", "SQL"], [i.text for i in book.items()])
dlg.files = types.SimpleNamespace(currentItem=lambda: None)
dlg._remove_file(); check("remove file with nothing picked", "Click" in dlg.message.t)
dlg._learn(); check("learn without files", "Add a file first" in dlg.message.t)
cv = Path(home) / "cv.txt"; cv.write_text("Jane Doe\nSkills: Excel, Power BI, DAX\n3 years as data analyst\n")
ok, msg = book.pin(str(cv)); check("pin from any folder", ok, msg)
check("pinned file listed", [r.name for r in book.pinned()] == ["cv.txt"], book.pinned())

print("\n%d failed" % len(bad))
for n, i in bad: print(" -", n, i)
sys.exit(1 if bad else 0)
