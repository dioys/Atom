import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
"""Exercise the plate look's layout and drawing with a recording painter."""
import sys, math, runpy, time
sys.argv = ["x"]
ns = runpy.run_path(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "test_sprite_ui.py"))
import ui, config
assert ui.IS_PLATE and ui.IS_HUD, config.THEME

calls = []
class Rec:
    def __getattr__(self, name):
        def f(*a, **k): calls.append((name, a)); return Rec()
        return f
class FM:
    def horizontalAdvance(self, t): return 6 * len(t)
    def elidedText(self, t, mode, w): return t[: max(0, int(w) // 6)]
class Painter(Rec):
    def __init__(self, *a): pass
    def fontMetrics(self): return FM()
class AnyAttr:
    def __getattr__(s, n): return AnyAttr()
    def __call__(s, *a, **k): return AnyAttr()
Painter.RenderHint = AnyAttr()
class Pt:
    def __init__(s, x=0, y=0): s.x_, s.y_ = x, y
class Rc:
    def __init__(s, x, y, w, h): s._x, s._y, s._w, s._h = x, y, w, h
    def x(s): return s._x
    def y(s): return s._y
    def width(s): return s._w
    def height(s): return s._h
    def left(s): return s._x
    def top(s): return s._y
    def right(s): return s._x + s._w
    def bottom(s): return s._y + s._h
    def adjusted(s, a, b, c, d): return Rc(s._x + a, s._y + b, s._w - a + c, s._h - b + d)
class Poly(list):
    def translated(s, dx, dy): return Poly(s)
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
    def heightForWidth(s, w): return 20 * max(1, math.ceil(len(s.t.replace("▌", "")) * 8 / max(w, 1)))
class Scr:
    def __init__(s, *a): s.g = None
    def __getattr__(s, n): return lambda *a, **k: Scr()
    def setGeometry(s, *a): s.g = a
class Metrics:
    def __init__(s, f): pass
    def horizontalAdvance(s, t): return 7 * len(t)
class Pix:
    def __init__(s, k=1): s.k = k
    def cacheKey(s): return s.k
    def width(s): return 120
    def height(s): return 120

for name, val in dict(QPainter=Painter, QPointF=Pt, QRectF=Rc, QPolygonF=Poly, QLabel=Lbl, QScrollArea=Scr,
                      QFontMetrics=Metrics, QFont=AnyAttr(), QFrame=AnyAttr(), Qt=AnyAttr(), QPen=lambda *a, **k: None,
                      QColor=lambda *a: ns["__builtins__"] and __import__("types").SimpleNamespace(red=lambda: 1, green=lambda: 2, blue=lambda: 3),
                      QPainterPath=lambda: Rec(), QTimer=ns["FakeTimer"], QWidget=ns["FakeWidget"]).items():
    setattr(ui, name, val)
ui.hud_font = lambda *a, **k: AnyAttr()
ui.random = __import__("random")
FW = ns["FakeWidget"]
FW.setAttribute = lambda s, *a: None
FW.hide = lambda s: None; FW.show = lambda s: None
FW.update = lambda s: None

# ---- layout
box = ui.Bubble("atom", config.HUD_BUBBLE_MAX)
assert box.plate
box.set_text("Hi")
w0, h0 = box.width(), box.height()
assert w0 == 392
assert h0 >= 8 + (14 + 58 + 22) + ui.Bubble.TAIL_H, h0       # tall enough for the portrait + the tail
box.set_text("This is a longer answer. " * 12)
assert box.height() > h0 and box._plate_rect.height() > 94
assert box.scroll.g[0] == 8 + 14 + 58 + 12, box.scroll.g       # text starts right of the portrait
box.set_text("word " * 600)
assert box.scroll.g[3] <= config.HUD_BUBBLE_MAX[1], box.scroll.g  # long text scrolls instead of growing
box.set_text("Hi")
q = ui._Quote(box); row = ui._QuoteRow(box)
q.set_text("open spotify and play dare"); h1 = box.height(); row.show()
assert box.height() >= h1 and box.scroll.g[1] == 8 + 14 + 18 + 18, box.scroll.g
row.hide(); assert box.height() == h1 and box.scroll.g[1] == 8 + 14 + 18
box.set_text('This is a longer answer. ' * 6); hq = box.height(); row.show(); assert box.height() == hq + ui.Bubble.QLINE; row.hide(); box.set_text('Hi')

# ---- long answers: the newest words stay in view while they arrive, a finished one starts at its top
class Bar:
    def __init__(s): s.v = None
    def maximum(s): return 100
    def setValue(s, v): s.v = v
class ScrBar(Scr):
    def __init__(s, *a): Scr.__init__(s); s.bar = Bar()
    def verticalScrollBar(s): return s.bar
box.scroll = ScrBar()
long_text = "word " * 600
box.set_text(long_text[:300], follow=True); assert box.scroll.bar.v == 100, box.scroll.bar.v   # arriving: newest words
box.set_text(long_text, follow=True); assert box.scroll.bar.v == 100
box.set_text(long_text); assert box.scroll.bar.v == 0, box.scroll.bar.v                          # finished: first line
box.type_text("Hello there. " * 40, cps=50)
box._tick(); assert box.scroll.bar.v is not None and 0 <= box.scroll.bar.v <= 100
mid = box.scroll.bar.v
for _ in range(5): box._tick()
assert box.scroll.bar.v >= mid, (mid, box.scroll.bar.v)                                           # follows the typing
while box._timer.active: box._tick()
assert box.scroll.bar.v == 0 and box._follow is False, (box.scroll.bar.v, box._follow)           # done: back to the top
assert config.HUD_BUBBLE_MAX[1] >= 200 and config.HUD_WINDOW_SIZE[1] >= 640
box.set_text("Hi")

# ---- drawing
def drawn(b):
    calls.clear(); b.paintEvent(None)
    return [c[1][-1] for c in calls if c[0] == "drawText"], [c[0] for c in calls]
texts, names = drawn(box)
assert "/// ATOM" in texts and names.count("drawPolygon") >= 6, (texts, names.count("drawPolygon"))
assert "drawPixmap" not in names, "no portrait yet -> placeholder letter"
assert "A" in texts or any(c[0] == "drawText" for c in calls)
box.set_tag("Reading budget.xlsx...")
assert box.tag == "READING BUDGET.XLSX"
texts, _ = drawn(box); assert any("READING BUDGET" in t for t in texts), texts
box.set_tag("")
row.show(); texts, _ = drawn(box)
assert ">" in texts and "open spotify and play dare" in texts, texts
row.hide()

# ---- sync follows his mood: colours, chip, portrait
class Char:
    state = "idle"
    def __init__(s): s.pix = Pix(1)
    def portrait(s): return s.pix
ch = Char()
box.sync(ch)
assert box.kind == "info" and box.chip == "" and box._portrait is ch.pix
texts, names = drawn(box); assert "drawPixmap" in names
ch.state = "thinking"; box.sync(ch); assert box.chip == "THINKING" and box._glitch == 5 and box._timer.active
texts, _ = drawn(box); assert "THINKING" in texts
ch.state = "worried"; box.sync(ch); assert box.kind == "alert" and box.chip == "ALERT"
colors = box._plate_colors(); assert len(colors) == 3
for st, kind in [("happy", "done"), ("sad", "alert"), ("sleepy", "idle"), ("talking", "info"), ("curious", "info")]:
    ch.state = st; box.sync(ch); assert box.kind == kind, (st, box.kind)
    drawn(box)
ch.pix = Pix(2); box.sync(ch); assert box._portrait_key == 2
class Orb:  # the orb has no portrait
    state = "idle"
orb = Orb(); box.sync(orb); assert box._portrait is None; drawn(box)

# ---- typewriter shows a block cursor and still ends with the plain text
box.set_text("x")
box.type_text("Hello there, this is typed out.", cps=50)
box._tick(); assert box.label.t.endswith("▌"), box.label.t
while box._timer.active: box._tick()
assert box.label.t == "Hello there, this is typed out." and box._glitch == 0
print("plate paint ok")
