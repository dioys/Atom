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
config.LIBRARY_DIR = config.DATA_DIR / "library"; config.FILES_DB = config.DATA_DIR / "atom.db"
config.SETTINGS_FILE = config.DATA_DIR / "settings.json"
import ui, callmode, screenreader, tools, userprofile, callpanel

bad = []
def check(n, c, *info):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, info))

# ---------------- screenreader: a picked picture
seen = {}
res = screenreader.read_screen(image="PICTURE", before=lambda: seen.setdefault("before", 1), ocr=lambda im: (seen.update(img=im) or "Write a while loop that prints 1 to 10"))
check("picked picture is read, nothing grabbed", res.ok and seen["img"] == "PICTURE" and "before" not in seen and "while loop" in res.text)
check("picked picture, no words", screenreader.read_screen(image="P", ocr=lambda im: "").error.startswith("I looked"))

# ---------------- callmode: one problem from the screen
asked = {}
def fake_ask(system, user):
    asked["system"], asked["user"] = system, user
    return "```python\ncounter = 1\nwhile counter <= 10:\n    print(counter)\n    counter += 1\n```\nIt counts up and prints each number."
answers = []
log = callmode.CallLog(Path(home) / "c.db")
ctl = callmode.CallController(log, None, ask=fake_ask, who=lambda: "Maria")
ctl.on_answer = lambda q, a, final: answers.append((q, a, final))
ctl.ask_screen("Tabs: Gmail YouTube\nPrint numbers 1 to 10 using a while loop and a counter\nSale! Get Photoshop")
for _ in range(50):
    if len(answers) >= 2: break
    time.sleep(0.05)
check("instant line then the real answer", len(answers) == 2 and answers[0][1].source == "screen" and answers[0][2] is False and answers[1][2] is True, answers)
check("answer keeps code, indentation and symbols", "    print(counter)" in answers[1][1].text and "<=" in answers[1][1].text and "```" not in answers[1][1].text, answers[1][1].text)
check("prompt says: one problem, ignore noise", "focus ONLY on the one question" in asked["system"] and "THE USER POINTED AT ONE PROBLEM" in asked["system"])
check("prompt carries the screen words", "Print numbers 1 to 10" in asked["user"] and "write the answer to the problem on the screen" in asked["user"].lower())
answers.clear()
ctl.ask_screen("Print numbers 1 to 10 using a while loop and a counter")
time.sleep(0.3)
check("asking again is allowed (screen text may differ)", len(answers) >= 1)
# a normal call question still uses the normal prompt
asked.clear(); answers.clear()
ctl.ask_now("Can you tell me about your skills?")
time.sleep(0.4)
check("normal question: normal prompt", "THE USER POINTED AT ONE PROBLEM" not in asked.get("system", "x") and "THE OTHER PERSON JUST SAID" in asked.get("user", ""))
check("panel label for screen answers", "problem you picked" in callpanel.source_label("screen"))

# ---------------- window logic on a stand-in
class Sig:
    def __init__(s): s.calls = []
    def emit(s, *a): s.calls.append(a)
class Btn:
    def __init__(s): s.checked = None
    def setChecked(s, v): s.checked = v
class Panel:
    def __init__(s, visible): s.visible = visible; s.problem = Sig(); s.status_changed = Sig()
    def isVisible(s): return s.visible
class Ctl:
    def __init__(s): s.active = False; s.screen = []
    def ask_screen(s, text): s.screen.append(text)
class Win:
    def __init__(s, visible=False, busy=False, calls=True):
        s.said = []; s.submitted = []
        s.say = lambda text, mood=None, **k: s.said.append(text)
        s._submit = lambda text, spoken=False, shown=None: s.submitted.append((text, shown))
        s._busy = lambda: busy
        s._call_panel = Panel(visible); s._call_ctl = Ctl()
        s._call_engine = lambda: s._call_ctl
        s.hear_btn = Btn()
        s.brain = types.SimpleNamespace(calls=object() if calls else None, profile=object() if calls else None)
        s.started = 0; s.stopped = 0; s.shown_call = 0
        s.start_call = lambda: (setattr(s, "started", s.started + 1), setattr(s._call_ctl, "active", True))
        s.stop_call = lambda: (setattr(s, "stopped", s.stopped + 1), setattr(s._call_ctl, "active", False))
        s.show_call = lambda: setattr(s, "shown_call", s.shown_call + 1)
        s._sync_hear_button = lambda: ui.MainWindow._sync_hear_button(s)

# picked text, no call window: goes to the chat, with a short stand-in in the bubble
w = Win(visible=False)
ui.MainWindow._on_picked_text(w, "Print 1 to 10 with a while loop", "")
check("picked text -> chat with focus instructions", len(w.submitted) == 1 and "Focus only on it" in w.submitted[0][0] and "while loop" in w.submitted[0][0] and w.submitted[0][1] == "(the problem you picked on the screen)", w.submitted)
# call window open: goes to the call engine
w = Win(visible=True)
ui.MainWindow._on_picked_text(w, "Q: what is 2+2", "")
check("picked text -> call window", w._call_ctl.screen == ["Q: what is 2+2"] and not w.submitted)
# problems
w = Win(visible=False); ui.MainWindow._on_picked_text(w, "", "need Tesseract")
check("read problem shown", w.said == ["need Tesseract"])
w = Win(visible=True); ui.MainWindow._on_picked_text(w, "", "")
check("empty box told to the panel", w._call_panel.problem.calls and "no readable text" in w._call_panel.problem.calls[0][0])
w = Win(busy=True); ui.MainWindow._on_picked_text(w, "text", "")
check("busy: asks to try again", "busy" in w.said[0] and not w.submitted)

# cancelled pick does nothing but restore Atom
w = Win(); restored = []
w._picker = object(); w._show_after_screen = lambda: restored.append(1)
ui.MainWindow._region_picked(w, None)
check("cancel: windows come back, no reading", restored == [1] and w._picker is None and not w.said)

# hear button
w = Win()
ui.MainWindow.toggle_hear(w)
check("hear: starts and shows the window", w.started == 1 and w.shown_call == 1 and w.hear_btn.checked is True)
ui.MainWindow.toggle_hear(w)
check("hear again: stops", w.stopped == 1 and w.hear_btn.checked is False)
w = Win(calls=False)
ui.MainWindow.toggle_hear(w)
check("hear when turned off: only the message", w.started == 0 and w.shown_call == 1 and w.hear_btn.checked is False)

# folders in the window
store = tools.FileStore(config.FILES_DB)
f1 = Path(home) / "a.txt"; f1.write_text("alpha"); f2 = Path(home) / "b.txt"; f2.write_text("beta")
store.add([f1, f2])
class W2:
    def __init__(s):
        s.store = store; s.said = []; s.refreshed = 0
        s.say = lambda text, mood=None, **k: s.said.append(text)
        s._refresh_files = lambda: setattr(s, "refreshed", s.refreshed + 1)
        s._index_queue = []; s._indexing = object()
        s._start_indexing = lambda: None
w2 = W2()
ui.MainWindow.move_files(w2, [str(f1)], "About me")
check("move_files", store.in_folder("About me")[0].name == "a.txt" and "Moved 1 file to About me" in w2.said[0] and "questions about you" in w2.said[0] and w2.refreshed == 1, w2.said)
ui.MainWindow.create_folder(w2, "Clients")
check("create_folder", "Clients" in store.folders() and "ready" in w2.said[-1])
ui.MainWindow.create_folder(w2, "   ")
check("create_folder: empty name told", "needs a name" in w2.said[-1])
ui.MainWindow.add_paths(w2, ["x"], "Reports")
check("add_paths remembers the folder", w2._index_queue == [(["x"], "Reports")], w2._index_queue)

# FilePanel list logic with stand-in widgets
class Combo:
    def __init__(s): s.items = []; s.idx = 0
    def blockSignals(s, v): pass
    def clear(s): s.items = []
    def addItem(s, label, data): s.items.append((label, data))
    def findData(s, d):
        for i, (_, data) in enumerate(s.items):
            if data == d: return i
        return -1
    def setCurrentIndex(s, i): s.idx = i
    def currentData(s): return s.items[s.idx][1] if s.items else ""
class ListW:
    def __init__(s): s.rows = []
    def clear(s): s.rows = []
    def addItem(s, item): s.rows.append(item)
class Lbl:
    def __init__(s): s.t = None; s.v = None
    def setText(s, t): s.t = t
    def setVisible(s, v): s.v = v
class B:
    def __init__(s): s.en = None
    def setEnabled(s, v): s.en = v
    def setMenu(s, m): pass
    def menu(s): return None
panel = types.SimpleNamespace(folder_box=Combo(), list=ListW(), heading=Lbl(), empty_hint=Lbl(), remove_btn=B(), move_btn=B(), clear_btn=B(), _records=[], _folders=[], ALL="All files")
panel.current_folder = lambda: callpanel_cf(panel)
def callpanel_cf(p):
    name = p.folder_box.currentData(); return name if name else None
panel._show_folder = lambda *_: ui.FilePanel._show_folder(panel)
class FakeItem:
    def __init__(s, text): s.text = text; s.data = {}
    def setData(s, role, v): s.data[role] = v
    def setToolTip(s, t): s.tip = t
ui.QListWidgetItem = FakeItem
ui.QMenu = lambda parent=None: types.SimpleNamespace(addAction=lambda *a: types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda f: None)), addSeparator=lambda: None)
ui.FilePanel.refresh(panel, store.all(), store.folders())
labels = [l for l, _ in panel.folder_box.items]
check("folder box lists all + folders with counts", labels[0] == "All files (2)" and "Work (1)" in labels and "About me (1)" in labels and "Reports (0)" in labels, labels)
check("all files shown first", len(panel.list.rows) == 2 and panel.heading.t == "Files (2)")
panel.folder_box.setCurrentIndex(panel.folder_box.findData("About me")); ui.FilePanel._show_folder(panel)
check("choosing a folder filters", len(panel.list.rows) == 1 and panel.list.rows[0].text.startswith("a.txt"))
check("new files go to the folder being looked at", callpanel_cf(panel) == "About me")
ui.FilePanel.refresh(panel, store.all(), store.folders())
check("selection kept after refresh", callpanel_cf(panel) == "About me")
panel.folder_box.setCurrentIndex(panel.folder_box.findData("Reports")); ui.FilePanel._show_folder(panel)
check("empty folder hint", panel.list.rows == [] and "Nothing in 'Reports'" in panel.empty_hint.t and panel.empty_hint.v is True and panel.clear_btn.en is True)

print("\n%d failed" % len(bad))
for n, i in bad: print(" -", n, i)
sys.exit(1 if bad else 0)
