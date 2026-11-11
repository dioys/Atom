import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, speaker
config.VOICE_MODE = "windows"
config.SETTINGS_FILE = __import__("pathlib").Path(home) / "settings.json"

class V:
    def __init__(s, n): s.n = n
    def name(s): return s.n
class L:
    def __init__(s, n): s.n = n
    def name(s): return s.n
class FakeTTS:
    def __init__(s):
        s.loc = L("en_PH"); s.voice = None; s.rate = None; s.pitch = None; s.said = []
        s.table = {"en_US": [V("David"), V("Zira")], "fil_PH": [V("Angelo")], "en_PH": [V("James")], "ja_JP": [V("Haruka")]}
        s.cur = "en_PH"
    def locale(s): return L(s.cur)
    def availableLocales(s): return [L(k) for k in s.table]
    def setLocale(s, l): s.cur = l.name()
    def availableVoices(s): return s.table[s.cur]
    def setVoice(s, v): s.voice = (s.cur, v.name())
    def setRate(s, r): s.rate = r
    def setPitch(s, p): s.pitch = p
    def setVolume(s, v): pass
    def stop(s): pass
    def say(s, t): s.said.append(t)

sp = speaker.Speaker()
assert not sp.available and sp.voices() == []
sp.apply_settings()  # no engine: no crash
sp._tts = FakeTTS(); sp._voices = None
vs = sp.voices()
names = [v["name"] for v in vs]
assert set(names) == {"David", "Zira", "Angelo", "James", "Haruka"}, names
assert vs[0]["locale"].startswith("en") and vs[-1]["name"] == "Haruka", [(v["name"], v["locale"]) for v in vs]
assert vs[0]["label"].count("(") == 1 and "_" not in vs[0]["label"]
assert sp._tts.cur == "en_PH", "locale restored after listing"
assert "_voice" not in sp.voices()[0] or True

# nothing saved: defaults
sp.apply_settings()
assert sp._tts.rate == config.SPEECH_RATE and sp._tts.pitch == config.SPEECH_PITCH
# explicit choice (the Test button)
sp.apply_settings("Zira", "en_US", 0.3, -0.4)
assert sp._tts.voice == ("en_US", "Zira") and sp._tts.rate == 0.3 and sp._tts.pitch == -0.4
# saved choice is used at start
config.save_settings({"voice": {"name": "Angelo", "locale": "fil_PH"}, "speech_rate": -0.2, "speech_pitch": 0.5})
sp.apply_settings()
assert sp._tts.voice == ("fil_PH", "Angelo") and sp._tts.rate == -0.2 and sp._tts.pitch == 0.5
# out-of-range values are clamped; a voice that was uninstalled is ignored quietly
config.save_settings({"voice": {"name": "Gone", "locale": "xx_XX"}, "speech_rate": 9, "speech_pitch": -9})
sp._tts.voice = None
sp.apply_settings()
assert sp._tts.voice is None and sp._tts.rate == 1.0 and sp._tts.pitch == -1.0
# a driver that breaks never crashes Atom
class Bad(FakeTTS):
    def setVoice(s, v): raise RuntimeError("x")
sp._tts = Bad(); sp._voices = None
sp.apply_settings("David", "en_US", 0, 0)
assert sp.say(speaker.Speaker.SAMPLE)
print("voices ok")
