"""memory.py - Step 5: Atom remembers between sessions.

Two things are saved in a small SQLite file on your computer
(C:\\Users\\<you>\\.atom\\memory.db). Nothing here talks to the internet.

  * the conversation, so after a restart Atom still knows what you talked about
  * notes: things worth keeping (your projects, deadlines, preferences)

No window code and no AI code in here.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import config

KINDS = ("fact", "preference", "project", "deadline")
MAX_MESSAGE_CHARS = 2000
MAX_NOTE_CHARS = 300

# things Atom must never keep
_SECRET = re.compile(r"(\b(?:\d[ -]?){13,19}\b|password|passcode|\bpin\b|cvv|secret key|api key)", re.I)


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d %b %Y %H:%M")


def looks_secret(text: str) -> bool:
    return bool(_SECRET.search(text or ""))


class Memory:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.MEMORY_DB)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                role TEXT NOT NULL, text TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                kind TEXT NOT NULL, text TEXT NOT NULL);
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------ conversation
    def add_message(self, role: str, text: str) -> None:
        text = (text or "").strip()[:MAX_MESSAGE_CHARS]
        if role not in ("user", "assistant") or not text:
            return
        with self._lock:
            self._db.execute(
                "INSERT INTO messages (ts, role, text) VALUES (?, ?, ?)", (time.time(), role, text)
            )
            # keep the file small: only the newest messages are kept
            self._db.execute(
                "DELETE FROM messages WHERE id <= (SELECT MAX(id) FROM messages) - ?",
                (config.MAX_SAVED_MESSAGES,),
            )
            self._db.commit()

    def recent_messages(self, limit: int) -> list[dict]:
        """The last `limit` messages, oldest first, shaped like the AI expects."""
        with self._lock:
            rows = self._db.execute(
                "SELECT role, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"role": role, "content": text} for role, text in reversed(rows)]

    def last_message_time(self) -> float | None:
        with self._lock:
            row = self._db.execute("SELECT MAX(ts) FROM messages").fetchone()
        return row[0] if row and row[0] else None

    def clear_messages(self) -> int:
        with self._lock:
            count = self._db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            self._db.execute("DELETE FROM messages")
            self._db.commit()
        return count

    # ------------------------------------------------------------------- notes
    def add_note(self, text: str, kind: str = "fact") -> tuple[bool, str]:
        """Save a note. Returns (is_new, the note as saved)."""
        text = re.sub(r"\s+", " ", (text or "").strip())[:MAX_NOTE_CHARS]
        kind = kind if kind in KINDS else "fact"
        with self._lock:
            row = self._db.execute(
                "SELECT id FROM notes WHERE lower(text) = lower(?)", (text,)
            ).fetchone()
            if row:
                return False, text
            self._db.execute(
                "INSERT INTO notes (ts, kind, text) VALUES (?, ?, ?)", (time.time(), kind, text)
            )
            self._db.commit()
        return True, text

    def notes(self) -> list[tuple[int, str, str]]:
        with self._lock:
            return self._db.execute("SELECT id, kind, text FROM notes ORDER BY id").fetchall()

    def notes_text(self, max_chars: int) -> str:
        """Notes as short lines for the AI. If there are too many, the newest win."""
        lines = [f"- ({kind}) {text}" for _, kind, text in self.notes()]
        kept, total = [], 0
        for line in reversed(lines):
            if total + len(line) + 1 > max_chars:
                break
            kept.append(line)
            total += len(line) + 1
        return "\n".join(reversed(kept))

    def forget(self, what: str) -> int:
        """Delete the notes that contain `what` (all of its words). Returns how many."""
        words = [w for w in re.findall(r"\w+", (what or "").lower()) if len(w) > 1]
        if not words:
            return 0
        removed = 0
        with self._lock:
            for note_id, _, text in self.notes():
                low = text.lower()
                if all(w in low for w in words):
                    self._db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
                    removed += 1
            self._db.commit()
        return removed

    def clear_notes(self) -> int:
        with self._lock:
            count = self._db.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            self._db.execute("DELETE FROM notes")
            self._db.commit()
        return count

    # ------------------------------------------------------------------ recall
    def recall(self, query: str, limit: int = 6) -> str:
        """Search notes and old messages for a topic (every word must appear)."""
        words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) > 1]
        with self._lock:
            if words:
                like = " AND ".join("lower(text) LIKE ?" for _ in words)
                args = [f"%{w}%" for w in words]
                notes = self._db.execute(
                    f"SELECT kind, text FROM notes WHERE {like} ORDER BY id DESC LIMIT ?", (*args, limit)
                ).fetchall()
                msgs = self._db.execute(
                    f"SELECT ts, role, text FROM messages WHERE {like} ORDER BY id DESC LIMIT ?",
                    (*args, limit),
                ).fetchall()
            else:  # no topic: just what was said most recently
                notes = []
                msgs = self._db.execute(
                    "SELECT ts, role, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        if not notes and not msgs:
            return "Nothing saved matches that."
        out = []
        for kind, text in notes:
            out.append(f"Note ({kind}): {text}")
        for ts, role, text in reversed(msgs):
            who = "User" if role == "user" else "Atom"
            out.append(f"{_when(ts)} {who}: {text[:220]}")
        return "\n".join(out)
