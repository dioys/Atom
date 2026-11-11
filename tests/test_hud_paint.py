import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
"""Exercise the HUD drawing code with a recording painter (real Qt isn't in the sandbox)."""
import sys, math, runpy, types
sys.argv = ["x"]
ns = runpy.run_path(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "test_sprite_ui.py"))
import ui, config

calls = []
class Rec:
    def __getattr__(self, name):
        def f(*a, **k): calls.append((name, a)); return Rec()
        return f
class FM:
    def horizontalAdvance(self, t): return 6 * len(t)
    def elidedText(self, t, mode, w): return t[: max(0, w // 6)]
class FakePainter(Rec):
    def __init__(self, *a): pass
    def fontMetrics(self): return FM()
class Pt:
    def __init__(s, x=0, y=0): s.x_, s.y_ = x, y
class Rc:
    def __init__(s, x, y, w, h): s.x, s.y, s.w, s.h = x, y, w, h
    def left(s): return s.x
    def top(s): return s.y
    def right(s): return s.x + s.w
    def bottom(s): return s.y + s.h
class Poly(list): pass
class Col:
    def __init__(s, *a): pass
    def setAlpha(s, a): pass
class Lbl:
    def __init__(s): s.t = ""; s.w = 100
    def setWordWrap(s, v): pass
    def setTextFormat(s, v): pass
    def setFont(s, f): pass
    def setStyleSheet(s, v): pass
    def setText(s, t): s.t = t
    def setFixedWidth(s, w): s.w = w
    def setFixedHeight(s, h): s.h = h
    def font(s): return None
    def heightForWidth(s, w): return 18 * max(1, math.ceil(len(s.t) * 7 / max(w, 1)))
class Scr:
    def __init__(s, *a): s.g = None
    def __getattr__(s, n): return lambda *a, **k: Scr()
    def setGeometry(s, *a): s.g = a
    def verticalScrollBar(s): return types.SimpleNamespace(maximum=lambda: 100, setValue=lambda v: None)
class Metrics:
    def __init__(s, f): pass
    def horizontalAdvance(s, t): return 7 * len(t)

for name, val in dict(QPainter=FakePainter, QPointF=Pt, QRectF=Rc, QPolygonF=Poly, QColor=Col, QLabel=Lbl,
                      QScrollArea=Scr, QFontMetrics=Metrics, qcolor=lambda c, a=255: Col(),
                      hud_font=lambda *a, **k: None, QFont=lambda *a, **k: None).items():
    setattr(ui, name, val)
ui.QPen = lambda *a, **k: None
ui.QLinearGradient = lambda *a: Rec()
ui.QPainterPath = lambda: Rec()
ui.QTimer = ns["FakeTimer"]
class AnyAttr:
    def __getattr__(s, n): return AnyAttr()
    def __call__(s, *a, **k): return AnyAttr()
ui.random = __import__("random")
ui.QFrame = AnyAttr(); ui.Qt = AnyAttr(); ui.QFont = AnyAttr()
FakePainter.RenderHint = AnyAttr()
ui.hud_font = lambda *a, **k: AnyAttr()
ui.QWidget = ns["FakeWidget"]

FW = ns["FakeWidget"]
FW.setAttribute = lambda s, *a: None
FW.hide = lambda s: setattr(s, "_vis", False)
FW.show = lambda s: setattr(s, "_vis", True)
FW.setVisible = lambda s, v: setattr(s, "_vis", bool(v))
FW.isVisible = lambda s: getattr(s, "_vis", True)
FW.move = lambda s, x, y: None
FW.raise_ = lambda s: None
assert ui.IS_HUD and config.THEME == "hud"

# --- bubbles: full width, grow with text, scroll when long
atom = ui.Bubble("atom", config.HUD_BUBBLE_MAX)
atom.set_text("Hi")
assert atom.width() == 392, atom.width()
short_h = atom.height()
atom.set_text("word " * 400)
assert atom.width() <= 392 + 1 and atom.height() <= config.HUD_BUBBLE_MAX[1] + 2 * 10 + 17, (atom.width(), atom.height())
assert atom.height() > short_h
# quote line: your words go into Atom's box
box = atom
box.set_text("Hello there")
h0 = box.height()
q = ui._Quote(box); row = ui._QuoteRow(box)
q.set_text("  open   spotify \n and play dare ")
assert box._quote == "open spotify and play dare"
assert box.height() == h0, "hidden until shown"
row.show(); assert box._quote_on and box.height() == h0 + ui.Bubble.QUOTE
calls.clear(); box.paintEvent(None)
texts = [c[1][1] for c in calls if c[0] == "drawText"]
assert "YOU" in texts and "ATOM" in texts and any("INCOMING" in t for t in texts), texts
row.hide(); assert box.height() == h0
q2 = ui._Quote(box); q2.set_text(""); row.show(); assert not box._quote_on, "nothing to quote"

# typewriter: reveals gradually, box size does not change, ends with the full text, glitch settles
box.set_text("short")
box.type_text("A longer answer that types itself out slowly on screen.", cps=50)
full_h, full_w = box.height(), box.width()
assert box._typed == 0 and box._glitch == 8 and box._timer.active
shown = []
while box._timer.active:
    box._tick(); shown.append(len(box._shown()))
    assert box.height() == full_h and box.width() == full_w
assert shown == sorted(shown) and shown[0] < 10 and box._typed is None and box.label.t.endswith("on screen."), shown[:5]
assert box._glitch == 0
# the same text again (e.g. after streaming) does not retype
box.type_text("A longer answer that types itself out slowly on screen.", cps=50)
assert box._typed is None and not box._timer.active
# set_text during typing cancels it
box.type_text("Another one that is long enough to take a while to type.", 20)
box.set_text("stop"); assert not box._timer.active and box.label.t == "stop"
# classic look types nothing
ui.IS_HUD = True

# --- frame + listening badge, for every mood
config.CHARACTER = "jester"
char = ui.make_character()
frame = ui.HudFrame.__new__(ui.HudFrame)
ns["FakeWidget"].__init__(frame)
frame._size = (392, 330)
frame.character, frame.title = char, "ATOM // SAY ATOM"
frame._last_state = char.state; frame._glitch = 0
frame.badge = ui.ListeningBadge(char, frame)
for mood in ["idle","talking","thinking","listening","happy","laughing","proud","worried","sad","annoyed","surprised","curious","sleepy","looking"]:
    char.set_state(mood)
    calls.clear(); frame.paintEvent(None)
    texts = [c[1][1] for c in calls if c[0] == "drawText"]
    assert "ATOM // SAY ATOM" in texts and len(texts) >= 3, (mood, texts)
    expect = ui.HUD_TAGS[mood][0]
    assert expect in texts, (mood, texts)
    frame._tick()
    assert frame.badge.isVisible() == (mood == "listening") if hasattr(frame.badge, "isVisible") else True
badge = frame.badge
badge._size = (210, 46)
calls.clear(); badge.paintEvent(None)
assert [c[1][1] for c in calls if c[0] == "drawText"] == ["I'M LISTENING", "SPEAK NOW"]
assert sum(1 for c in calls if c[0] == "drawRect") == 6
frame.resizeEvent.__func__  # exists
# mood change makes the frame flicker, then it settles
char.set_state("idle"); frame._tick(); frame._glitch = 0
char.set_state("happy"); frame._tick()
assert frame._glitch == 6
calls.clear(); frame.paintEvent(None)
assert any(c[0] == "fillRect" for c in calls), "flicker bars drawn"
for _ in range(7): frame._tick()
assert frame._glitch == 0
calls.clear(); frame.paintEvent(None)
assert not any(c[0] == "fillRect" for c in calls)
print("hud paint ok")
