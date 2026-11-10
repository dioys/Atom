"""userprofile.py - Step 13: Atom's memory of YOU - your skills, your experience and the files that describe you.

Two kinds of things live here:
  * short facts you (or Atom) typed:  "skill: Python", "experience: 3 years as a data analyst", ...
  * "profile files": any file you pointed at - a CV, a skills list, a project report - kept wherever it
    already is on your computer (Atom does not need them in one folder).

When someone asks "what are your skills?", Atom looks here first. Everything is saved on this computer
in  ~/.atom/profile.db  and nothing is sent anywhere by this file.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import config
from tools import ABOUT_ME_FOLDER, DEFAULT_FOLDER

KINDS = ("skill", "experience", "project", "education", "strength", "about")
_PLURAL = {"skill": "skills", "experience": "experience", "project": "projects",
           "education": "education", "strength": "strengths", "about": "about me"}

# words in a question -> the kinds of facts worth looking at
_KIND_WORDS = {
    "skill": r"skills?|skilled|good at|expert|expertise|proficien\w*|tech stack|technolog\w*|tools?|languages?|software|strong(?:est)?",
    "strength": r"strengths?|best at|excel|stand out|why should|why (?:do )?we hire|what makes you|value you bring",
    "experience": r"experience|worked|work history|background|career|employ\w*|role|position|job|company|responsibilit\w*|accomplish\w*|achiev\w*",
    "project": r"projects?|built|portfolio|developed|created|case study|proud of",
    "education": r"education|degree|school|studied|study|graduat\w*|universit\w*|college|course\w*|certif\w*|training",
}
_INTRO = r"about (?:your|yourself)|introduce|who are you|walk me through your (?:resume|cv|background)|your background|describe yourself"
_STOP = set("the a an and or of to in on at for with is are was were be been do does did you your yours i me my we our "
            "this that it its as by from what which who how why when where can could would will tell about have has had "
            "please any some just into over more most very".split())


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9+#.]+", (text or "").lower()):
        w = w.strip(".")
        if len(w) < 2 or w in _STOP:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


@dataclass
class Item:
    id: int
    kind: str
    text: str


class Profile:
    """Facts about the user plus the files that describe them."""

    def __init__(self, store, path: Path | None = None):
        self.store = store
        self.path = Path(path or getattr(config, "PROFILE_DB", config.DATA_DIR / "profile.db"))
        self._lock = threading.RLock()
        self.ask = None          # set by Brain: function(system, user) -> text, used by learn_from_files
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, text TEXT NOT NULL, ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS pinned (
                path TEXT PRIMARY KEY, ts REAL NOT NULL);
            """
        )
        self._db.commit()
        self._adopt_old_pins()

    def _adopt_old_pins(self) -> None:
        """Earlier versions kept their own list of profile files. Now the Files folder 'About me' is the list."""
        with self._lock:
            old = [row[0] for row in self._db.execute("SELECT path FROM pinned").fetchall()]
            if not old:
                return
            try:
                self.store.set_folder(old, ABOUT_ME_FOLDER)
            except Exception:
                return
            self._db.execute("DELETE FROM pinned")
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------ typed facts
    @staticmethod
    def _kind(kind: str) -> str:
        kind = (kind or "skill").strip().lower()
        for k in KINDS:
            if kind == k or kind == _PLURAL[k]:
                return k
        return "skill"

    def add(self, text: str, kind: str = "skill") -> tuple[bool, str]:
        """Save one fact. Returns (is_new, the fact as saved)."""
        text = re.sub(r"\s+", " ", str(text or "").strip(" -*\t"))[:240]
        if not text:
            raise ValueError("Tell me what to add.")
        kind = self._kind(kind)
        with self._lock:
            row = self._db.execute("SELECT id FROM items WHERE lower(text) = lower(?) AND kind = ?", (text, kind)).fetchone()
            if row:
                return False, text
            self._db.execute("INSERT INTO items (kind, text, ts) VALUES (?, ?, ?)", (kind, text, time.time()))
            self._db.commit()
        return True, text

    def add_many(self, text: str, kind: str = "skill") -> list[str]:
        """'Python, SQL and Power BI' -> three skills. Longer sentences stay in one piece."""
        text = str(text or "").strip()
        kind = self._kind(kind)
        parts = [text]
        if kind in ("skill", "strength") and len(text) < 400:
            parts = [p for p in re.split(r"\s*(?:,|;|\n|\band\b|&|/)\s*", text) if p.strip()]
        added = []
        for part in parts:
            is_new, saved = self.add(part, kind)
            if is_new:
                added.append(saved)
        return added

    def items(self, kind: str | None = None) -> list[Item]:
        with self._lock:
            if kind:
                rows = self._db.execute("SELECT id, kind, text FROM items WHERE kind = ? ORDER BY id", (self._kind(kind),)).fetchall()
            else:
                rows = self._db.execute("SELECT id, kind, text FROM items ORDER BY id").fetchall()
        return [Item(*r) for r in rows]

    def remove(self, what: str) -> int:
        """Delete the facts containing all the words of `what` (or the one with that number)."""
        what = str(what or "").strip()
        if not what:
            return 0
        number = re.fullmatch(r"#?\s*(\d+)", what)
        with self._lock:
            if number:
                cur = self._db.execute("DELETE FROM items WHERE id = ?", (int(number.group(1)),))
                self._db.commit()
                return cur.rowcount
            words = [w for w in re.findall(r"\w+", what.lower()) if len(w) > 1]
            removed = 0
            for item in self.items():
                low = item.text.lower()
                if words and all(w in low for w in words):
                    self._db.execute("DELETE FROM items WHERE id = ?", (item.id,))
                    removed += 1
            self._db.commit()
        return removed

    # ----------------------------------------------------------- profile files
    def _record_for(self, name: str):
        """The library record for a file name (or part of it); None if there is none or it is unclear."""
        needle = str(name or "").strip().lower()
        records = self.store.all()
        found = [r for r in records if r.name.lower() == needle or r.path.lower() == needle]
        if not found and needle:
            found = [r for r in records if needle in r.name.lower()]
        return found[0] if len(found) == 1 else None

    def pin(self, name_or_path: str) -> tuple[bool, str]:
        """Make a file part of the profile. `name_or_path` is a file Atom already has, or any path on this
        computer (Atom reads it first). Returns (ok, message)."""
        target = str(name_or_path or "").strip().strip('"')
        if not target:
            return False, "Which file?"
        record = self._record_for(target)
        if record is None and os.path.isfile(target):
            self.store.add([target])
            record = self._record_for(target)
        if record is None:
            matches = [r.name for r in self.store.all() if target.lower() in r.name.lower()]
            if len(matches) > 1:
                return False, "More than one file matches: " + ", ".join(matches[:6]) + ". Tell me which."
            return False, f"I don't have a file called '{target}'. Add it first, or give me its full path."
        self.store.set_folder([record.path], ABOUT_ME_FOLDER)
        return True, f"{record.name} is now part of your profile (folder: {ABOUT_ME_FOLDER})."

    def unpin(self, name: str) -> tuple[bool, str]:
        record = next((r for r in self.pinned() if str(name or "").strip().lower() in r.name.lower()), None)
        if record is None:
            return False, f"'{name}' is not one of your profile files."
        self.store.set_folder([record.path], DEFAULT_FOLDER)
        return True, f"{record.name} is no longer part of your profile (it is in {DEFAULT_FOLDER} now)."

    def pinned(self) -> list:
        return self.store.in_folder(ABOUT_ME_FOLDER)

    def is_empty(self) -> bool:
        return not self.items() and not self.pinned()

    # ------------------------------------------------------------------ reading
    def keywords(self, limit: int = 40) -> list[str]:
        """Short skill words (for helping speech recognition with names like 'Power BI')."""
        out = []
        for item in self.items():
            if item.kind in ("skill", "strength") and len(item.text) <= 30 and item.text not in out:
                out.append(item.text)
        return out[:limit]

    def _kinds_for(self, question: str) -> set[str]:
        low = (question or "").lower()
        return {k for k, pattern in _KIND_WORDS.items() if re.search(r"\b(?:" + pattern + r")\b", low)}

    def _is_intro(self, question: str) -> bool:
        return bool(re.search(_INTRO, (question or "").lower()))

    def _file_pieces(self, question: str, limit: int, overview: bool) -> list[tuple[str, str]]:
        """(file name, excerpt) from the profile files that best fit the question."""
        pinned = {r.id: r for r in self.pinned()}
        if not pinned:
            return []
        out: list[tuple[str, str]] = []
        for hit in self.store.search(question, limit=60):
            if hit.file_id in pinned and len(out) < limit:
                out.append((hit.name, hit.text.strip()))
        if not out and overview:
            for record in pinned.values():
                for text in self.store.chunks_of(record.id, 1):
                    out.append((record.name, text.strip()))
        return out[:limit]

    def search(self, question: str, limit: int = 8) -> list[Item]:
        """Typed facts that fit the question, best first."""
        wanted = _tokens(question)
        kinds = self._kinds_for(question)
        scored = []
        for item in self.items():
            score = len(wanted & _tokens(item.text)) * 2 + (1 if item.kind in kinds else 0)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda s: (-s[0], s[1].id))
        return [item for _, item in scored[:limit]]

    def context(self, question: str, max_chars: int = 1800) -> str:
        """What Atom knows about you that fits `question` - for answering a call or interview question.
        Empty string if there is nothing."""
        generic = self._is_intro(question) or not (self._kinds_for(question) or _tokens(question))
        lines: list[str] = []
        seen: set[int] = set()
        for item in self.search(question, 10):
            seen.add(item.id)
            lines.append(f"- ({item.kind}) {item.text}")
        if generic or not lines:
            for item in self.items():                    # nothing specific matched: the basics
                if item.id not in seen and len(lines) < 16:
                    lines.append(f"- ({item.kind}) {item.text}")
        pieces = self._file_pieces(question, limit=3, overview=generic or not lines)
        text = ""
        if lines:
            text += "Facts about the user:\n" + "\n".join(lines)
        for name, excerpt in pieces:
            text += f"\n\nFrom the user's file {name}:\n{excerpt[:700]}"
        return text.strip()[:max_chars]

    def relevant(self, text: str, max_chars: int = 700) -> str:
        """A short block for ordinary chat: only when the question is about the user's skills or background."""
        if self.is_empty():
            return ""
        about_me = self._kinds_for(text) or self._is_intro(text)
        if not about_me and not self.search(text, 3):
            return ""
        return self.context(text, max_chars)

    def overview(self, max_chars: int = 1500) -> str:
        parts = []
        for kind in KINDS:
            facts = [i.text for i in self.items(kind)]
            if facts:
                parts.append(f"{_PLURAL[kind].capitalize()}: " + "; ".join(facts))
        for record in self.pinned():
            parts.append(f"File: {record.name}")
        return "\n".join(parts)[:max_chars] or "Nothing in your profile yet."

    def first_person(self, question: str) -> str:
        """A simple answer written only from the profile (used when the AI is slow or offline). '' if no facts."""
        kinds = self._kinds_for(question)
        intro = self._is_intro(question)
        pools = {k: [i.text for i in self.items(k)] for k in KINDS}
        say = []

        def join(facts: list[str], n: int) -> str:
            facts = facts[:n]
            return facts[0] if len(facts) == 1 else ", ".join(facts[:-1]) + " and " + facts[-1]

        if not kinds and not intro:                       # "Do you know Power BI?": answer about that one thing
            hits = self.search(question, 3)
            skills = [h.text for h in hits if h.kind == "skill"]
            if skills:
                return "Yes, " + join(skills, 3) + (" is one of my skills." if len(skills) == 1 else " are among my skills.")
            if hits:
                return "From my background: " + join([h.text for h in hits], 3) + "."
            return ""
        if pools["skill"] and ("skill" in kinds or intro):
            say.append("My main skills are " + join(pools["skill"], 6) + ".")
        if pools["strength"] and ("strength" in kinds or intro):
            say.append("My strengths are " + join(pools["strength"], 4) + ".")
        if pools["experience"] and ("experience" in kinds or intro):
            say.append("In terms of experience, " + join(pools["experience"], 3) + ".")
        if pools["project"] and ("project" in kinds or intro):
            say.append("A project I can talk about: " + join(pools["project"], 2) + ".")
        if pools["education"] and ("education" in kinds or intro):
            say.append("On education, " + join(pools["education"], 2) + ".")
        if pools["about"] and intro:
            say.insert(0, pools["about"][0].rstrip(".") + ".")
        if not say:                                       # the question named a kind but there are no facts of it
            hits = self.search(question, 3)
            if hits:
                say.append("From my background: " + join([h.text for h in hits], 3) + ".")
        return " ".join(say)

    # ----------------------------------------------------------- learn from files
    def learn_from_files(self, max_chars: int = 6000) -> int:
        """Ask the AI to list the skills and experience in the profile files and save them as short facts.
        Returns how many new facts were saved. Needs `self.ask` (set by Brain)."""
        if self.ask is None:
            raise RuntimeError("No AI is available to read the files.")
        total = 0
        system = (
            "You read a document about one person (a CV, a skills list, a project report). List facts about them, one per "
            "line, each starting with one of these labels followed by a colon: skill, experience, project, education, "
            "strength. Keep each line under 20 words. Use ONLY what the document says; never invent anything. "
            "If the document has no such facts, answer: none"
        )
        for record in self.pinned():
            text = " ".join(self.store.chunks_of(record.id, 12))[:max_chars]
            if not text.strip():
                continue
            reply = self.ask(system, f"Document: {record.name}\n\n{text}")
            for line in str(reply or "").splitlines():
                found = re.match(r"\s*[-*]?\s*(skill|experience|project|education|strength)s?\s*:\s*(.+)", line, re.I)
                if found:
                    try:
                        is_new, _ = self.add(found.group(2), found.group(1))
                    except ValueError:
                        continue
                    total += 1 if is_new else 0
        return total
