"""watcher.py - Step 6: notice the moment a file you gave Atom is saved.

Uses the `watchdog` package to listen to the folders your files live in.
When Excel (or anything else) saves a file, Atom hears about it, waits a
moment so a burst of saves counts once, and then calls `on_change(path)`.

No window code in here. `on_change` runs on a background thread, so the
window should only use it to send a Qt signal. If `watchdog` is not
installed, start() returns False and Atom keeps using its timer instead.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Iterable

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # optional: Atom still works, just a little slower to notice
    Observer = None

    class FileSystemEventHandler:  # type: ignore[no-redef]
        pass


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class FileWatcher(FileSystemEventHandler):
    def __init__(self, on_change: Callable[[str], None], delay: float = 2.0):
        super().__init__()
        self.on_change = on_change
        self.delay = delay            # seconds of quiet before a change is reported
        self._observer = None
        self._folders: set[str] = set()
        self._files: set[str] = set()
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ control
    @property
    def available(self) -> bool:
        return Observer is not None

    def start(self) -> bool:
        if Observer is None:
            return False
        with self._lock:
            if self._observer is None:
                self._observer = Observer()
                self._observer.daemon = True
                self._observer.start()
        return True

    def watch(self, paths: Iterable[str]) -> None:
        """Listen for changes to these files (call again whenever files are added)."""
        if self._observer is None:
            return
        with self._lock:
            for path in paths:
                self._files.add(_key(path))
                folder = os.path.dirname(os.path.abspath(path))
                if folder in self._folders or not os.path.isdir(folder):
                    continue
                try:
                    self._observer.schedule(self, folder, recursive=False)
                    self._folders.add(folder)
                except OSError:
                    pass  # a folder we can't listen to: the timer check still covers it

    def stop(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            observer, self._observer = self._observer, None
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=2)
            except Exception:
                pass

    # ------------------------------------------------------------- events
    def on_any_event(self, event) -> None:
        if getattr(event, "is_directory", False) or getattr(event, "event_type", "") == "deleted":
            return
        for path in (getattr(event, "src_path", ""), getattr(event, "dest_path", "")):
            if path:
                self._maybe(str(path))

    def _maybe(self, path: str) -> None:
        key = _key(path)
        if Path(path).name.startswith("~$") or key not in self._files:
            return  # Office lock files and files Atom doesn't track
        with self._lock:
            old = self._timers.pop(key, None)
            if old:
                old.cancel()
            timer = threading.Timer(self.delay, self._fire, args=(key, path))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _fire(self, key: str, path: str) -> None:
        with self._lock:
            self._timers.pop(key, None)
        try:
            self.on_change(path)
        except Exception:
            pass  # a notification must never break the watcher
