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


import os, tempfile, pathlib
os.environ["HOME"] = tempfile.mkdtemp()
import numpy as np
import config
FakeTimer.isActive = lambda self: self.active
import ui, speaker, robot, personality

bad = []
def check(n, c, *i):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, i))

rate = 16000
def write(path, sec): robot.write_wav(pathlib.Path(path), 0.3 * np.sin(np.arange(int(rate * sec)) / 7), rate)
class Player:
    available = True
    def play(s, p): pass
    def stop(s): pass
def synth(text, out, voice, rate_, stop=None):
    time.sleep(0.06); write(out, 0.5); return True

def make(mode_ok=True, synth_fn=synth):
    spk = speaker.Speaker(); spk.mode = "boy"
    spk.boy = robot.Robot(Player(), synth_fn, pathlib.Path(os.environ["HOME"]) / "w"); spk.boy.configure("android")
    bubble = types.SimpleNamespace(texts=[], tag="", set_text=lambda t, b=None: b.texts.append(t) if False else None)
    texts = []
    bubble = types.SimpleNamespace(set_text=lambda t, follow=False: texts.append((time.monotonic(), t)), set_tag=lambda t: None)
    states = []
    char = types.SimpleNamespace(set_state=lambda *a, **k: states.append(a))
    timer = FakeTimer()
    fake = types.SimpleNamespace(speaker=spk, atom_bubble=bubble, character=char, _reveal_timer=timer, FEELING_MS=ui.MainWindow.FEELING_MS,
                                 speak_btn=types.SimpleNamespace(isChecked=lambda: True), _via_voice=False, _worker=None,
                                 _streaming_voice=False, raise_=lambda: None, input=types.SimpleNamespace(setFocus=lambda: None),
                                 _last_activity=0, _refresh_files=lambda: None)
    for name in ("_reset_reveal", "_finish_reveal", "_reveal_tick", "_on_chunk", "_on_partial", "_on_reply"):
        setattr(fake, name, types.MethodType(getattr(ui.MainWindow, name), fake))
    fake.say = lambda *a, **k: texts.append((time.monotonic(), "SAY:" + a[0]))
    fake._reset_reveal()
    return fake, texts, states, timer

def run(fake, timer, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if timer.active: fake._reveal_tick()
        time.sleep(0.02)

answer = "Sure, I opened it for you right now. The sales are up eleven percent this year, which is great. Want me to break it down by product?"
fake, texts, states, timer = make()
t0 = time.monotonic()
fake._streaming_voice = fake.speaker.begin_stream(lambda text, secs: fake._on_chunk(text, secs))
check("stream started", fake._streaming_voice)
fake._on_partial(answer)                    # a fast model: the whole answer arrives at once
check("nothing is dumped into the bubble while the voice is still preparing", texts == [], texts)
fake._on_reply(answer)
run(fake, timer, 0.5)
first = [t for t in texts if t[1]]
check("words start to appear when the voice starts", bool(first) and 0.05 < first[0][0] - t0 < 0.45 and len(first[0][1]) < len(answer) * 0.5, [(round(a - t0, 2), len(b)) for a, b in texts[:3]])
run(fake, timer, 2.5)
lens = [len(t[1]) for t in texts if not t[1].startswith("SAY")]
check("the text grows step by step", lens == sorted(lens) and len(set(lens)) > 8, lens[:12])
check("ends with the whole answer, shown in full", texts[-1][1] == answer, texts[-1])
check("it took about as long as he talks (3 sentences x 0.5 s)", 1.0 < texts[-1][0] - first[0][0] < 2.4, texts[-1][0] - first[0][0])
check("reveal over: timer stopped, flag reset", not timer.active and not fake._streaming_voice)
check("his mouth moves during sentences", any(s[0] == "talking" for s in states), states[:3])

# the voice fails entirely: the text must still appear
def broken(text, out, voice, rate_, stop=None): return False
fake, texts, states, timer = make(synth_fn=broken)
fake.speaker.boy.fallback = None
fake._streaming_voice = fake.speaker.begin_stream(lambda text, secs: fake._on_chunk(text, secs))
fake._on_partial(answer); fake._on_reply(answer)
run(fake, timer, 1.5)
check("voice broken: the full text still appears", texts and texts[-1][1] == answer, texts[-1:] )

# stopped halfway (new question): everything is shown at once
fake, texts, states, timer = make()
fake._streaming_voice = fake.speaker.begin_stream(lambda text, secs: fake._on_chunk(text, secs))
fake._on_partial(answer); fake._on_reply(answer)
run(fake, timer, 0.45)
fake.speaker.stop(); run(fake, timer, 0.2)
check("stopped: text completes immediately", texts[-1][1] == answer and not timer.active, texts[-1:])

# a long answer that is only partly spoken (voice limit) still ends with the full text
long = " ".join(f"This is sentence number {i} of a very long answer that goes on." for i in range(14))
fake, texts, states, timer = make()
old = config.SPEAK_MAX_CHARS; config.SPEAK_MAX_CHARS = 150
fake._streaming_voice = fake.speaker.begin_stream(lambda text, secs: fake._on_chunk(text, secs))
fake._on_partial(long); fake._on_reply(long)
run(fake, timer, 3.0); config.SPEAK_MAX_CHARS = old
check("long answer: full text at the end", texts[-1][1] == long, len(texts[-1][1]))

# warm_up does nothing without the voice files and never crashes
spk = speaker.Speaker(); spk.mode = "boy"; spk.warm_up(); check("warm_up is safe", True)
print("\nFAILED:" if bad else "\nALL PASSED", bad or ""); sys.exit(1 if bad else 0)
