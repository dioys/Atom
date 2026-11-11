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

import os, tempfile, time
from pathlib import Path
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
import config
config.DATA_DIR = Path(home) / ".atom"; config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.SETTINGS_FILE = config.DATA_DIR / "settings.json"
import ui, brain as brain_mod, personality

bad = []
def check(n, c, *info):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, info))

# ---- fences
pc = brain_mod.Brain.plain_code
check("fences dropped, code kept", pc("```python\ncounter = 1\nwhile counter <= 10:\n    print(counter)\n    counter += 1\n```") ==
      "counter = 1\nwhile counter <= 10:\n    print(counter)\n    counter += 1")
check("plain text untouched", pc("Hello there.\nHow are you?") == "Hello there.\nHow are you?")
check("text around code kept", pc("Here:\n```\nx = 1\n```\nDone.") == "Here:\nx = 1\nDone.")
check("prompt asks for simple code", "simplest beginner-style" in config.SYSTEM_PROMPT and "no ``` fences" in config.SYSTEM_PROMPT)

# ---- a stand-in window
class Rec:
    def __init__(s): s.t = None; s.shown = False
    def set_text(s, t, follow=False): s.t = t
    def show(s): s.shown = True
class Tray:
    def __init__(s): s.msgs = []
    def showMessage(s, title, text, icon, ms): s.msgs.append(text)
ui.QSystemTrayIcon = types.SimpleNamespace(MessageIcon=types.SimpleNamespace(Information=0))

class Win:
    def __init__(s, history=(), held=False, tray=True, available=True):
        s._chat_held = held
        s.said = []; s.states = []
        s.say = lambda text, mood=None, spoken=False, live=False: s.said.append(text)
        s.character = types.SimpleNamespace(set_state=lambda m, ms=None, **k: s.states.append(m), state="idle")
        s.tray = Tray() if tray else None
        s.brain = types.SimpleNamespace(history=list(history), available=available)
        s.user_bubble, s.atom_bubble, s.user_row = Rec(), Rec(), Rec()
        s._holds_chat = lambda: ui.MainWindow._holds_chat(s)
        s._notify = lambda t: ui.MainWindow._notify(s, t)
        s._speak_up = lambda *a, **k: ui.MainWindow._speak_up(s, *a, **k)
        s._restore_last_chat = lambda: ui.MainWindow._restore_last_chat(s)

config.TRAY_NOTIFICATIONS = True; config.KEEP_LAST_CHAT = True
w = Win()
check("not held: he speaks up", ui.MainWindow._speak_up(w, "psst") is True and w.said == ["psst"])
w = Win(held=True)
check("held: idle remark is dropped, face reacts", ui.MainWindow._speak_up(w, "fun fact") is False and w.said == [] and w.states == ["curious"] and w.tray.msgs == [])
check("held + notify: pop-up instead of the chat box", ui.MainWindow._speak_up(w, "file changed", notify=True) is True and w.said == [] and w.tray.msgs == ["file changed"])
w = Win(held=True, tray=False)
check("held + notify + no tray: not delivered", ui.MainWindow._speak_up(w, "file changed", notify=True) is False and w.said == [])
config.KEEP_LAST_CHAT = False
w = Win(held=True)
check("KEEP_LAST_CHAT off: old behaviour", ui.MainWindow._speak_up(w, "psst") is True and w.said == ["psst"])
config.KEEP_LAST_CHAT = True

# ---- restore at start
hist = [{"role": "user", "content": "while loop 1 to 10"}, {"role": "assistant", "content": "counter = 1\nwhile counter <= 10:\n    print(counter)\n    counter += 1"}]
w = Win(history=hist)
check("restore puts the last chat back", ui.MainWindow._restore_last_chat(w) is True and w.atom_bubble.t.startswith("counter = 1") and w.user_bubble.t == "while loop 1 to 10" and w.user_row.shown and w._chat_held)
w = Win(history=[])
check("restore: nothing to restore", ui.MainWindow._restore_last_chat(w) is False and not w._chat_held)
w = Win(history=hist)
ui.MainWindow._welcome(w)
check("welcome shows the last chat, no hello", w.said == [] and w._chat_held and w.atom_bubble.t.startswith("counter"))
w = Win(history=hist, available=False)
w.brain.status_text = "no key"; w.brain.user_name = lambda: None; w.brain.last_talked = None
w.store = types.SimpleNamespace(all=lambda: [1])
ui.personality = personality
w.say = lambda text, mood=None, **k: w.said.append(text)
try:
    ui.MainWindow._welcome(w)
    check("no AI key: normal hello", len(w.said) == 1 and "no key" in w.said[0], w.said)
except Exception as e:
    check("no AI key: normal hello", False, repr(e))

# ---- idle tick does not write over the chat
import time as _t
w = Win(held=True)
w._busy = lambda: False; w._indexing = None; w.isVisible = lambda: True
w._last_activity = _t.monotonic() - 10_000; w._last_remark_at = -1e9; w._last_remark_text = None
w.character.state = "idle"
config.IDLE_SLEEP_SECONDS = 0
ui.MainWindow._idle_tick(w)
check("idle tick: chat untouched", w.said == [] and w.atom_bubble.t is None)
w2 = Win(held=False)
w2._busy = lambda: False; w2._indexing = None; w2.isVisible = lambda: True
w2._last_activity = _t.monotonic() - 10_000; w2._last_remark_at = -1e9; w2._last_remark_text = None
ui.MainWindow._idle_tick(w2)
check("idle tick: with no chat on show he still chats", len(w2.said) == 1)

# ---- wake
w = Win(held=True); w.character.state = "sleepy"; w._last_activity = 0
ui.MainWindow._wake(w)
check("wake: no words over the chat", w.said == [] and "happy" in w.states)

print("\n%d failed" % len(bad))
for n, i in bad: print(" -", n, i)
sys.exit(1 if bad else 0)
