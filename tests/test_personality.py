import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, random, time
from datetime import datetime
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
os.environ["GROQ_API_KEY"] = "k"
sys.path.insert(0, SRC)
import config, personality as P, tools, brain as B
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)
rng = random.Random(1)

# part of day
d = lambda h: datetime(2026, 11, 2, h, 30)
check("parts of day", [P.part_of_day(d(h)) for h in (2, 8, 13, 19, 23)] == ["night", "morning", "afternoon", "evening", "evening"])

# name finding
n = lambda *texts: P.find_name([(i, "fact", t) for i, t in enumerate(texts)])
check("user's name is", n("User's name is Delro") == "Delro")
check("name colon", n("Name: delro") == "Delro")
check("call me", n("Call the user Joyce") == "Joyce")
check("newest wins", n("User's name is Old", "User's name is New") == "New")
check("no name", n("Project Orion is due 15 Dec", "Prefers short answers") is None)
check("junk not a name", n("The project name is the budget") is None)

# greeting
now = datetime(2026, 11, 2, 9, 0)
g = P.greeting(now, name="Delro", last_talked=None, files=0, rng=rng)
print(g)
check("first run greeting", "Delro" in g and "Drop a file" in g and "last talked" not in g)
yday = datetime(2026, 11, 1, 18, 0).timestamp()
g = P.greeting(now, "Delro", yday, 3, rng); print(g)
check("yesterday + files", "yesterday" in g and "3 files" in g)
g = P.greeting(now, None, datetime(2026, 11, 2, 8, 50).timestamp(), 1, rng); print(g)
check("minutes ago + singular + no name", "Back already" in g and "1 file." in g and ", None" not in g)
g = P.greeting(now, None, datetime(2026, 10, 28, 8, 0).timestamp(), 2, rng); print(g)
check("this week -> weekday name", "Wednesday" in g)
g = P.greeting(now, None, datetime(2026, 9, 1).timestamp(), 2, rng)
check("long gap", "been a while" in g)
for h in range(24):
    g = P.greeting(datetime(2026, 11, 2, h, 0), "Ann", None, 1, rng)
    assert g and "Ann" in g, g
check("all hours produce a greeting", True)

# small talk
seen = set(); last = None
for _ in range(200):
    r = P.idle_remark(last, rng); check_ok = r != last; last = r; seen.add(r)
    if not check_ok: break
check("idle remark never repeats back-to-back", check_ok and len(seen) > 5)
check("wake / added / thinking lines exist", P.wake_line(rng) in P.WAKE_LINES and P.added_opener(rng) in P.ADDED_OPENERS and P.thinking_line(rng) in P.THINKING_LINES)

# moods
m = P.mood_for
check("worried: sorry", m("Sorry, I couldn't reach my brain: rate limit") == "worried")
check("worried: something went wrong", m("Something went wrong: x") == "worried")
check("worried: couldn't", m("I couldn't open the microphone (Mic: x).") == "worried")
check("worried: didn't catch", m("Sorry, I didn't catch that. Could you say it again?") == "worried")
check("happy: saved", m("Saved your report. It has 3 sections.") == "happy")
check("happy: now playing", m("Now playing Dare by Gorillaz on your PC.") == "happy")
check("happy: opened", m("I opened Excel for you.") == "happy")
check("talking: normal answer", m("Your total sales for 2025 were 1,200.") == "talking")
check("long answer stays talking", m("Saved " + "x" * 400) == "talking")
check("empty", m("") == "talking")
check("failed tasks are worried not happy", m("The report failed to save, sorry.") == "worried")

# brain: name + last_talked
store = tools.FileStore(db_path=f"{home}/s.db")
B.openai = object()
b = B.Brain(store)
check("no name yet", b.user_name() is None and b.last_talked is None)
b.memory.add_note("User's name is Delro", "fact")
check("brain finds name", b.user_name() == "Delro")
B.Brain._ask = lambda self, p, s, t: "Hello!"
b.reply("hi")
check("last_talked after restart", B.Brain(store).last_talked is not None)
check("system prompt has personality + name rule", "blunt" in config.SYSTEM_PROMPT and "User's name is X" in config.SYSTEM_PROMPT)
config.MEMORY = False
check("memory off: no name, no crash", B.Brain(store).user_name() is None)
# prompt didn't break tool prompts
check("old prompt parts intact", "play_music" in config.SYSTEM_PROMPT and "data_aggregate" in config.SYSTEM_PROMPT and "Never claim to have done" in config.SYSTEM_PROMPT)
print("ALL PASSED" if not bad else bad)
