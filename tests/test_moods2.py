import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import sys; sys.path.insert(0,SRC)
import personality as P
m=P.mood_for
cases={
 "Haha, that's a funny one!":"laughing",
 "Wow, that is a big number.":"surprised",
 "Good news: your sales are up 12%.":"proud",
 "Unfortunately your file has no totals.":"sad",
 "Which file do you mean?":"curious",
 "Sorry, I didn't catch that.":"worried",
 "Saved your report.":"happy",
 "Your total is 1,200.":"talking",
 "":"talking",
 "I couldn't open the microphone.":"worried",
}
for t,e in cases.items():
    assert m(t)==e,(t,m(t),e)
print("moods ok")
