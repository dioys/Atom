import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, time, wave, pathlib
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, babble, speaker
config.SETTINGS_FILE = pathlib.Path(home) / "settings.json"
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)

# syllables and plan
check("syllables", [babble.syllables(w) for w in ["the", "make", "Atom", "spotify", "table", "2024"]] == [1, 1, 2, 3, 2, 2])
sample = "Hello! I'm Atom. Do you want me to open your files?"
p = babble.plan(sample)
check("one blip per syllable", len(p) == sum(babble.syllables(w) for w in ["Hello", "I'm", "Atom", "Do", "you", "want", "me", "to", "open", "your", "files"]))
check("notes in range", all(0 <= n < babble.NOTES and w > 0 for w, n in p))
check("question rises, exclamation jumps", p[-1][1] >= 3 or p[-1][1] == babble.NOTES - 1)
check("deterministic", babble.plan(sample) == p)
check("empty text", babble.plan("") == [] and babble.duration_ms("") == 0 and babble.plan("🎉 ...") == [])
fast, slow = babble.duration_ms(sample, 1), babble.duration_ms(sample, -1)
check("rate changes length", fast < babble.duration_ms(sample, 0) < slow)
check("pauses at sentences", max(w for w, _ in p) > 2 * min(w for w, _ in p))
check("long answer is bounded by speakable", babble.duration_ms(speaker.speakable("word " * 400)) < 30000)

# wav files
folder = pathlib.Path(home) / "snd"
for style in babble.STYLES:
    files = babble.ensure_sounds(style, 0.0, 0.8, folder)
    check(f"{style}: 8 wavs", len(files) == 8 and all(f.exists() for f in files))
    with wave.open(str(files[0])) as w:
        n, fr = w.getnframes(), w.getframerate()
        data = w.readframes(n)
    import struct
    vals = struct.unpack("<%dh" % n, data)
    check(f"{style}: short and audible, not clipped", 0.05 < n / fr < 0.15 and 3000 < max(abs(v) for v in vals) < 32767)
    check(f"{style}: starts and ends near silence", abs(vals[0]) < 800 and abs(vals[-1]) < 3000)
hi = babble.ensure_sounds("soft", 1.0, 0.8, folder); lo = babble.ensure_sounds("soft", -1.0, 0.8, folder)
check("pitch makes different files", hi[0] != lo[0] and hi[0].read_bytes() != lo[0].read_bytes())
check("unknown style -> soft", babble.ensure_sounds("nope", 0, 0.8, folder)[0].name.startswith("soft"))

# the babbler with a fake player
class Fake:
    available = True
    def __init__(self): self.played = []; self.stops = 0
    def play(self, path): self.played.append((time.monotonic(), path.name))
    def stop(self): self.stops += 1
fp = Fake(); b = babble.Babbler(fp, folder); b.configure("retro", 0.2, 1.0)
t0 = time.monotonic(); check("say starts", b.say("Hi there, friend!"))
time.sleep(babble.duration_ms("Hi there, friend!", 1.0) / 1000 + 0.3)
check("played every blip", len(fp.played) == len(babble.plan("Hi there, friend!", 1.0)) and all(n.startswith("retro_2_") for _, n in fp.played))
b.say("This is a very long sentence that should stop early when asked nicely by the user")
time.sleep(0.3); b.stop(); n = len(fp.played); time.sleep(0.5)
check("stop cuts it off", len(fp.played) == n and fp.stops >= 1)
class NoSound(Fake): available = False
nb = babble.Babbler(NoSound(), folder); nb.configure()
check("no sound system -> unavailable, safe", nb.available is False and nb.say("hello") is False)
class Boom(Fake):
    def play(self, path): raise RuntimeError("driver")
bb = babble.Babbler(Boom(), folder); bb.configure(); bb.say("hello there"); time.sleep(0.4)
check("driver error doesn't crash", True)

# the Speaker in babble mode
config.save_settings({"voice_mode": "babble", "babble_style": "bubbly", "speech_pitch": 0.3, "speech_rate": 0.5})
sp = speaker.Speaker()
sp.babbler = babble.Babbler(Fake(), folder); sp.apply_settings()
check("babble mode, available", sp.mode == "babble" and sp.available and sp.babbler.style == "bubbly" and not sp.has_windows_voice)
check("estimate_ms follows the babble", speaker._BABBLE_RATE == 0.5 and speaker.estimate_ms(sample, True) == int(min(max(babble.duration_ms(speaker.speakable(sample), 0.5) + 300, 1200), 30000)))
check("typed answers keep the old timing", speaker.estimate_ms("a" * 100, False) == 2000)
check("say plays", sp.say("**Hello** there 🎉") and sp.babbler._thread is not None)
check("nothing to say", sp.say("🎉") is False)
sp.stop()
# switching to a Windows voice
class FakeTTS:
    def __init__(self): self.said = []
    def stop(self): pass
    def say(self, t): self.said.append(t)
    def setRate(self, v): pass
    def setPitch(self, v): pass
sp._tts = FakeTTS()
sp.apply_settings(mode="windows")
check("windows mode", sp.mode == "windows" and speaker._BABBLE_RATE is None and sp.available and sp.say("Hi there"))
check("windows speech used", sp._tts.said == ["Hi there"] and speaker.estimate_ms("a" * 100, True) == 7200)
sp.apply_settings(mode="babble", style="deep")
check("back to babble from settings args", sp.mode == "babble" and sp.babbler.style == "deep")
print("ALL PASSED" if not bad else bad)
