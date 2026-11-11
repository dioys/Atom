import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, ctypes
from ctypes import wintypes
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import hotkey, startup
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)
P = hotkey.parse_hotkey
check("ctrl+alt+space", P("ctrl+alt+space") == (hotkey.MOD_CONTROL | hotkey.MOD_ALT, 0x20))
check("case and spaces", P("Ctrl + Shift + A") == (hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, ord("A")))
check("win+f9", P("win+f9") == (hotkey.MOD_WIN, 0x78))
check("digit", P("ctrl+alt+5") == (hotkey.MOD_CONTROL | hotkey.MOD_ALT, ord("5")))
check("f24", P("alt+f24")[1] == 0x87)
for bad_text in ("", "a", "ctrl", "hyper+a", "ctrl+alt+", "ctrl+banana", "ctrl+f99"):
    try: P(bad_text); check(f"rejects {bad_text!r}", False)
    except ValueError: check(f"rejects {bad_text!r}", True)

class FakeUser32:
    def __init__(self, free=True): self.free = free; self.calls = []
    def RegisterHotKey(self, hwnd, id_, mods, vk): self.calls.append(("reg", id_, mods, vk)); return 1 if self.free else 0
    def UnregisterHotKey(self, hwnd, id_): self.calls.append(("unreg", id_)); return 1
pressed = []
u = FakeUser32()
h = hotkey.GlobalHotkey(lambda: pressed.append(1), user32=u)
check("register ok", h.register("ctrl+alt+space", install=False) is True)
check("NOREPEAT flag set", u.calls[0][2] == hotkey.MOD_CONTROL | hotkey.MOD_ALT | hotkey.MOD_NOREPEAT and u.calls[0][3] == 0x20)

def message(msg_id, wparam):
    m = wintypes.MSG(); m.message = msg_id; m.wParam = wparam
    return m
m = message(hotkey.WM_HOTKEY, hotkey.GlobalHotkey.HOTKEY_ID)
check("hotkey message -> callback + swallowed", h.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(m)) == (True, 0) and pressed == [1])
other = message(hotkey.WM_HOTKEY, 1234)
check("other hotkey ignored", h.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(other)) == (False, 0) and pressed == [1])
other = message(0x0100, hotkey.GlobalHotkey.HOTKEY_ID)
check("other message ignored", h.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(other)) == (False, 0))
check("other event type ignored", h.nativeEventFilter(b"xcb_generic_event_t", ctypes.addressof(m)) == (False, 0))
h.callback = lambda: 1 / 0
h.handle(); check("broken callback doesn't crash", True)
h.unregister(); h.unregister()
check("unregister once", [c for c in u.calls if c[0] == "unreg"] == [("unreg", hotkey.GlobalHotkey.HOTKEY_ID)])
check("message ignored after unregister", h.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(m)) == (False, 0))
taken = hotkey.GlobalHotkey(lambda: None, user32=FakeUser32(free=False))
check("taken by another program -> False", taken.register("ctrl+alt+space", install=False) is False)
check("bad text -> False", hotkey.GlobalHotkey(lambda: None, user32=FakeUser32()).register("nonsense", install=False) is False)
check("not windows -> False, no crash", hotkey.GlobalHotkey(lambda: None).register("ctrl+alt+space") is False)

# ---- start with windows (fake registry)
class FakeKey:
    def __init__(self, store): self.store = store
    def __enter__(self): return self
    def __exit__(self, *a): return False
class FakeWinreg:
    HKEY_CURRENT_USER = 1; KEY_SET_VALUE = 2; REG_SZ = 1
    def __init__(self): self.values = {}
    def OpenKey(self, root, path, reserved=0, access=0):
        assert path == startup.RUN_KEY; return FakeKey(self.values)
    def QueryValueEx(self, key, name):
        if name not in self.values: raise FileNotFoundError(name)
        return self.values[name], 1
    def SetValueEx(self, key, name, r, t, value): self.values[name] = value
    def DeleteValue(self, key, name):
        if name not in self.values: raise FileNotFoundError(name)
        del self.values[name]
reg = FakeWinreg()
check("starts disabled", startup.is_enabled(reg) is False)
check("enable", startup.set_enabled(True, reg) and startup.is_enabled(reg) and "--startup" in reg.values["Atom"] and "main.py" in reg.values["Atom"])
check("command quotes paths", reg.values["Atom"].startswith('"') and reg.values["Atom"].count('"') == 4)
check("disable", startup.set_enabled(False, reg) and not startup.is_enabled(reg))
check("disable twice is fine", startup.set_enabled(False, reg) is True)
sys.frozen = True; sys.executable = r"C:\Apps\Atom\Atom.exe"
check("frozen exe command", startup.launch_command() == r'"C:\Apps\Atom\Atom.exe" --startup')
del sys.frozen
check("not windows: safe no-ops", startup.supported() is False and startup.is_enabled() is False and startup.set_enabled(True) is False)
print("ALL PASSED" if not bad else bad)
