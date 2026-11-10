"""timeparse.py - Step 11: turns "tomorrow 9am", "in 20 minutes", "friday 3pm", "nov 10 at 2:30pm"
into a real date and time. Plain rules, no AI, no internet.

    parse_when(text, now)    -> datetime, or None when the words aren't understood
    split_repeat(text)       -> (text without "every ...", "daily" | "weekdays" | "weekly" | "monthly" | "")
    next_after(due, repeat, now) -> the next time a repeating reminder should fire
    nice(dt, now)            -> "today 3:00 PM", "tomorrow 9:00 AM", "Fri 6 Nov, 10:00 AM"
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
PART_OF_DAY = {"morning": (9, 0), "afternoon": (15, 0), "evening": (18, 0), "tonight": (20, 0),
               "noon": (12, 0), "midday": (12, 0), "lunch": (12, 0), "lunchtime": (12, 0),
               "midnight": (0, 0), "eod": (17, 0), "end of day": (17, 0), "end of the day": (17, 0)}
DEFAULT_TIME = (9, 0)
UNITS = {"sec": 1 / 60, "second": 1 / 60, "min": 1, "minute": 1, "hr": 60, "hour": 60, "day": 1440, "week": 10080}

_DAY_NAMES = r"(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
_WEEKDAY_RE = r"\b(?:(next|this|coming)\s+)?(" + _DAY_NAMES + r")\b"
_MONTH_RE = "|".join(m[:3] for m in MONTHS)


def _weekday_index(word: str) -> int:
    for i, name in enumerate(WEEKDAYS):
        if name.startswith(word[:3]):
            return i
    return 0


def _month_index(word: str) -> int:
    for i, name in enumerate(MONTHS):
        if name.startswith(word[:3]):
            return i + 1
    return 1


def _clean(text: str) -> str:
    s = str(text or "").lower().strip()
    s = s.replace("o'clock", "").replace("oclock", "")
    s = re.sub(r"[,!?]|\bplease\b|\bthe\b|\bat\b|\bon\b|\bby\b|\baround\b|\babout\b", " ", s)
    s = re.sub(r"(\d)\s*(a|p)\.?m\.?", r"\1\2m", s)
    return re.sub(r"\s+", " ", s).strip()


# ----------------------------------------------------------------- repeat
def split_repeat(text: str) -> tuple[str, str]:
    """('every monday 9am') -> ('monday 9am', 'weekly')."""
    s = str(text or "").lower()
    repeat = ""
    rules = [
        (r"\bevery\s*(?:weekday|work\s*day)s?\b|\bweekdays\b", "weekdays"),
        (r"\bevery\s*(?:day|morning|evening|night|afternoon)\b|\bdaily\b|\beveryday\b|\beach day\b", "daily"),
        (r"\bevery\s*month\b|\bmonthly\b", "monthly"),
        (r"\bevery\s*(?:week|" + _DAY_NAMES + r")\b|\bweekly\b", "weekly"),
    ]
    for pattern, name in rules:
        if re.search(pattern, s):
            repeat = name
            keep_day = re.search(r"\bevery\s*(" + _DAY_NAMES + r")\b", s)
            s = re.sub(pattern, (keep_day.group(1) if keep_day else " "), s)
            break
    part = re.search(r"\bevery\s*(morning|evening|afternoon|night)\b", str(text or "").lower())
    if part and not re.search(r"\d\s*(am|pm)|\d:\d\d", s):
        s += " " + {"night": "evening"}.get(part.group(1), part.group(1))
    return re.sub(r"\s+", " ", s).strip(), repeat


def next_after(due: datetime, repeat: str, now: datetime) -> datetime:
    """The first repeat of `due` that is later than `now`."""
    step = 0
    while due <= now and step < 4000:
        step += 1
        if repeat == "daily":
            due += timedelta(days=1)
        elif repeat == "weekdays":
            due += timedelta(days=1)
            while due.weekday() >= 5:
                due += timedelta(days=1)
        elif repeat == "weekly":
            due += timedelta(days=7)
        elif repeat == "monthly":
            month = due.month % 12 + 1
            year = due.year + (1 if due.month == 12 else 0)
            day = min(due.day, calendar.monthrange(year, month)[1])
            due = due.replace(year=year, month=month, day=day)
        else:
            break
    return due


# ------------------------------------------------------------------ parse
def _duration(s: str) -> timedelta | None:
    """'in 1 hour 30 minutes', 'in an hour', 'in half an hour', '20 min from now'."""
    if not (re.search(r"\bin\b|\bfrom now\b|\blater\b", s) or re.fullmatch(r"[\d\s.a-z]+", s) and re.match(r"^(a|an|half|\d)", s)):
        return None
    if "half an hour" in s or "half hour" in s:
        return timedelta(minutes=30)
    total, found = 0.0, False
    for number, unit in re.findall(r"(\d+(?:\.\d+)?|\ban?\b)\s*(sec|second|min|minute|hr|hour|day|week)s?\b", s):
        found = True
        total += (1.0 if number.startswith("a") else float(number)) * UNITS[unit]
    return timedelta(minutes=total) if found else None


def _time_of(s: str) -> tuple[tuple[int, int] | None, str, bool]:
    """(hour, minute) or None, the text with the time removed, and whether am/pm was said."""
    m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", s)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if h < 24 and mi < 60:
            return (h, mi), s[:m.start()] + " " + s[m.end():], bool(ap) or h >= 13 or h == 0
    m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", s)
    if m:
        h, ap = int(m.group(1)), m.group(2)
        if 1 <= h <= 12:
            h = (h % 12) + (12 if ap == "pm" else 0)
            return (h, 0), s[:m.start()] + " " + s[m.end():], True
    for word, hm in sorted(PART_OF_DAY.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"\b" + word + r"\b", s):
            return hm, re.sub(r"\b" + word + r"\b", " ", s, count=1), True
    m = re.search(r"(?<![\d/-])\b(\d{1,2})\b(?![\d/:-])", s)          # a bare "3" or "9"
    if m and 1 <= int(m.group(1)) <= 12 and not re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*" + m.group(1), s) \
            and not re.search(m.group(1) + r"(st|nd|rd|th)?\s*(of\s*)?(" + _MONTH_RE + ")", s):
        return (int(m.group(1)), 0), s[:m.start()] + " " + s[m.end():], False
    return None, s, False


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    s = _clean(text)
    if not s:
        return None

    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})(?:[ t]+(\d{1,2}):(\d{2}))?", s)
    day = None
    explicit_time = None
    if iso:
        try:
            day = datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
        if iso.group(4):
            explicit_time = (int(iso.group(4)), int(iso.group(5)))
        s = s[:iso.start()] + " " + s[iso.end():]
    else:
        delta = _duration(s)
        if delta is not None:
            return now + delta

    time_of, rest, ampm_said = (explicit_time, s, True) if explicit_time else _time_of(s)
    s = rest

    if day is None:
        base = now.replace(hour=0, minute=0)
        if re.search(r"\bday after tomorrow\b", s):
            day = base + timedelta(days=2)
        elif re.search(r"\btomorrow\b|\btmrw\b|\btmr\b", s):
            day = base + timedelta(days=1)
        elif re.search(r"\btoday\b|\btonight\b|\bthis (morning|afternoon|evening)\b", s):
            day = base
        else:
            m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s*)?(" + _MONTH_RE + r")[a-z]*\.?(?:\s+(\d{4}))?", s) or None
            n = re.search(r"\b(" + _MONTH_RE + r")[a-z]*\.?\s*(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?\b", s)
            try:
                if m:
                    month, dnum, year = _month_index(m.group(2)), int(m.group(1)), m.group(3)
                elif n:
                    month, dnum, year = _month_index(n.group(1)), int(n.group(2)), n.group(3)
                else:
                    month = dnum = year = None
                if month:
                    y = int(year) if year else now.year
                    day = datetime(y, month, dnum)
                    if not year and day < base - timedelta(days=1):
                        day = datetime(y + 1, month, dnum)
            except ValueError:
                return None
            if day is None:
                w = re.search(_WEEKDAY_RE, s)
                if w:
                    target = _weekday_index(w.group(2))
                    ahead = (target - base.weekday()) % 7
                    later_today = bool(time_of) and (time_of[0], time_of[1]) > (now.hour, now.minute)
                    if ahead == 0 and (w.group(1) == "next" or not later_today):
                        ahead = 7                  # today's weekday: "friday" on a Friday means next week unless later today
                    day = base + timedelta(days=ahead)
                elif re.search(r"\bnext week\b", s):
                    day = base + timedelta(days=7 - base.weekday())
                    time_of = time_of or DEFAULT_TIME
                elif re.search(r"\bend of (?:the )?week\b", s):
                    day = base + timedelta(days=(4 - base.weekday()) % 7)
                    time_of = time_of or PART_OF_DAY["eod"]
                elif re.search(r"\bnext month\b", s):
                    month = base.month % 12 + 1
                    year = base.year + (1 if base.month == 12 else 0)
                    day = datetime(year, month, 1)
                    time_of = time_of or DEFAULT_TIME

    if day is None:
        if time_of is None:
            return None
        h, mi = time_of
        candidates = [h] if (ampm_said or h >= 13 or h == 0) else [h % 12, h % 12 + 12]
        for hour in candidates:
            when = now.replace(hour=hour, minute=mi)
            if when > now:
                return when
        return now.replace(hour=candidates[-1], minute=mi) + timedelta(days=1) if len(candidates) == 1 else \
            now.replace(hour=candidates[0], minute=mi) + timedelta(days=1)

    if time_of is None:
        time_of = DEFAULT_TIME
        if day == now.replace(hour=0, minute=0):
            return None                           # "today" alone: no time to ring at
    h, mi = time_of
    if not ampm_said and h < 12:
        h = h if h >= 7 else h + 12                # a bare "3" on another day means 3 pm; "9" means 9 am
    return day.replace(hour=h, minute=mi)


def nice(dt: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    clock = dt.strftime("%I:%M %p").lstrip("0")
    days = (dt.date() - now.date()).days
    if days == 0:
        return f"today {clock}"
    if days == 1:
        return f"tomorrow {clock}"
    if 1 < days < 7:
        return f"{dt:%A} {clock}"
    return f"{dt:%a} {dt.day} {dt:%b}{'' if dt.year == now.year else ' ' + str(dt.year)}, {clock}"
