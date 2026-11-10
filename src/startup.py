"""startup.py - Step 8: start Atom automatically when you sign in to Windows.

Adds (or removes) one entry in your own "Run" list in the registry
(HKEY_CURRENT_USER, so no administrator rights are needed). Nothing else changes.
Atom starts quietly in the tray: the "--startup" flag tells main.py not to pop up.
"""

from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Atom"


def supported() -> bool:
    """Start-with-Windows only exists on Windows."""
    return sys.platform == "win32"


def launch_command() -> str:
    """The command Windows should run at sign-in."""
    if getattr(sys, "frozen", False):  # packaged Atom.exe
        return f'"{sys.executable}" --startup'
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")  # no black console window
    if windowless.exists():
        python = windowless
    main = Path(__file__).resolve().with_name("main.py")
    return f'"{python}" "{main}" --startup'


def _winreg():
    if sys.platform != "win32":
        return None
    import winreg

    return winreg


def is_enabled(winreg=None) -> bool:
    winreg = winreg or _winreg()
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(on: bool, winreg=None) -> bool:
    """Turn start-with-Windows on or off. Returns True if it worked."""
    winreg = winreg or _winreg()
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass  # it wasn't there: already off
        return True
    except OSError as error:
        print(f"[atom] couldn't change start-with-Windows: {error}")
        return False
