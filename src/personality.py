"""personality.py - Step 7: what Atom says and how he reacts. No window code here.

The window asks this file for a greeting, an idle remark, a wake-up line,
or which mood fits an answer. Everything is plain text and chance, so it is
easy to change: edit the lists below to give Atom your own voice.
"""

from __future__ import annotations

import random
import re
from datetime import datetime


# ------------------------------------------------------------------ name
_NAME_PATTERNS = (
    re.compile(r"\bname\s*(?:is|:)\s*([A-Za-z][\w'-]{1,24})", re.I),
    re.compile(r"\bcall\s+(?:the\s+user|him|her|me|them)\s+([A-Za-z][\w'-]{1,24})", re.I),
)
_NOT_NAMES = {"the", "a", "an", "not", "unknown", "none", "atom", "project", "file"}


def find_name(notes: list[tuple[int, str, str]]) -> str | None:
    """The user's name, if a saved note says it ("User's name is Delro")."""
    for _id, _kind, text in reversed(notes):  # newest note wins
        for pattern in _NAME_PATTERNS:
            match = pattern.search(text)
            if match and match.group(1).lower() not in _NOT_NAMES:
                return match.group(1).capitalize() if match.group(1).islower() else match.group(1)
    return None


# -------------------------------------------------------------- greeting
def part_of_day(now: datetime) -> str:
    hour = now.hour
    if hour < 5:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


_OPENERS = {
    "morning": ["Good morning", "Morning", "Rise and shine"],
    "afternoon": ["Good afternoon", "Hey", "Hi"],
    "evening": ["Good evening", "Hey", "Hi"],
    "night": ["Burning the midnight oil", "Still up", "Hello, night owl"],
}


def _since(now: datetime, last: datetime) -> str:
    days = (now.date() - last.date()).days
    seconds = (now - last).total_seconds()
    if seconds < 3600:
        return "Back already! "
    if days == 0:
        return "Welcome back. "
    if days == 1:
        return "Good to see you again, we last talked yesterday. "
    if days < 7:
        return f"We last talked on {last:%A}. "
    return "It's been a while! "


def greeting(now: datetime, name: str | None = None, last_talked: float | None = None,
             files: int = 0, rng: random.Random | None = None) -> str:
    """A short hello for when Atom starts."""
    rng = rng or random
    opener = rng.choice(_OPENERS[part_of_day(now)])
    punctuation = "?" if opener in ("Still up",) else "!"
    text = f"{opener}, {name}{punctuation} " if name else f"{opener}{punctuation} "
    if last_talked:
        text += _since(now, datetime.fromtimestamp(last_talked))
    if files:
        text += f"I'm keeping an eye on your {files} file{'s' if files != 1 else ''}. "
    else:
        text += "Drop a file on me to get started, or just say hi. "
    text += "I can open apps, play music, crunch numbers and draw charts too."
    return text.strip()


# ------------------------------------------------------------ small talk
IDLE_REMARKS = [
    "I'm right here if you need me.",
    "Fun fact: electrons never sit still. I try to, but it's hard.",
    "Tip: say \"remember my report is due Friday\" and I'll keep a note.",
    "Tip: drop a spreadsheet on me and ask for a chart.",
    "Psst... want a quick status report? Press Report.",
    "Tip: say \"open Excel\" or \"play something chill\" and I'll do it.",
    "All quiet on the files front.",
    "Need a break? I can put on some music.",
    "I'm keeping an eye on your files while you work.",
]

WAKE_LINES = [
    "Oh! You're back.",
    "*yawn* I'm awake! What do we do?",
    "Hi again! I was just resting my electrons.",
    "There you are!",
]

ADDED_OPENERS = ["Got it!", "Nice, thanks!", "Done reading!", "Got them!"]
THINKING_LINES = ["Thinking...", "Hmm, let me see...", "On it!", "One moment..."]


def idle_remark(last: str | None = None, rng: random.Random | None = None) -> str:
    rng = rng or random
    choices = [r for r in IDLE_REMARKS if r != last] or IDLE_REMARKS
    return rng.choice(choices)


def wake_line(rng: random.Random | None = None) -> str:
    return (rng or random).choice(WAKE_LINES)


def added_opener(rng: random.Random | None = None) -> str:
    return (rng or random).choice(ADDED_OPENERS)


def thinking_line(rng: random.Random | None = None) -> str:
    return (rng or random).choice(THINKING_LINES)


# ------------------------------------------------------------------ moods
_WORRIED = re.compile(
    r"^(sorry|something went wrong|i couldn'?t|i can'?t|error|oops|hmm, i couldn'?t)|"
    r"couldn'?t reach|could not|failed|not installed|rate limit|didn'?t catch",
    re.I,
)
_HAPPY = re.compile(
    r"\b(saved|all set|done[.!]|here you go|now playing|i opened|opening|added \d+|"
    r"chart is ready|report is ready|your report|your chart)\b",
    re.I,
)
_LAUGH = re.compile(r"\b(ha ?ha+|hehe+|lol|joke|funny|hilarious)\b|\U0001F602|\U0001F923", re.I)
_SURPRISE = re.compile(r"^(wow|whoa|oh!|oh wow|no way|really\?)|\b(surprising|unexpected|didn'?t expect)\b", re.I)
_SAD = re.compile(r"^(unfortunately|i'?m sorry)|\bsad to|\bmy bad\b|\bno luck\b", re.I)
_PROUD = re.compile(r"\b(nailed it|good news|great news|congrat|well done|you did it|record high|all (?:on )?track)\b", re.I)
_CURIOUS = re.compile(r"\b(which (?:one|file)|do you mean|could you (?:tell|say|clarify)|what would you like)\b|\?\s*$", re.I)


def mood_for(answer: str) -> str:
    """Which face fits this answer. One of: worried, sad, laughing, surprised,
    proud, happy, curious or talking (the plain default)."""
    text = (answer or "").strip()
    if not text:
        return "talking"
    if _WORRIED.search(text):
        return "worried"
    if _SAD.search(text):
        return "sad"
    short = len(text) <= 220
    if short and _LAUGH.search(text):
        return "laughing"
    if short and _SURPRISE.search(text):
        return "surprised"
    if short and _PROUD.search(text):
        return "proud"
    if short and _HAPPY.search(text):
        return "happy"
    if short and _CURIOUS.search(text):
        return "curious"
    return "talking"
