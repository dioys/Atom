"""hotkey.py - Step 8: a key combination that calls Atom from any program.

Windows only. It asks Windows to tell Atom whenever the combination is pressed
(RegisterHotKey), so Atom does not spy on your keyboard: he hears only this one
combination. If another program already owns it, register() returns False.

  parse_hotkey("ctrl+alt+space")  ->  (modifiers, key code)
  GlobalHotkey(callback).register("ctrl+alt+space")
"""

from __future__ import annotations

import sys

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312

_MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "windows": MOD_WIN, "super": MOD_WIN,
}
_KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+Space' -> (MOD_CONTROL | MOD_ALT, 0x20). Raises ValueError if it makes no sense."""
    parts = [p.strip().lower() for p in (text or "").replace(" ", "").split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("A hotkey needs at least one modifier and a key, like ctrl+alt+space.")
    *mods, key = parts
    modifiers = 0
    for mod in mods:
        if mod not in _MODIFIERS:
            raise ValueError(f"Unknown modifier '{mod}' (use ctrl, alt, shift or win).")
        modifiers |= _MODIFIERS[mod]
    if key in _KEYS:
        code = _KEYS[key]
    elif len(key) == 1 and key.isalnum():
        code = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        code = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"Unknown key '{key}'.")
    return modifiers, code


try:
    from PySide6.QtCore import QAbstractNativeEventFilter
except ImportError:  # keeps the parsing usable (and testable) without Qt
    class QAbstractNativeEventFilter:  # type: ignore[no-redef]
        def __init__(self):
            pass


class GlobalHotkey(QAbstractNativeEventFilter):
    """Install with QApplication.instance().installNativeEventFilter(hotkey) -
    register() does that for you."""

    HOTKEY_ID = 0xA70A

    def __init__(self, callback, user32=None):
        super().__init__()
        self.callback = callback
        self._user32 = user32
        self._registered = False

    # ------------------------------------------------------------ control
    def _api(self):
        if self._user32 is not None:
            return self._user32
        if sys.platform != "win32":
            return None
        import ctypes

        return ctypes.windll.user32

    def register(self, text: str, install: bool = True) -> bool:
        """Start listening. False if the combination is invalid, taken, or this isn't Windows."""
        api = self._api()
        if api is None:
            return False
        try:
            modifiers, code = parse_hotkey(text)
        except ValueError as error:
            print(f"[atom] hotkey not set: {error}")
            return False
        self.unregister()
        if not api.RegisterHotKey(None, self.HOTKEY_ID, modifiers | MOD_NOREPEAT, code):
            print(f"[atom] hotkey {text} is already used by another program")
            return False
        self._registered = True
        if install:
            from PySide6.QtCore import QCoreApplication

            QCoreApplication.instance().installNativeEventFilter(self)
        return True

    def unregister(self) -> None:
        api = self._api()
        if api is not None and self._registered:
            api.UnregisterHotKey(None, self.HOTKEY_ID)
        self._registered = False

    # ----------------------------------------------------------- Qt hook
    def nativeEventFilter(self, event_type, message):
        if not self._registered or bytes(event_type) != b"windows_generic_MSG":
            return False, 0
        import ctypes
        from ctypes import wintypes

        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
            self.handle()
            return True, 0
        return False, 0

    def handle(self) -> None:
        """The combination was pressed."""
        try:
            self.callback()
        except Exception as error:  # a broken callback must not break the message loop
            print(f"[atom] hotkey action failed: {error}")
