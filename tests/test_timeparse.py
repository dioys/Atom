import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import sys; sys.path.insert(0, SRC)
from datetime import datetime
import timeparse as T
now = datetime(2026, 11, 4, 14, 30)      # Wednesday 2:30 PM
bad = []
def chk(text, want):
    got = T.parse_when(text, now)
    ok = got == (datetime(*want) if want else None)
    print(("PASS " if ok else "FAIL ") + f"{text!r} -> {got}")
    if not ok: bad.append((text, got, want))
chk("in 10 minutes", (2026,11,4,14,40))
chk("in an hour", (2026,11,4,15,30))
chk("in 1 hour 30 minutes", (2026,11,4,16,0))
chk("in half an hour", (2026,11,4,15,0))
chk("20 minutes from now", (2026,11,4,14,50))
chk("in 2 days", (2026,11,6,14,30))
chk("tomorrow 9am", (2026,11,5,9,0))
chk("tomorrow at 3:30 pm", (2026,11,5,15,30))
chk("tomorrow", (2026,11,5,9,0))
chk("tomorrow morning", (2026,11,5,9,0))
chk("today at 5pm", (2026,11,4,17,0))
chk("at 5pm", (2026,11,4,17,0))
chk("at 9am", (2026,11,5,9,0))              # already past today -> tomorrow
chk("3pm", (2026,11,4,15,0))
chk("at 3", (2026,11,4,15,0))               # bare 3: next 3 o'clock = 3 pm today
chk("at 9", (2026,11,4,21,0))               # the next 9 o'clock is tonight
chk("tonight", (2026,11,4,20,0))
chk("this evening", (2026,11,4,18,0))
chk("noon", (2026,11,5,12,0))
chk("friday", (2026,11,6,9,0))
chk("friday 10am", (2026,11,6,10,0))
chk("next monday", (2026,11,9,9,0))
chk("next month", (2026,12,1,9,0))
chk("wednesday", (2026,11,11,9,0))          # today is Wednesday and no later time -> next week
chk("wednesday 6pm", (2026,11,4,18,0))
chk("next week", (2026,11,9,9,0))
chk("end of the week", (2026,11,6,17,0))
chk("end of day", (2026,11,4,17,0))
chk("nov 10 2pm", (2026,11,10,14,0))
chk("10 nov at 2:30pm", (2026,11,10,14,30))
chk("november 10th", (2026,11,10,9,0))
chk("jan 5", (2027,1,5,9,0))                # already passed this year -> next year
chk("2026-12-25", (2026,12,25,9,0))
chk("2026-12-25 18:45", (2026,12,25,18,45))
chk("2026-12-25T07:00", (2026,12,25,7,0))
chk("day after tomorrow 8am", (2026,11,6,8,0))
chk("15:45", (2026,11,4,15,45))
chk("midnight", (2026,11,5,0,0))
chk("gibberish words", None)
chk("", None)
chk("today", None)
chk("2026-13-45", None)
# repeats
for text, want in [("every day at 9am", ("9am", "daily")), ("every monday 9am", ("monday 9am", "weekly")), ("weekdays 8am", ("8am", "weekdays")),
                   ("every morning", ("morning", "daily")), ("tomorrow 3pm", ("tomorrow 3pm", "")), ("every month on the 1st", (None, "monthly"))]:
    got = T.split_repeat(text)
    ok = got[1] == want[1] and (want[0] is None or got[0].replace("  ", " ").strip() == want[0] or want[0] in got[0])
    print(("PASS " if ok else "FAIL ") + f"split {text!r} -> {got}")
    if not ok: bad.append(("split", text, got))
d = datetime(2026,11,4,9,0)
assert T.next_after(d, "daily", now) == datetime(2026,11,5,9,0)
assert T.next_after(datetime(2026,11,6,9,0), "weekdays", datetime(2026,11,6,10,0)) == datetime(2026,11,9,9,0)
assert T.next_after(datetime(2026,10,31,9,0), "monthly", datetime(2026,11,1,0,0)) == datetime(2026,11,30,9,0)
assert T.next_after(datetime(2026,11,10,9,0), "weekly", now) == datetime(2026,11,10,9,0)
assert T.next_after(datetime(2026,12,31,9,0), "monthly", datetime(2027,1,1,0,0)) == datetime(2027,1,31,9,0)
assert T.nice(datetime(2026,11,4,15,0), now) == "today 3:00 PM" and T.nice(datetime(2026,11,5,9,0), now) == "tomorrow 9:00 AM"
assert T.nice(datetime(2026,11,6,9,0), now) == "Friday 9:00 AM" and T.nice(datetime(2026,11,20,9,0), now) == "Fri 20 Nov, 9:00 AM"
print("FAILED:" if bad else "ALL PASSED", bad)
