"""callmode.py - Step 13: Atom as a quiet helper during a call or interview.

What this file does (no window code, no microphone code):
  * keeps a log of what was said on a call, and the things the other person asked YOU to do  (calls.db)
  * spots questions and requests in what the other person says
  * writes an answer for you to say - always: from your profile and the AI when it is there, from your
    profile alone when the AI is slow, and as a polite "give me a second" line when nothing else fits
  * at the end, writes a short summary and finishes the to-do list of what was asked

Only you see Atom's answers. Everything is saved on this computer in  ~/.atom/calls.db .
"""

from __future__ import annotations

import queue
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import config

# ======================================================================= the call log


class CallLog:
    """Calls, the lines said in them, and the to-do items that came out of them."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or getattr(config, "CALL_DB", config.DATA_DIR / "calls.db"))
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL NOT NULL, ended REAL,
                title TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT, call_id INTEGER NOT NULL, ts REAL NOT NULL,
                speaker TEXT NOT NULL, text TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, call_id INTEGER NOT NULL, text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0, ts REAL NOT NULL, source TEXT NOT NULL DEFAULT '');
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def start_call(self, title: str = "") -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO calls (started, title) VALUES (?, ?)", (time.time(), title.strip()[:120]))
            self._db.commit()
            return int(cur.lastrowid)

    def end_call(self, call_id: int, summary: str = "") -> None:
        with self._lock:
            self._db.execute("UPDATE calls SET ended = ?, summary = ? WHERE id = ?", (time.time(), summary, call_id))
            self._db.commit()

    def last_call_id(self) -> int | None:
        with self._lock:
            row = self._db.execute("SELECT id FROM calls ORDER BY id DESC LIMIT 1").fetchone()
        return int(row[0]) if row else None

    def call(self, call_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT id, started, ended, title, summary FROM calls WHERE id = ?", (call_id,)).fetchone()
        return dict(zip(("id", "started", "ended", "title", "summary"), row)) if row else None

    def add_line(self, call_id: int, speaker: str, text: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO lines (call_id, ts, speaker, text) VALUES (?, ?, ?, ?)", (call_id, time.time(), speaker, text))
            self._db.commit()

    def lines(self, call_id: int, limit: int | None = None) -> list[tuple[str, str]]:
        """[(speaker, text)] in the order they were said (the newest `limit` if given)."""
        with self._lock:
            rows = self._db.execute("SELECT speaker, text FROM lines WHERE call_id = ? ORDER BY id", (call_id,)).fetchall()
        rows = [(r[0], r[1]) for r in rows]
        return rows[-limit:] if limit else rows

    def add_task(self, call_id: int, text: str, source: str = "") -> bool:
        """Save a to-do from the call. False if (nearly) the same one is already there."""
        text = re.sub(r"\s+", " ", text or "").strip()[:200]
        if not text:
            return False
        norm = _norm(text)
        with self._lock:
            for _, old in self._db.execute("SELECT id, text FROM tasks WHERE call_id = ?", (call_id,)).fetchall():
                if _norm(old) == norm or SequenceMatcher(None, _norm(old), norm).ratio() > 0.85 or _overlap(old, text) >= 0.7:
                    return False
            self._db.execute("INSERT INTO tasks (call_id, text, ts, source) VALUES (?, ?, ?, ?)", (call_id, text, time.time(), source))
            self._db.commit()
        return True

    def tasks(self, call_id: int, include_done: bool = True) -> list[tuple[int, str, bool]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, text, done FROM tasks WHERE call_id = ?" + ("" if include_done else " AND done = 0") + " ORDER BY id",
                (call_id,),
            ).fetchall()
        return [(r[0], r[1], bool(r[2])) for r in rows]

    def set_done(self, task_id: int, done: bool = True) -> None:
        with self._lock:
            self._db.execute("UPDATE tasks SET done = ? WHERE id = ?", (1 if done else 0, task_id))
            self._db.commit()

    def find_task(self, call_id: int, query: str):
        """One task of this call by number or by (part of) its words; (task, error)."""
        items = self.tasks(call_id)
        q = str(query or "").strip().lower()
        if not items:
            return None, "There are no tasks from that call."
        number = re.fullmatch(r"#?\s*(\d+)", q)
        if number:
            for item in items:
                if item[0] == int(number.group(1)):
                    return item, ""
            return None, f"I can't find task number {number.group(1)}."
        found = [i for i in items if q and q in i[1].lower()]
        if len(found) == 1:
            return found[0], ""
        return None, ("More than one task matches. Tell me the number." if found else f"No task matches '{query}'.")

    def tasks_text(self, call_id: int) -> str:
        items = self.tasks(call_id)
        if not items:
            return "Nobody asked you to do anything on that call (that I heard)."
        return "Asked of you:\n" + "\n".join(f"#{i} [{'x' if d else ' '}] {t}" for i, t, d in items)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def _overlap(a: str, b: str) -> float:
    """Share of words two lines have in common (1.0 = the same words)."""
    x, y = set(_norm(a).split()), set(_norm(b).split())
    return len(x & y) / len(x | y) if x and y else 0.0


# ================================================================== questions and requests
_DAYS = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|today|noon|end of (?:the )?(?:day|week|month)|eod|next week|next month|this week|the weekend"
_DEADLINE = re.compile(r"\b(?:by|before|until|due(?: on| by)?|no later than)\s+(?:" + _DAYS + r"|\d{1,2}(?::\d\d)?\s*(?:am|pm)?|the \d{1,2}(?:st|nd|rd|th)?|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2})\b", re.I)
_ACTION_VERB = r"send|email|e-mail|forward|share|submit|prepare|fix|update|finish|complete|review|schedule|book|call|ring|follow up|bring|upload|write|draft|set up|check|confirm|sign|fill|reply|respond|get back|finalise|finalize|deliver|test|ship|push|merge|create|make|build|add|remove|look into|look at|take care"
# things the other person asks that are interview questions, not jobs for you
_NOT_A_JOB = r"tell me|tell us|explain|describe|walk (?:me|us)|share your|give (?:me|us) an? (?:example|overview|summary)|introduce|elaborate|talk (?:me|us)|talk about|hear me|see me|see my|see the screen|see this|hear us|hear you|see you|speak up|repeat|say that again|go ahead|start|begin|answer|think|imagine|assume|pretend|suppose|explain|clarify"

_REQUEST_PATTERNS = [
    re.compile(r"\b(?:can|could|would|will) you (?:please )?(?:also )?(?!(?:" + _NOT_A_JOB + r")\b)(?P<what>(?:" + _ACTION_VERB + r")\b.+)", re.I),
    re.compile(r"\b(?:i|we)(?:'d| would| will)?\s+(?:need|want|like|expect)\s+you\s+to\s+(?!(?:" + _NOT_A_JOB + r")\b)(?P<what>.+)", re.I),
    re.compile(r"\b(?:you(?:'ll| will)? (?:need|have) to|you (?:should|must)|make sure (?:that )?you|don'?t forget to|remember to|please)\s+(?!(?:" + _NOT_A_JOB + r")\b)(?P<what>.+)", re.I),
    re.compile(r"^(?P<what>(?:" + _ACTION_VERB + r")\b.+\b(?:" + _DAYS + r")\b.*)$", re.I),   # "Send me the report by Friday."
    re.compile(r"\b(?:follow up|get back to (?:me|us)|let (?:me|us) know|keep (?:me|us) posted)\b(?P<what>.*)", re.I),
]
_FILLER = re.compile(r"^(?:(?:so|and|ok|okay|um+|uh+|yeah|well|right|then|also|just|actually|please|alright)[,\s]+)+", re.I)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.?!])\s+", re.sub(r"\s+", " ", text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _clean_task(sentence: str, what: str) -> str:
    text = _FILLER.sub("", (what or sentence).strip(" ?.!,"))
    if len(text.split()) < 2:
        text = _FILLER.sub("", sentence.strip(" ?.!,"))
    text = re.sub(r"\s+", " ", text)
    return (text[:1].upper() + text[1:])[:160]


def find_requests(text: str) -> list[str]:
    """Things the other person asks you to do, as short to-do lines. 'Can you send me the report by Friday?'
    -> 'Send me the report by Friday'. Interview questions ('can you tell me about...') are not jobs."""
    out: list[str] = []
    for sentence in split_sentences(text):
        low = sentence.lower()
        if re.search(r"\b(?:" + _NOT_A_JOB + r")\b", low) and not _DEADLINE.search(low):
            continue
        for pattern in _REQUEST_PATTERNS:
            found = pattern.search(sentence)
            if found:
                what = found.groupdict().get("what") or ""
                if pattern is _REQUEST_PATTERNS[-1]:
                    what = sentence                               # "let me know..." is a job in itself
                task = _clean_task(sentence, what)
                if len(task.split()) >= 3 and task.lower() not in {t.lower() for t in out}:
                    out.append(task)
                break
        else:
            # a sentence with a deadline and an action ("the report is due by Friday")
            if _DEADLINE.search(sentence) and re.search(r"\b(?:" + _ACTION_VERB + r"|report|deadline|deliverable|document|slides|proposal|draft)\b", low):
                task = _clean_task(sentence, sentence)
                if len(task.split()) >= 3:
                    out.append(task)
    return out


_Q_START = re.compile(
    r"^(?:so,?\s+|and,?\s+|okay,?\s+|ok,?\s+)?(?:what|why|how|when|where|who|which|whose|tell (?:me|us)|describe|explain|walk (?:me|us)|"
    r"give (?:me|us)|share|talk (?:me|us)|name|list|elaborate|can you|could you|would you|do you|did you|have you|are you|were you|"
    r"is there|if you|suppose|imagine|let'?s say)\b", re.I)


def is_question(sentence: str) -> bool:
    s = sentence.strip()
    if len(s.split()) < 2:
        return False
    if s.endswith("?"):
        return True
    return bool(_Q_START.match(s)) and len(s.split()) >= 4 and not s.lower().startswith(("can you hear", "could you hear"))


# short everyday lines that need no AI: (pattern, answer)
_QUICK = [
    (re.compile(r"\b(?:can|could) you (?:hear|see) (?:me|us)\b|\bare you there\b|\bcan you hear\b|\bam i (?:audible|coming through|breaking up)\b|\bis my (?:audio|sound|mic) ok\b", re.I),
     "Yes, I can hear you clearly."),
    (re.compile(r"\b(?:can|could) you see (?:my|the|this) screen\b|\bsee my screen\b", re.I), "Yes, I can see your screen."),
    (re.compile(r"\bhow are you(?: doing| today| this (?:morning|afternoon|evening))?\b|\bhow'?s it going\b|\bhow have you been\b|\bhow is your day\b", re.I),
     "I'm doing well, thank you. How are you?"),
    (re.compile(r"\bdo you have any (?:questions|other questions)\b|\bany questions (?:for|from) (?:us|me|you)\b|\bquestions for (?:us|me)\b|\bis there anything you'?d like to ask\b", re.I),
     "Yes, one question: what would success look like in this role in the first three months?"),
    (re.compile(r"\bthanks? (?:you )?for (?:joining|coming|being here|having me)\b", re.I), "Thank you for having me."),
    (re.compile(r"\bthanks? (?:you )?for (?:your time|taking the time|meeting with (?:us|me))\b|\bthat'?s (?:all|everything) (?:i|we) (?:had|have)\b|\bwe'?ll be in touch\b|\bwe will be in touch\b|\bwe'?ll get back to you\b|\bnice (?:talking|meeting|speaking)\b", re.I),
     "Thank you for your time. I really enjoyed the conversation and I look forward to hearing from you."),
    (re.compile(r"^(?:hi|hello|hey|good (?:morning|afternoon|evening))\b[\s,!.a-z']{0,40}$", re.I), "Hello, good to meet you."),
    (re.compile(r"\bcan you (?:hear|see) me (?:ok|okay|now|alright)\b|\bis this a good time\b", re.I), "Yes, this is a good time."),
]


def quick_answer(text: str, last_only: bool = False) -> str | None:
    """A ready one-line answer for everyday call talk ('can you hear me?', 'how are you?'), else None.
    With last_only, only the final sentence counts (the sentence before it is just the scene)."""
    sentences = list(reversed(split_sentences(text)))
    for sentence in sentences[:1] if last_only else sentences:
        for pattern, answer in _QUICK:
            if pattern.search(sentence):
                return answer
    return None


def classify(text: str) -> tuple[str, str]:
    """(kind, the sentence that needs an answer). kind: 'smalltalk', 'request', 'question' or 'statement'."""
    for sentence in reversed(split_sentences(text)):
        if quick_answer(sentence):
            return "smalltalk", sentence
        if is_question(sentence):
            kind = "request" if find_requests(sentence) and not re.search(r"\b(?:" + _NOT_A_JOB + r")\b", sentence.lower()) else "question"
            return kind, sentence
        if find_requests(sentence):
            return "request", sentence
    return "statement", ""


def question_context(text: str, kind: str, focus: str) -> str:
    """The sentence to answer, plus the sentence before it when that one is short (it often sets the scene)."""
    sentences = split_sentences(text)
    if focus in sentences:
        i = sentences.index(focus)
        if i > 0 and len(sentences[i - 1]) < 160 and not sentences[i - 1].endswith("?"):
            return f"{sentences[i - 1]} {focus}"
    return focus


_NEEDS_SCREEN = re.compile(
    r"\bon (?:my|the|your) screen\b|\bshar\w* (?:my|the|your) screen\b|\bwhat do you see\b|\blook at (?:this|that|the)\b|\bread (?:this|that|it)\b|"
    r"\b(?:this|these|that|the following) (?:code|error|bug|function|query|page|slide|chart|graph|table|diagram|output|problem|snippet|sheet|document|email|message)\b|"
    r"\bwhat'?s (?:on|in) (?:front of you|this)\b|\bshown (?:here|on)\b|\bas you can see\b|\bon the (?:slide|board|page)\b", re.I)


def needs_screen(question: str) -> bool:
    return bool(_NEEDS_SCREEN.search(question or ""))


# ====================================================================== answering


@dataclass
class Answer:
    text: str
    source: str            # 'quick', 'ai', 'profile' or 'stall'
    grounded: bool = True  # False when the profile did not cover it


_STALL = [
    "That's a good question. Let me take a moment to think it through, and then I'll answer it properly.",
    "Good question. Could I take a second to organise my thoughts?",
    "Let me think about that for a moment. Could you tell me a bit more about what you're looking for?",
]


def stall_answer(question: str) -> str:
    """The last-resort line: always something polite to say."""
    return _STALL[sum(map(ord, question or "")) % len(_STALL)]


CALL_SYSTEM = (
    "You are Atom, quietly helping {who} during a live call or interview. Only {who} can see your answer.\n"
    "Write the answer {who} can SAY OUT LOUD: first person ('I ...'), natural spoken English, 1 to 4 short sentences "
    "(under 70 words) unless the question clearly needs more. No markdown, no bullet points, no labels, no quotation marks.\n"
    "Facts about their skills, jobs, projects, education, numbers or dates must come ONLY from PROFILE. Never invent employers, "
    "titles, numbers or years.\n"
    "If PROFILE does not cover the question, still give a short, honest, general answer they can say, and start it with "
    "'(not in your profile) '. If you cannot answer at all, write one polite line that buys time or asks a clarifying question.\n"
    "If the other person asked them to do something, write a short reply that confirms what was asked and the deadline, "
    "without promising anything more.\n"
    "If SCREEN text is given it is what is visible on their screen (read by OCR, so it may contain mistakes). It can include browser "
    "tabs, menus, ads and other noise: focus ONLY on the one question, problem or task in it and ignore the rest.\n"
    "Never refuse and never mention that you are an AI."
)


SCREEN_PROBLEM = (
    "\nTHE USER POINTED AT ONE PROBLEM ON THEIR SCREEN (the SCREEN text). Solve or answer exactly that problem. If it is code, a formula "
    "or a calculation, give the simplest correct solution a beginner would write, as plain lines (no markdown, no comments), then ONE "
    "short sentence on how it works. If it is a question to answer in words, give a short answer they can say. This overrides the "
    "length and first-person rules above."
)


def build_prompt(who: str, profile_text: str, screen_text: str, recent: list[tuple[str, str]], question: str,
                 from_screen: bool = False) -> tuple[str, str]:
    system = CALL_SYSTEM.format(who=who or "the user") + (SCREEN_PROBLEM if from_screen else "")
    convo = "\n".join(f"{'Them' if s == 'them' else 'Me'}: {t}" for s, t in recent[-6:])
    user = [f"PROFILE:\n{profile_text or '(empty)'}"]
    if screen_text:
        user.append(f"SCREEN:\n{screen_text[:2500]}")
    if convo:
        user.append(f"RECENT CONVERSATION:\n{convo}")
    if from_screen:
        user.append("Write the answer to the problem on the screen now.")
    else:
        user.append(f'THE OTHER PERSON JUST SAID: "{question}"\nWrite the answer now.')
    return system, "\n\n".join(user)


def tidy_answer(text: str, keep_code: bool = False) -> Answer | None:
    if keep_code:                                   # an answer to a problem on screen: keep the code exactly, drop only the ``` lines
        lines = [ln.rstrip() for ln in str(text or "").splitlines() if not ln.lstrip().startswith("```")]
        text = "\n".join(lines).strip()
        return Answer(text[:1500], "screen", True) if text else None
    text = re.sub(r"[*_`#>]+", "", str(text or "")).strip()
    text = re.sub(r"^(?:answer|suggested answer|you could say|say)\s*:\s*", "", text, flags=re.I).strip().strip('"').strip()
    if not text:
        return None
    grounded = not text.lower().startswith("(not in your profile)")
    return Answer(text[:700], "ai", grounded)


def instant_answer(question: str, profile) -> Answer:
    """The answer shown at once, before the AI replies: a ready line, your profile, or a polite stall."""
    quick = quick_answer(question, last_only=True)
    if quick:
        return Answer(quick, "quick")
    if profile is not None:
        try:
            mine = profile.first_person(question)
        except Exception:
            mine = ""
        if mine:
            return Answer(mine, "profile")
    return Answer(stall_answer(question), "stall", grounded=False)


def ai_answer(question: str, *, profile, ask, who: str = "", screen_text: str = "", recent=(), from_screen: bool = False) -> Answer | None:
    """The AI's answer, or None when there is no AI or it fails. `ask(system, user) -> text`."""
    if ask is None:
        return None
    ctx = ""
    if profile is not None:
        try:
            ctx = profile.context(question)
        except Exception:
            ctx = ""
    system, user = build_prompt(who, ctx, screen_text, list(recent), question, from_screen)
    try:
        return tidy_answer(ask(system, user), keep_code=from_screen)
    except Exception as error:
        print(f"[atom] call answer failed: {error}", flush=True)
        return None


def ai_summary(ask, lines: list[tuple[str, str]], who: str = "") -> tuple[str, list[str]]:
    """(summary, tasks) written by the AI from the whole call; ('', []) if it fails."""
    if ask is None or not lines:
        return "", []
    text = "\n".join(f"{'Them' if s == 'them' else 'Me'}: {t}" for s, t in lines)[-5000:]
    system = (
        "You read the transcript of a call (Them = the other person, Me = the user). Reply in exactly this format:\n"
        "SUMMARY:\n- up to 4 short bullets of what was discussed\nTASKS:\n- one line for each thing Them asked or expects the user "
        "to do (with the deadline if said), or 'none'\nUse only what is in the transcript."
    )
    try:
        reply = str(ask(system, text) or "")
    except Exception as error:
        print(f"[atom] call summary failed: {error}", flush=True)
        return "", []
    summary, _, tasks_part = reply.partition("TASKS:")
    summary = summary.replace("SUMMARY:", "").strip()
    tasks = [re.sub(r"^[-*\d.)\s]+", "", l).strip() for l in tasks_part.splitlines()]
    return summary, [t for t in tasks if t and t.lower() != "none" and len(t) > 3]


def plain_summary(call: dict | None, lines: list[tuple[str, str]], tasks: list) -> str:
    """A summary without AI: how long, how much was said, what was asked of you."""
    minutes = 0
    if call and call.get("started"):
        minutes = max(1, round(((call.get("ended") or time.time()) - call["started"]) / 60))
    theirs = sum(1 for s, _ in lines if s == "them")
    text = f"Call of about {minutes} min; {theirs} things said by them."
    if tasks:
        text += f" {len(tasks)} thing{'s' if len(tasks) != 1 else ''} asked of you: " + "; ".join(t[1] for t in tasks[:5]) + "."
    return text


# ===================================================================== the controller


class CallController:
    """Runs a call session: hears audio chunks, turns them into text, spots requests and questions, and
    reports to the window through the `on_*` functions (they may be called from any thread).

    Everything that talks to the outside world is passed in, so it can be tested without a microphone:
      transcribe(pcm, hint) -> text      ask(system, user) -> text      screen() -> text
    """

    def __init__(self, log: CallLog, profile=None, *, ask=None, transcribe=None, screen=None, who=None):
        self.log = log
        self.profile = profile
        self.ask = ask
        self.screen = screen
        self.who = who or (lambda: "")
        self._transcribe = transcribe
        self.auto_answer = True
        self.read_screen_always = False
        self.call_id: int | None = None
        self.listeners: list = []
        self.on_line = lambda speaker, text: None
        self.on_task = lambda task: None
        self.on_answer = lambda question, answer, final: None
        self.on_status = lambda text: None
        self.on_error = lambda text: None
        self.on_summary = lambda text: None
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._seq = 0
        self._last_question = ("", 0.0)
        self._last_error = 0.0
        self.active = False

    # -- life of a call
    def start(self, listener_factory, title: str = "") -> int:
        """Begin a call. `listener_factory(controller)` returns the audio listeners (already built, not started)."""
        if self.active:
            return self.call_id or 0
        self.call_id = self.log.start_call(title)
        self.active = True
        self._worker = threading.Thread(target=self._work, name="atom-call", daemon=True)
        self._worker.start()
        self.listeners = list(listener_factory(self) or [])
        for listener in self.listeners:
            listener.start()
        self.on_status("Listening")
        timer = threading.Timer(config.CALL_SILENCE_WARNING, self._check_hearing, args=(self.call_id,))
        timer.daemon = True
        timer.start()
        return self.call_id

    def _check_hearing(self, call_id: int) -> None:
        """If the call audio is silent for a long time the wrong output is probably selected: say so once."""
        if not self.active or call_id != self.call_id:
            return
        if self.listeners and not any(getattr(l, "heard_anything", True) for l in self.listeners):
            self.on_error("I can't hear any sound yet. Atom listens to what comes out of your DEFAULT speakers or headphones - "
                          "check that the call is playing there (Windows sound settings > Output).")

    def stop(self, wait: bool = False):
        """End the call. The summary is written in the background (or here, with wait=True)."""
        if not self.active:
            return None
        self.active = False
        for listener in self.listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self.listeners = []
        self._queue.put(None)
        if self._worker:
            self._worker.join(timeout=8)
        call_id = self.call_id
        thread = threading.Thread(target=self._finish, args=(call_id,), daemon=True)
        thread.start()
        if wait:
            thread.join(timeout=30)
        return call_id

    def _finish(self, call_id: int | None) -> None:
        if call_id is None:
            return
        lines = self.log.lines(call_id)
        summary, tasks = ai_summary(self.ask, lines, self.who())
        for task in tasks:
            if self.log.add_task(call_id, task, source="summary"):
                self.on_task(task)
        if not summary:
            summary = plain_summary(self.log.call(call_id), lines, self.log.tasks(call_id))
        self.log.end_call(call_id, summary)
        self.on_summary(summary)

    # -- audio in
    def hear(self, pcm: bytes, speaker: str = "them") -> None:
        """An utterance of 16 kHz 16-bit mono audio (called by the listeners)."""
        if self.active:
            self._queue.put((pcm, speaker))

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            pcm, speaker = item
            try:
                hint = ", ".join(self.profile.keywords(20)) if self.profile is not None else ""
                text = (self._transcribe or _default_transcribe)(pcm, hint)
            except Exception as error:
                now = time.time()
                if now - self._last_error > 30:        # one message, not one per sentence
                    self._last_error = now
                    self.on_error(f"I couldn't turn the call audio into text: {error}")
                continue
            if text:
                try:
                    self.handle_text(speaker, text)
                except Exception as error:
                    print(f"[atom] call line failed: {error}", flush=True)

    # -- one line of the call
    def handle_text(self, speaker: str, text: str) -> None:
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text:
            return
        if self.call_id is None:
            self.call_id = self.log.start_call()
        self.log.add_line(self.call_id, speaker, text)
        self.on_line(speaker, text)
        if speaker != "them":
            return
        for task in find_requests(text):
            if self.log.add_task(self.call_id, task, source=text):
                self.on_task(task)
        kind, focus = classify(text)
        if self.auto_answer and kind in ("question", "request", "smalltalk"):
            self.answer_async(question_context(text, kind, focus) if kind != "smalltalk" else focus)

    # -- answers
    def answer_async(self, question: str, screen_text: str | None = None) -> None:
        """Show an answer at once, then (in the background) a better one from the AI.
        screen_text = words you picked off the screen: the answer is about that one problem."""
        question = (question or "").strip()
        if not question:
            return
        now = time.time()
        if question.lower() == self._last_question[0].lower() and now - self._last_question[1] < 20 and screen_text is None:
            return                                           # the same question again: already answered
        self._last_question = (question, now)
        self._seq += 1
        seq = self._seq
        if screen_text is not None:
            first = Answer("Looking at the problem you showed me...", "screen", grounded=True)
        else:
            first = instant_answer(question, self.profile)
        wants_ai = first.source != "quick" and self.ask is not None
        self.on_answer(question, first, not wants_ai)
        if wants_ai:
            threading.Thread(target=self._better_answer, args=(seq, question, first, screen_text), daemon=True).start()

    def _better_answer(self, seq: int, question: str, first: Answer, picked: str | None = None) -> None:
        screen_text = picked or ""
        if picked is None and self.screen is not None and (self.read_screen_always or needs_screen(question)):
            try:
                screen_text = self.screen() or ""
            except Exception as error:
                print(f"[atom] couldn't read the screen: {error}", flush=True)
        recent = self.log.lines(self.call_id, 8) if self.call_id else []
        better = ai_answer(question, profile=self.profile, ask=self.ask, who=self.who(), screen_text=screen_text, recent=recent,
                           from_screen=picked is not None)
        if seq != self._seq:
            return                                           # a newer question came in: this one is old news
        self.on_answer(question, better or first, True)

    def ask_now(self, question: str) -> None:
        """You typed a question into the panel: answer it the same way."""
        self._last_question = ("", 0.0)
        self.answer_async(question)

    def ask_screen(self, screen_text: str) -> None:
        """You picked a problem on the screen: answer that one problem (not the whole screen)."""
        self.answer_async("The problem on my screen", screen_text=(screen_text or "").strip() or None)


def _default_transcribe(pcm: bytes, hint: str = "") -> str:
    import voice
    return voice.transcribe(pcm, hint=hint)
