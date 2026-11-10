"""daily.py - Step 11: Atom as a daily helper. Reminders, a to-do list and a morning briefing.

Everything is saved on this computer in  ~/.atom/daily.db  (nothing is sent anywhere).
The window checks every few seconds whether a reminder is due; this file only keeps the lists.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import get_close_matches
from pathlib import Path

import config
import timeparse


@dataclass
class Reminder:
    id: int
    text: str
    due: datetime
    repeat: str = ""


@dataclass
class Todo:
    id: int
    text: str
    done: bool = False
    due: date | None = None


def _ts(dt: datetime) -> float:
    return dt.timestamp()


class Daily:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or getattr(config, "DAILY_DB", config.DATA_DIR / "daily.db"))
        self._lock = threading.RLock()
        self.last_fired: int | None = None      # the reminder that rang most recently (for "snooze")
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, due REAL NOT NULL,
                repeat TEXT NOT NULL DEFAULT '', done INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
                due TEXT, created REAL NOT NULL, done_ts REAL);
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------ reminders
    @staticmethod
    def _reminder(row) -> Reminder:
        return Reminder(row[0], row[1], datetime.fromtimestamp(row[2]), row[3] or "")

    def add_reminder(self, text: str, due: datetime, repeat: str = "") -> Reminder:
        text = " ".join(str(text or "").split())[:200]
        if not text:
            raise ValueError("Tell me what to remind you about.")
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO reminders (text, due, repeat, created) VALUES (?, ?, ?, ?)",
                (text, _ts(due), repeat, datetime.now().timestamp()),
            )
            self._db.commit()
            return Reminder(cur.lastrowid, text, due, repeat)

    def reminders(self) -> list[Reminder]:
        with self._lock:
            rows = self._db.execute("SELECT id, text, due, repeat FROM reminders WHERE done = 0 ORDER BY due, id").fetchall()
        return [self._reminder(r) for r in rows]

    def due(self, now: datetime | None = None) -> list[Reminder]:
        """Reminders whose time has come (including ones that came while Atom was closed)."""
        now = now or datetime.now()
        return [r for r in self.reminders() if r.due <= now]

    def fire(self, reminder_id: int, now: datetime | None = None) -> None:
        """Call after a reminder was shown: repeating ones move to their next time, the rest are finished."""
        now = now or datetime.now()
        self.last_fired = reminder_id
        with self._lock:
            row = self._db.execute("SELECT due, repeat FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            if not row:
                return
            if row[1]:
                nxt = timeparse.next_after(datetime.fromtimestamp(row[0]), row[1], now)
                self._db.execute("UPDATE reminders SET due = ? WHERE id = ?", (_ts(nxt), reminder_id))
            else:
                self._db.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
            self._db.commit()

    def snooze(self, which, minutes: int = 10, now: datetime | None = None) -> Reminder:
        """Ring again in `minutes`. `which` = a reminder's number or words, or '' for the one that just rang."""
        now = now or datetime.now()
        minutes = max(1, min(int(minutes), 7 * 1440))
        if isinstance(which, int) or (isinstance(which, str) and which.strip()):
            query = f"#{which}" if isinstance(which, int) else which
            found = self._find([(r.id, r.text, r) for r in self.reminders()], query, "reminder")
        elif self.last_fired is not None:
            found = None
        else:
            raise ValueError("Nothing has rung yet, so there is nothing to snooze.")
        reminder_id = found.id if found else self.last_fired
        with self._lock:
            row = self._db.execute("SELECT text, repeat FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            if not row:
                raise ValueError("I can't find that reminder any more.")
            due = now + timedelta(minutes=minutes)
            self._db.execute("UPDATE reminders SET due = ?, done = 0 WHERE id = ?", (_ts(due), reminder_id))
            self._db.commit()
        return Reminder(reminder_id, row[0], due, row[1] or "")

    def cancel_reminder(self, query: str) -> Reminder:
        found = self._find([(r.id, r.text, r) for r in self.reminders()], query, "reminder")
        with self._lock:
            self._db.execute("UPDATE reminders SET done = 1 WHERE id = ?", (found.id,))
            self._db.commit()
        return found

    # ---------------------------------------------------------------- to-dos
    @staticmethod
    def _todo(row) -> Todo:
        due = date.fromisoformat(row[3]) if row[3] else None
        return Todo(row[0], row[1], bool(row[2]), due)

    def add_todo(self, text: str, due: date | None = None) -> tuple[Todo, bool]:
        """(item, already_there)."""
        text = " ".join(str(text or "").split())[:200]
        if not text:
            raise ValueError("Tell me what to put on the list.")
        with self._lock:
            for item in self.todos():
                if item.text.lower() == text.lower():
                    return item, True
            cur = self._db.execute(
                "INSERT INTO todos (text, due, created) VALUES (?, ?, ?)",
                (text, due.isoformat() if due else None, datetime.now().timestamp()),
            )
            self._db.commit()
            return Todo(cur.lastrowid, text, False, due), False

    def todos(self, include_done: bool = False) -> list[Todo]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, text, done, due FROM todos" + ("" if include_done else " WHERE done = 0") + " ORDER BY done, id"
            ).fetchall()
        items = [self._todo(r) for r in rows]
        far = date.max
        return sorted(items, key=lambda t: (t.done, t.due or far, t.id))

    def complete_todo(self, query: str) -> Todo:
        found = self._find([(t.id, t.text, t) for t in self.todos()], query, "to-do")
        with self._lock:
            self._db.execute("UPDATE todos SET done = 1, done_ts = ? WHERE id = ?", (datetime.now().timestamp(), found.id))
            self._db.commit()
        return found

    def remove_todo(self, query: str) -> Todo:
        found = self._find([(t.id, t.text, t) for t in self.todos(include_done=True)], query, "to-do")
        with self._lock:
            self._db.execute("DELETE FROM todos WHERE id = ?", (found.id,))
            self._db.commit()
        return found

    def clear_done(self) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM todos WHERE done = 1")
            self._db.commit()
            return cur.rowcount

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _find(items, query, what: str):
        """Pick one item by number ('3', '#3') or by (part of) its words; say clearly if it is unclear."""
        q = str(query or "").strip().lower()
        if not items:
            raise ValueError(f"There is no {what} to change.")
        if not q:
            raise ValueError(f"Which {what}? Tell me its number or a few of its words.")
        number = re.fullmatch(r"#?\s*(\d+)", q)
        if number:
            for item_id, _, obj in items:
                if item_id == int(number.group(1)):
                    return obj
            raise ValueError(f"I can't find {what} number {number.group(1)}.")
        exact = [obj for _, text, obj in items if text.lower() == q]
        if len(exact) == 1:
            return exact[0]
        part = [obj for _, text, obj in items if q in text.lower()]
        if not part:
            words = [w for w in re.findall(r"[a-z0-9']+", q) if len(w) > 2]
            part = [obj for _, text, obj in items if words and all(w in text.lower() for w in words)]
        if not part:
            close = get_close_matches(q, [text.lower() for _, text, _ in items], n=1, cutoff=0.6)
            part = [obj for _, text, obj in items if close and text.lower() == close[0]]
        if len(part) == 1:
            return part[0]
        if not part:
            raise ValueError(f"No {what} matches '{query}'.")
        names = "; ".join(f"#{o.id} {o.text}" for o in part[:5])
        raise ValueError(f"More than one {what} matches: {names}. Tell me the number.")

    # ------------------------------------------------------------- display
    def reminders_text(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        items = self.reminders()
        if not items:
            return "No reminders are set."
        lines = []
        for r in items[:15]:
            again = f" (repeats {r.repeat})" if r.repeat else ""
            late = " - waiting to be shown" if r.due <= now else ""
            lines.append(f"#{r.id} {timeparse.nice(r.due, now)}: {r.text}{again}{late}")
        return "Reminders:\n" + "\n".join(lines)

    def todos_text(self, today: date | None = None) -> str:
        today = today or date.today()
        items = self.todos()
        if not items:
            return "The to-do list is empty."
        lines = []
        for t in items[:20]:
            tag = ""
            if t.due:
                tag = " (OVERDUE, was due " if t.due < today else " (due "
                tag += (t.due.strftime("%a %d %b").replace(" 0", " ")) + ")"
            lines.append(f"#{t.id} {t.text}{tag}")
        more = f"\n...and {len(items) - 20} more" if len(items) > 20 else ""
        return f"To-do list ({len(items)} open):\n" + "\n".join(lines) + more

    def briefing(self, now: datetime | None = None, extra: list[str] | None = None) -> str:
        """A short 'here is your day' for the speech bubble."""
        now = now or datetime.now()
        today = now.date()
        parts: list[str] = []
        todays = [r for r in self.reminders() if r.due.date() == today]
        late = [r for r in self.reminders() if r.due.date() < today]
        if late:
            parts.append(f"{len(late)} reminder{'s' if len(late) != 1 else ''} slipped by while I was off: " +
                         "; ".join(r.text for r in late[:2]) + ("..." if len(late) > 2 else "") + ".")
        if todays:
            shown = ", ".join(f"{r.due.strftime('%I:%M %p').lstrip('0')} {r.text}" for r in todays[:3])
            parts.append(f"Today you have {len(todays)} reminder{'s' if len(todays) != 1 else ''}: {shown}"
                         + (f" and {len(todays) - 3} more" if len(todays) > 3 else "") + ".")
        open_items = self.todos()
        if open_items:
            overdue = [t for t in open_items if t.due and t.due < today]
            due_today = [t for t in open_items if t.due == today]
            top = [t.text for t in (overdue + due_today + [t for t in open_items if t not in overdue + due_today])[:3]]
            line = f"Your to-do list has {len(open_items)} open item{'s' if len(open_items) != 1 else ''}"
            if overdue:
                line += f", {len(overdue)} overdue"
            if due_today:
                line += f", {len(due_today)} due today"
            parts.append(line + ": " + "; ".join(top) + ("..." if len(open_items) > 3 else "") + ".")
        for line in (extra or []):
            parts.append(line)
        if not parts:
            return "Nothing is scheduled and your list is empty. A quiet day - tell me if you want to add something."
        greeting = "Good morning!" if now.hour < 12 else "Good afternoon!" if now.hour < 18 else "Good evening!"
        return f"{greeting} " + " ".join(parts)
