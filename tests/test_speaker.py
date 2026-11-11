import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, speaker
config.VOICE_MODE = "windows"
from speaker import speakable
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)
check("plain text unchanged", speakable("Now playing Dare by Gorillaz on your PC.") == "Now playing Dare by Gorillaz on your PC.")
check("markdown removed", speakable("**Total:** 1,200 for `2025`") == "Total: 1,200 for 2025")
check("emoji removed", speakable("Done! 🎉 Saved your report 📄") == "Done! Saved your report")
check("url", speakable("See https://example.com/page?x=1 for more") == "See a link for more")
check("windows path -> file name", speakable(r"Saved C:\Users\delro\.atom\reports\2026-11-01-status.docx now") == "Saved 2026-11-01-status.docx now")
check("fractions and money kept", speakable("Costs $1,200.50 (12%)") == "Costs $1,200.50 (12%)")
check("peso sign kept", "₱" in speakable("Total ₱5,000"))
long = "First sentence here. " * 30
out = speakable(long, 100)
check("long text cut at a sentence", len(out) <= 100 and out.endswith(".") and out.count("First") == 4)
check("no sentence break: cut at a word", speakable("word " * 200, 50).endswith("word.") )
check("empty", speakable("") == "" and speakable("🎉🎉") == "")
check("default limit from config", len(speakable("a " * 600)) <= config.SPEAK_MAX_CHARS + 1)
sp = speaker.Speaker()
check("no Qt speech here -> unavailable but safe", sp.available is False and sp.say("hi") is False and sp.stop() is None)

# fake engine
class FakeTTS:
    def __init__(self): self.said = []; self.stops = 0
    def stop(self): self.stops += 1
    def say(self, t): self.said.append(t)
sp._tts = FakeTTS()
check("say speaks cleaned text", sp.say("**Hi** 🎉 there") and sp._tts.said == ["Hi there"] and sp._tts.stops == 1)
check("nothing to say", sp.say("🎉") is False)
class Broken(FakeTTS):
    def say(self, t): raise RuntimeError("driver")
sp._tts = Broken()
check("driver error doesn't crash", sp.say("hello") is False)
print("ALL PASSED" if not bad else bad)
