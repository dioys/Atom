"""atomlog.py - Step 9: Atom writes down what he does, so a problem can be found later.

The log is one plain text file on this computer:  ~/.atom/atom.log  (it never leaves your PC).
It keeps errors, the tools Atom used, and every "[atom] ..." message that used to scroll past in the
terminal. When it passes 500 KB the old part moves to atom.log.1, so it never grows forever.

    atomlog.install()      # once, at start-up: catches crashes and copies the terminal messages
    atomlog.log("text")    # write a line
    atomlog.tail(40)       # the last 40 lines, for "Show me the log"
"""

from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

MAX_BYTES = 500_000
_lock = threading.Lock()
_path: Path | None = None
_installed = False


def path() -> Path:
    global _path
    if _path is None:
        import config
        _path = config.DATA_DIR / "atom.log"
    return _path


def use_file(where: Path | None) -> None:
    """Choose another log file (used by the tests)."""
    global _path
    _path = where


def _rotate(target: Path) -> None:
    try:
        if target.stat().st_size > MAX_BYTES:
            old = target.with_name(target.name + ".1")
            if old.exists():
                old.unlink()
            target.replace(old)
    except OSError:
        pass


def log(text: str, kind: str = "info") -> None:
    """Add one line (or several) to the log. Never raises: logging must not break Atom."""
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = str(text).rstrip().splitlines() or [""]
        body = "".join(f"{stamp} {kind.upper():5} {line}\n" for line in lines)
        target = path()
        with _lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            _rotate(target)
            with open(target, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(body)
    except Exception:
        pass


def error(text: str) -> None:
    log(text, "error")


def exception(where: str, exc: BaseException) -> None:
    """Log an error with its full traceback."""
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
    log(f"{where}: {type(exc).__name__}: {exc}\n{detail}", "error")


def tail(lines: int = 40) -> str:
    try:
        text = path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(the log is empty so far)"
    return "\n".join(text.splitlines()[-lines:]) or "(the log is empty so far)"


def tool_call(name: str, args: dict, result: str, seconds: float) -> None:
    """One line per tool Atom used. The result is cut short; the word 'Error' marks a failure."""
    short = ", ".join(f"{k}={str(v)[:40]!r}" for k, v in list(args.items())[:4])
    head = " ".join(str(result).split())[:110]
    bad = str(result).startswith(("Error", "Could not", "Sorry"))
    log(f"tool {name}({short}) {seconds:.1f}s -> {head}", "warn" if bad else "tool")


class _Tee:
    """Passes everything on to the real terminal, and copies lines that start with [atom] into the log."""

    def __init__(self, real, kind: str):
        self._real = real
        self._kind = kind
        self._buffer = ""

    def write(self, text):
        try:
            if self._real is not None:
                self._real.write(text)
        except Exception:
            pass
        try:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line.strip().startswith("[atom]") or self._kind == "error" and line.strip():
                    log(line.strip(), self._kind)
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            if self._real is not None:
                self._real.flush()
        except Exception:
            pass

    def __getattr__(self, name):          # isatty(), encoding, ... come from the real stream
        return getattr(self._real, name)


def install() -> None:
    """Call once at start-up."""
    global _installed
    if _installed:
        return
    _installed = True
    import version
    log(f"==== Atom {version.VERSION} starting (Python {sys.version.split()[0]}) ====")

    previous = sys.excepthook

    def on_crash(kind, value, trace):
        try:
            log("".join(traceback.format_exception(kind, value, trace)).rstrip(), "crash")
        finally:
            previous(kind, value, trace)

    sys.excepthook = on_crash

    def on_thread_crash(args):
        if args.exc_type is SystemExit:
            return
        log(f"thread {getattr(args.thread, 'name', '?')}: " +
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)).rstrip(), "crash")

    threading.excepthook = on_thread_crash
    sys.stdout = _Tee(sys.stdout, "info")
    sys.stderr = _Tee(sys.stderr, "error")
