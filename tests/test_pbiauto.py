import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, types, time, pathlib
os.environ["HOME"] = tempfile.mkdtemp(); sys.path.insert(0, SRC)
bad = []
def check(n, c, *i):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, i))
import pbiauto
check("not available off Windows", not pbiauto.available() and pbiauto.start_refresh("x") is None)
# pretend we are on Windows with a fake pywinauto
class Btn:
    def __init__(s, ok=True): s.ok = ok; s.clicked = []
    def exists(s, timeout=0): return s.ok
    def invoke(s): s.clicked.append("invoke")
    def click_input(s): s.clicked.append("click")
class Win:
    def __init__(s, title, btn): s.t = title; s.btn = btn; s.keys = []
    def window_text(s): return s.t
    def child_window(s, **k): assert k == {"title": "Refresh", "control_type": "Button"}; return s.btn
    def set_focus(s): pass
    def type_keys(s, k): s.keys.append(k)
class Desk:
    def __init__(s, wins): s.wins = wins
    def windows(s): return s.wins
btn = Btn()
good = Win("Sales 2025 • Last saved: Today (Power BI Project)", btn)
other = Win("Notepad", Btn())
mod = types.ModuleType("pywinauto"); mod.Desktop = lambda backend=None: Desk([other, good])
sys.modules["pywinauto"] = mod; sys.platform = "win32"
check("available with helper", pbiauto.available())
logs = []
ok = pbiauto.wait_and_refresh("Sales 2025", timeout=5, log=logs.append, pause=0.05)
check("pressed Refresh in the right window", ok and btn.clicked == ["invoke"] and other.btn.clicked == [], (ok, btn.clicked, logs))
# button missing -> keyboard fallback
btn2 = Btn(ok=False); w2 = Win("Sales 2025 - Power BI Desktop", btn2); mod.Desktop = lambda backend=None: Desk([w2])
logs.clear(); ok = pbiauto.wait_and_refresh("Sales 2025", timeout=5, log=logs.append, pause=0.05)
check("keyboard fallback Alt+H+R", ok and w2.keys == ["%hr"], (ok, w2.keys))
# no window -> gives up politely
mod.Desktop = lambda backend=None: Desk([other]); logs.clear()
t = time.monotonic(); ok = pbiauto.wait_and_refresh("Sales 2025", timeout=2.5, log=logs.append, pause=0.05)
check("no window: returns False with a message", not ok and logs and "yourself" in logs[0] and time.monotonic() - t < 6, logs)
# background thread
mod.Desktop = lambda backend=None: Desk([good]); btn.clicked.clear()
th = pbiauto.start_refresh("Sales 2025"); check("start_refresh returns a thread", th is not None)
th.join(20); check("thread pressed it", btn.clicked == ["invoke"], btn.clicked)
print("\nFAILED:" if bad else "\nALL PASSED", bad or ""); sys.exit(1 if bad else 0)
