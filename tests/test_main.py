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
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home

SERVERS = {}
class Sig:
    def __init__(s): s.cbs = []
    def connect(s, cb): s.cbs.append(cb)
    def emit(s, *a):
        for cb in s.cbs: cb(*a)
class FakeConn:
    def __init__(s, data): s.data = data; s.reply = b""; s.closed = False
    def waitForReadyRead(s, ms): return True
    def readAll(s): d, s.data = s.data, b""; return d
    def write(s, d): s.reply += d
    def flush(s): pass
    def waitForBytesWritten(s, ms): return True
    def disconnectFromServer(s): s.closed = True
class FakeServer:
    @staticmethod
    def removeServer(name): SERVERS.pop(name, None)
    def __init__(s, parent=None): s.newConnection = Sig(); s.pending = None
    def listen(s, name): SERVERS[name] = s; return True
    def nextPendingConnection(s): return s.pending
class FakeSocket:
    def __init__(s): s.name = None; s.out = b""; s.conn = None
    def connectToServer(s, name): s.name = name
    def waitForConnected(s, ms): return s.name in SERVERS
    def write(s, d): s.out += d
    def waitForBytesWritten(s, ms): return True
    def waitForReadyRead(s, ms):
        server = SERVERS[s.name]; s.conn = FakeConn(s.out); server.pending = s.conn; server.newConnection.emit()
        return bool(s.conn.reply)
    def readAll(s): return s.conn.reply
    def disconnectFromServer(s): pass
sys.modules["PySide6.QtNetwork"] = make_mod("PySide6.QtNetwork", QLocalServer=FakeServer, QLocalSocket=FakeSocket)
sys.modules["PySide6.QtWidgets"].QApplication = types.SimpleNamespace(primaryScreen=lambda: None)

import main, version
bad = []
def check(n, c, *info):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, info))

class Win:
    def __init__(s): s.summoned = 0; s.quit = 0
    def summon(s, listen=True): s.summoned += 1
    def quit_app(s): s.quit += 1

check("no Atom running -> None", main.ask_running_atom(version.hello()) is None)
win = Win(); main.listen_for_second_launch(win)
check("same version -> show + summon", main.ask_running_atom(version.hello()) == "show" and win.summoned == 1 and win.quit == 0)
check("older newcomer -> show", main.ask_running_atom(b"show|0.1.0") == "show" and win.summoned == 2)
check("ping is silent", main.ask_running_atom(b"ping") == "ping" and win.summoned == 2)
check("old-style hello (no version) -> show", main.ask_running_atom(b"show") == "show")
check("newer newcomer -> replace, running one quits itself", main.ask_running_atom(b"show|99.0.0") == "replace")
check("  (quit is scheduled, not instant)", win.quit == 0)   # QTimer.singleShot is a no-op stand-in
# wait_until_gone
check("wait: gone at once when nobody is there", (SERVERS.clear() or main.wait_until_gone(1.0)) is True)
SERVERS["AtomDesktopAssistant"] = FakeServer(); SERVERS["AtomDesktopAssistant"].newConnection.connect(lambda: None)
t0 = __import__("time").time(); r = main.wait_until_gone(0.6); check("wait: gives up if he never closes", r is False and __import__("time").time() - t0 >= 0.5)
print("FAILED:" if bad else "ALL PASSED", bad)

# ---- shortcut maker
import make_shortcut as ms
from pathlib import Path
script = ms.shortcut_script(["Desktop", "Programs"], Path("C:/Users/del ro/O'Neil/.venv/Scripts/pythonw.exe"), Path("C:/atom/atom.ico"))
assert "GetFolderPath('Desktop')" in script and "GetFolderPath('Programs')" in script and "O''Neil" in script and "IconLocation" in script and "main.py" in script, script
assert "Remove-Item" in ms.shortcut_script(["Desktop"], Path("x"), None, remove=True) and "CreateShortcut" not in ms.shortcut_script(["Desktop"], Path("x"), None, remove=True)
calls = []
ms.make_icon = lambda: None
rc = ms.main(["--desktop"], run=lambda s: (calls.append(s) or (True, "made x")))
assert rc == 0 and len(calls) == 1 and "Programs" not in calls[0]
rc = ms.main([], run=lambda s: (calls.append(s) or (True, "made x"))); assert "Programs" in calls[-1]
rc = ms.main(["--remove"], run=lambda s: (calls.append(s) or (True, ""))); assert rc == 0 and "Remove-Item" in calls[-1]
assert ms.main([], run=lambda s: (False, "boom")) == 1
print("SHORTCUT OK")
