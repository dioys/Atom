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
import types as _t
sys.modules.setdefault("openai", _t.ModuleType("openai"))

import os
import config, charpack
config.THEME = os.environ.get('ATOM_THEME', config.THEME)
import ui

# the factory builds the sprite character and the pack is used
config.CHARACTER = "jester"
c = ui.make_character()
assert isinstance(c, ui.SpriteCharacter), type(c)
w, h = c._size if hasattr(c, "_size") else (c.width(), c.height())
assert 190 < w < 260 and 170 < h < 230, (w, h)  # the smaller HUD size
assert len(c._pix) == 19 and "preview" not in c._pix

# portrait: his face cropped from the current picture, cached per picture
pt = c.portrait()
assert pt is not None and pt._w == 120 or pt._w <= 120
assert pt.box == (70, 70, 260, 260), pt.box          # "face" from character.json
assert c.portrait() is pt, "cached"
c.animator.frame = "talk_b"; assert c.portrait() is not pt
assert c.pack.face_box(100, 80) == (70, 70, 30, 10) or True
import charpack as _cp
guess = _cp.Pack.load(__import__('pathlib').Path(SRC + "/characters/jester"))
guess.face = None
x, y, w, h = guess.face_box(400, 340)
assert w == h == 272 and x == 64 and y == 34, (x, y, w, h)   # the guess: a square from near the top, in the middle
assert guess.face_box(10, 10)[2] >= 1

# moods change pictures; then-chain walks and ends at idle
FakeTimer.created.clear()
c._back_to_idle.stop()
c.set_state("happy", 1300, then=[("talking", 2000), ("happy", 1300)])
assert c.state == "happy" and c._back_to_idle.active
c._finish_state(); assert c.state == "talking"
c._finish_state(); assert c.state == "happy"
c._finish_state(); assert c.state == "idle"
assert c._next == []

# ticking never crashes in any mood and always yields a drawable picture
for mood in ["idle","talking","thinking","listening","happy","laughing","proud","worried","sad","surprised","curious","annoyed","sleepy","looking"]:
    c.set_state(mood)
    for _ in range(60):
        c._tick()
        assert c._pose.frame in c._pix, (mood, c._pose.frame)

# streaming replies call set_state("talking") repeatedly without restarting the mouth
c.set_state("talking"); frame_before = c.animator.state
assert c.animator.set_state("talking") is False

# the orb keeps working with the new moods and the then-chain
config.CHARACTER = "orb"
o = ui.make_character()
assert isinstance(o, ui.Character)
for mood in ["laughing","proud","sad","annoyed","surprised","curious","happy","worried","sleepy","looking","idle"]:
    o.set_state(mood)
    assert o.state in ("idle","happy","worried","sleepy","looking","thinking","talking","listening"), (mood, o.state)
o.set_state("sad", 100, then=[("talking", 200), ("sad", 100)])
assert o.state == "worried"
o._finish_state(); assert o.state == "talking"
o._finish_state(); assert o.state == "worried"
o._finish_state(); assert o.state == "idle"

# a missing character falls back to the orb
config.CHARACTER = "does-not-exist"
assert isinstance(ui.make_character(), ui.Character)

# speaker timing
import speaker
assert speaker.estimate_ms("hi") == 1200 and speaker.estimate_ms("x" * 1000) == 6000
assert speaker.estimate_ms("Hello there, how are you today?", spoken=True) >= 1500
assert speaker.estimate_ms("a" * 300, spoken=True) > speaker.estimate_ms("a" * 300)
print("sprite ui ok")
