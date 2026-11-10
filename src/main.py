"""main.py - start Atom. Run with:  python main.py

Only one Atom runs at a time: starting him again just brings the first one to
the front - unless the new copy is a NEWER version (you just updated the files): then the old Atom closes
himself and the new one starts. When Windows starts him at sign-in he waits quietly in the tray
(that is what the --startup flag means).
"""

import re
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

import config


def check_files() -> bool:
    """Atom is made of many files, and it is easy to copy only some of them. This checks that
    config.py has every setting the other files ask for, and says so plainly if not."""
    if getattr(sys, "frozen", False):  # the packaged Atom.exe has no loose files to check
        return True
    used: set[str] = set()
    for path in Path(__file__).resolve().parent.glob("*.py"):
        if path.name != "config.py":
            used |= set(re.findall(r"\bconfig\.([A-Z][A-Z0-9_]+)\b", path.read_text(encoding="utf-8", errors="ignore")))
    missing = sorted(name for name in used if not hasattr(config, name))
    if missing:
        print(
            "\nYour config.py is OLDER than the other Atom files, so Atom can't start yet.\n"
            f"It is missing: {', '.join(missing)}\n"
            "Fix: copy the newest config.py over the one in this folder, then run  python main.py  again.\n"
        )
        return False
    return True


if not check_files():
    sys.exit(1)

import atomlog  # noqa: E402
import version  # noqa: E402
import backup  # noqa: E402
import checkup  # noqa: E402
from brain import Brain  # noqa: E402
from tools import FileStore  # noqa: E402
from ui import MainWindow  # noqa: E402

SERVER_NAME = "AtomDesktopAssistant"


def ask_running_atom(message: bytes) -> str | None:
    """Talk to an Atom that is already running. Returns his answer ('show', 'replace', 'ping'; '' from an older Atom
    that doesn't answer), or None when no Atom is running."""
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(400):
        return None
    socket.write(message)
    socket.waitForBytesWritten(400)
    reply = ""
    if socket.waitForReadyRead(800):
        reply = bytes(socket.readAll()).decode("utf-8", "ignore").strip()
    socket.disconnectFromServer()
    return reply


def wait_until_gone(seconds: float = 8.0) -> bool:
    """After telling an older Atom to close: wait until he has really gone."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if ask_running_atom(b"ping") is None:
            return True
        time.sleep(0.25)
    return False


def listen_for_second_launch(window: MainWindow) -> QLocalServer:
    QLocalServer.removeServer(SERVER_NAME)  # a leftover from a crash would block us
    server = QLocalServer(window)

    def on_connection() -> None:
        connection = server.nextPendingConnection()
        if connection is None:
            return
        connection.waitForReadyRead(300)
        answer = version.reply_to(bytes(connection.readAll()))
        connection.write(answer.encode())
        connection.flush()
        connection.waitForBytesWritten(300)
        connection.disconnectFromServer()
        if answer == "show":
            window.summon(listen=False)
        elif answer == "replace":                       # a newer Atom was started: step aside for it
            atomlog.log("a newer Atom was started, closing this one")
            QTimer.singleShot(300, window.quit_app)

    server.newConnection.connect(on_connection)
    server.listen(SERVER_NAME)
    return server


def main() -> int:
    if sys.platform == "win32":   # one taskbar identity, so the pinned icon, the window and the tray all group together
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.APP_ID)
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(version.VERSION)
    app.setQuitOnLastWindowClosed(False)  # closing the window keeps Atom in the tray

    answer = ask_running_atom(version.hello())
    if answer is not None:
        if answer == "replace" and wait_until_gone():
            print("An older Atom was running. He closed, and this newer one is starting.")
        else:
            # the first Atom comes to the front; this one is not needed
            print(
                "\nAtom is ALREADY RUNNING, so this new copy closed itself and you are still looking at the old one.\n"
                "To start fresh: right-click Atom's tray icon (bottom right, near the clock) > Quit,\n"
                "or run:  taskkill /F /IM Atom.exe   and   taskkill /F /IM pythonw.exe\n"
                "then run  python main.py  again.\n"
            )
            return 0

    atomlog.install()                      # from here on, crashes and "[atom]" messages go into ~/.atom/atom.log
    restored = ""
    try:
        restored = backup.apply_pending()  # a restore you asked for is swapped in before anything is opened
    except Exception as error:
        atomlog.exception("restore", error)
        restored = f"I couldn't finish restoring your backup ({error}). Your current files were left alone."

    store = FileStore()
    brain = Brain(store)
    window = MainWindow(store, brain)
    server = listen_for_second_launch(window)  # keep a reference so it stays alive
    window._single_instance_server = server
    started_at_login = "--startup" in sys.argv
    if not (started_at_login and window.tray):  # at sign-in he waits in the tray instead
        window.show()
    note = restored or checkup.startup_note(checkup.quick())    # tell him about a restore, or a file / key problem
    if note:
        atomlog.log(f"start-up note: {note}", "warn")
        QTimer.singleShot(5000, lambda: window.say(note, mood="worried"))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
