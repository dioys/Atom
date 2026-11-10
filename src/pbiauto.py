"""pbiauto.py - lets Atom press Power BI's own "Refresh" button, so a report he just built shows its data
without you clicking anything.

A Power BI project opens with no data loaded (Power BI always waits for a Refresh). This file looks for
the Power BI Desktop window that opened the report and presses Refresh in it, the same click you would make.
It touches nothing else: it only looks for a button called "Refresh" in that one window.

  wait_and_refresh(project_name)  - runs in the background (start it with start_refresh)
  available()                     - is the helper installed?  (pip install pywinauto)

If anything is missing or Power BI is slow, it just stops quietly: you press Refresh yourself.
"""

from __future__ import annotations

import sys
import threading
import time


def available() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import pywinauto  # noqa: F401
        return True
    except ImportError:
        return False


def _window(desktop, project: str):
    """The Power BI Desktop window whose title mentions this report."""
    want = project.lower()
    for win in desktop.windows():
        try:
            title = win.window_text() or ""
        except Exception:
            continue
        if want in title.lower() and ("power bi" in title.lower() or "pbip" in title.lower() or "project" in title.lower()):
            return win
    return None


def _press(win) -> bool:
    """Press the Refresh button (Home tab). True if a click was sent."""
    try:
        button = win.child_window(title="Refresh", control_type="Button")
        if button.exists(timeout=1):
            try:
                button.invoke()
            except Exception:
                button.click_input()
            return True
    except Exception:
        pass
    try:                                # the keyboard way: Alt, H, R (Home > Refresh)
        win.set_focus()
        win.type_keys("%hr")
        return True
    except Exception:
        return False


def wait_and_refresh(project: str, timeout: float = 150.0, log=print, pause: float = 4.0) -> bool:
    """Wait for the report's window, give it a moment to finish loading, press Refresh. True when pressed."""
    if not available():
        return False
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    end = time.monotonic() + timeout
    win = None
    while time.monotonic() < end:
        try:
            win = _window(desktop, project)
        except Exception:
            win = None
        if win is not None:
            break
        time.sleep(2)
    if win is None:
        log("[atom] Power BI: I didn't see the report window, press Refresh yourself")
        return False
    time.sleep(pause)                      # let the report finish drawing
    for _ in range(5):
        try:
            win = _window(desktop, project) or win
            if _press(win):
                log("[atom] Power BI: pressed Refresh")
                return True
        except Exception as error:
            log(f"[atom] Power BI: couldn't press Refresh ({error.__class__.__name__})")
        time.sleep(3)
    log("[atom] Power BI: I couldn't find the Refresh button, press it yourself")
    return False


def start_refresh(project: str, log=print) -> threading.Thread | None:
    """Do it in the background so Atom keeps answering. None when the helper isn't installed."""
    if not available():
        return None
    thread = threading.Thread(target=wait_and_refresh, args=(project,), kwargs={"log": log}, daemon=True)
    thread.start()
    return thread
