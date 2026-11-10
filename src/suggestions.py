"""suggestions.py - Step 6: Atom notices things and offers help on his own.

No window code and no AI code in here, and it never talks to the internet.
Atom only suggests; he never edits your files. Each time the window asks
`Suggester.check()`:

  * Did a file you gave Atom change on disk? If so he reads it again, so his
    answers never use an old version.
  * Is anything past its due date and not done? Or due in the next few days?
  * Did the checks find a problem: a formula error or odd formula, blank cells,
    duplicate rows? (see checks.py)

check() returns a short message, or None when there is nothing worth saying.
Each finding is mentioned once.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import checks
import config
import reports

SPREADSHEETS = {".xlsx", ".xlsm", ".csv", ".tsv"}
MAX_LINES = 3  # findings mentioned in one message; the rest come next time


def _list(items: list[str], limit: int = 2) -> str:
    """['a', 'b', 'c'] -> 'a, b and 1 more'."""
    shown = items[:limit]
    text = ", ".join(shown)
    return text + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


class Suggester:
    def __init__(self, store, today: date | None = None):
        self.store = store
        self._today = today
        self._pending_updates: list[str] = []   # changed files not yet mentioned
        self._told: set[tuple] = set()          # findings already shown
        # what the last scan found: (kind, file name) -> items. kind: late | check | soon
        self._found: dict[tuple[str, str], list[str]] = {}
        self._first_check = True
        self._to_scan: set[str] = set()         # newly added files to look at next time
        self._last_keys: tuple = ()

    def scan_soon(self, names: list[str]) -> None:
        """Files you just added: look for problems in them on the next check."""
        self._to_scan.update(names)

    @staticmethod
    def _key(kind: str, name: str, items: list[str]) -> tuple:
        return (kind, name, len(items), tuple(items[:3]))

    def check(self) -> str | None:
        """Re-read changed files, then decide whether there is something to say."""
        for name in self.store.refresh_changed():
            if name not in self._pending_updates:
                self._pending_updates.append(name)

        # spreadsheets to look at: the changed ones, new ones, or all of them on the first check
        scan = [
            r for r in self.store.all()
            if Path(r.name).suffix.lower() in SPREADSHEETS
            and (self._first_check or r.name in self._pending_updates or r.name in self._to_scan)
        ]
        self._first_check = False
        self._to_scan.clear()

        today = self._today or date.today()
        for record in scan:  # remember what we found until it has really been said
            path = Path(record.library_path)
            late = reports.overdue_items(path, today)
            result = checks.analyze(path, today, getattr(config, "DUE_SOON_DAYS", 7))
            for kind, items in (("late", late), ("check", result.checks), ("soon", result.soon)):
                if items:
                    self._found[(kind, record.name)] = items
                else:
                    self._found.pop((kind, record.name), None)

        order = {"late": 0, "check": 1, "soon": 2}
        fresh = sorted(
            (
                (kind, name, items) for (kind, name), items in self._found.items()
                if self._key(kind, name, items) not in self._told
            ),
            key=lambda f: (order[f[0]], f[1]),
        )
        if not self._pending_updates and not fresh:
            return None

        parts = []
        if self._pending_updates:
            names = _list(self._pending_updates)
            parts.append(f"I noticed {names} changed, so I read {'it' if len(self._pending_updates) == 1 else 'them'} again.")
        shown = fresh[:MAX_LINES]
        for kind, name, items in shown:
            if kind == "late":
                parts.append(f"{name} has {_plural(len(items), 'item')} past due, like {_list(items)}.")
            elif kind == "soon":
                days = getattr(config, "DUE_SOON_DAYS", 7)
                parts.append(f"{name} has {_plural(len(items), 'item')} due in the next {days} days, like {_list(items)}.")
            else:
                parts.append(f"In {name}: {_list(items)}.")
        if any(kind in ("late", "soon") for kind, _, _ in shown):
            parts.append("Want a status report? Press Report.")
        self._last_keys = tuple(self._key(*f) for f in shown)
        return " ".join(parts)

    def overview_lines(self) -> list[str]:
        """What the last scan found, as short sentences for the daily briefing (nothing is marked as told)."""
        lines = []
        for (kind, name), items in sorted(self._found.items()):
            if kind == "late":
                lines.append(f"{name} has {_plural(len(items), 'item')} past due, like {_list(items, 1)}.")
            elif kind == "soon":
                lines.append(f"{name} has {_plural(len(items), 'item')} due soon, like {_list(items, 1)}.")
        return lines[:3]

    def acknowledge(self) -> None:
        """Call after the message was actually shown, so it isn't repeated."""
        self._pending_updates.clear()
        self._told.update(self._last_keys)
        self._last_keys = ()
