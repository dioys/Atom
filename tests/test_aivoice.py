import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, time, pathlib, shutil, threading, io, wave
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import numpy as np, config, robot, speaker, aivoice
config.SETTINGS_FILE = pathlib.Path(home) / "settings.json"
bad = []
def check(n, c, *_):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, _))
RAW = pathlib.Path("/tmp/babble_demo/flite_raw.wav")
x, rate = robot.read_wav(RAW)

# ---- glitch
check("amount 0 = untouched", np.array_equal(robot.glitch(x, rate, 0), x))
check("short clip untouched", np.array_equal(robot.glitch(x[:rate // 2], rate, 5), x[:rate // 2]))
changed = 0
for seed in range(30):
    y = robot.glitch(x, rate, 1.2, seed=seed)
    assert y.shape == x.shape and np.isfinite(y).all() and abs(y).max() <= 1.0
    changed += not np.array_equal(y, x)
check("length kept, finite, in range (30 seeds)", True)
check("sometimes glitches, sometimes not (30 seeds)", 10 <= changed <= 30, changed)
rare = sum(not np.array_equal(robot.glitch(x, rate, 0.6, seed=s), x) for s in range(60))
often = sum(not np.array_equal(robot.glitch(x, rate, 2.5, seed=s), x) for s in range(60))
check("rarely < often", rare < often, (rare, often))
y = robot.glitch(x, rate, 5, seed=3)
diff = np.abs(y - x) > 1e-9
share = diff.mean()
check("most of the speech is left alone", share < 0.35, share)
check("same seed same glitch", np.array_equal(robot.glitch(x, rate, 2, seed=5), robot.glitch(x, rate, 2, seed=5)))
check("silence safe", np.array_equal(robot.glitch(np.zeros(rate * 3), rate, 5), np.zeros(rate * 3)))
check("clean style = just louder/normalised", np.corrcoef(robot.effect(x, rate, "clean"), x)[0, 1] > 0.999)
check("clean peak 0.9", abs(abs(robot.effect(x, rate, "clean")).max() - 0.9) < 1e-6)
check("clean on silence safe", np.isfinite(robot.effect(np.zeros(100), rate, "clean")).all())

# ---- chunks
check("empty -> none", aivoice.chunks("") == [] and aivoice.chunks("   ") == [] and aivoice.chunks("...") == [])
check("short stays one", aivoice.chunks("Hi there. How are you?") == ["Hi there. How are you?"])
long = " ".join(f"This is sentence number {i}." for i in range(30))
cs = aivoice.chunks(long)
check("all pieces <= 190", all(len(c) <= 190 for c in cs) and len(cs) > 3)
check("no words lost", " ".join(cs).split() == long.split())
w = "word " * 100
cs = aivoice.chunks(w)
check("one huge sentence cut at spaces", all(len(c) <= 190 for c in cs) and " ".join(cs).split() == w.split())
cs = aivoice.chunks("a" * 500)
check("no spaces: hard cut still <=190", all(len(c) <= 190 for c in cs) and "".join(cs) == "a" * 500)

# ---- join + synth with a fake client
def wav_bytes(samples, r=24000):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(r)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return b.getvalue()
tone = lambda n: 0.3 * np.sin(np.arange(n) / 10)
j, r = aivoice.join_wavs([wav_bytes(tone(2400)), wav_bytes(tone(2400))])
check("join adds a small gap", r == 24000 and len(j) == 2400 * 2 + int(24000 * 0.12))
try:
    aivoice.join_wavs([wav_bytes(tone(100), 24000), wav_bytes(tone(100), 16000)]); ok = False
except ValueError: ok = True
check("different rates refused", ok)

class Resp:
    def __init__(s, c): s.content = c
class Speech:
    def __init__(s, log, fail=None): s.log, s.fail = log, fail
    def create(s, **kw):
        s.log.append(kw)
        if s.fail: raise s.fail
        return Resp(wav_bytes(tone(4800)))
class Client:
    def __init__(s, log, fail=None): s.audio = type("A", (), {"speech": Speech(log, fail)})()
log = []
g = aivoice.GroqVoice(lambda: Client(log))
out = pathlib.Path(home) / "o.wav"
text = " ".join(f"This is sentence number {i}." for i in range(12))
check("synth ok", g(text, out, "austin", 0, None) and out.exists())
check("every request is <=200 chars, right model & voice, wav",
      all(len(k["input"]) <= 200 and k["model"] == aivoice.MODEL and k["voice"] == "austin" and k["response_format"] == "wav" for k in log) and len(log) >= 2, log[:1])
d, rt = robot.read_wav(out); check("one joined file", rt == 24000 and len(d) > 4800 * len(log))
log.clear(); g(text, out, "nobody", 0, None)
check("unknown voice -> troy", log[0]["voice"] == "troy")
st = threading.Event(); st.set(); log.clear()
check("stop before start -> no request", g(text, out, "troy", 0, st) is False and not log)
for err, word in [(Exception("Error code: 400 - model_terms_required"), "accept"), (Exception("Error code: 429 rate_limit_exceeded"), "limit"),
                  (Exception("Connection error."), "internet"), (Exception("Error code: 401 invalid api key"), "key")]:
    gg = aivoice.GroqVoice(lambda e=err: Client([], e))
    ok = gg("Hello there friend.", out, "troy", 0, None)
    check(f"failure -> False, friendly: {word}", ok is False and word in gg.last_error.lower(), gg.last_error)
def nokey(): raise RuntimeError("there is no Groq key yet (add it in Settings)")
gg = aivoice.GroqVoice(nokey); check("no key -> False with reason", gg("Hi.", out, "troy", 0, None) is False and "key" in gg.last_error)
check("nothing to say", aivoice.GroqVoice(lambda: Client([])) ("...", out, "troy", 0, None) is False)

# ---- Robot with AI synth + fallback
class Player:
    available = True
    def __init__(s): s.played = []
    def play(s, p): s.played.append(pathlib.Path(p))
    def stop(s): pass
folder = pathlib.Path(home) / "snd"
pl = Player()
fb_calls = []
def fallback(text, out, voice, rate_, stop=None):
    fb_calls.append((text, voice, rate_)); shutil.copy(RAW, out); return True
good = aivoice.GroqVoice(lambda: Client([]))
r = robot.Robot(pl, good, folder, fallback); r.configure("clean", "troy", 0.0, 0.0, 0.9, glitch=1.2, fallback_voice="Microsoft David")
check("available", r.available)
r.say("Hello there. I opened Spotify."); time.sleep(0.8)
check("AI voice played, no fallback", len(pl.played) == 1 and not fb_calls and not r.notice)
check("latency measured", r.latency_ms >= 0)
pl2 = Player(); broken = aivoice.GroqVoice(lambda: Client([], Exception("Connection error.")))
r = robot.Robot(pl2, broken, folder, fallback); r.configure("clean", "troy", 0.0, 0.0, 0.9, glitch=1.2, fallback_voice="Microsoft David")
r.say("Hello there."); time.sleep(0.8)
check("offline: fallback voice used and played", len(pl2.played) == 1 and fb_calls == [("Hello there.", "Microsoft David", 0)], fb_calls)
check("notice says why", "internet" in r.notice, r.notice)
o, _ = robot.read_wav(pl2.played[0]); check("fallback audio is within range", abs(o).max() <= 0.9 + 1e-3)
pl3 = Player(); r = robot.Robot(pl3, broken, folder, lambda *a, **k: False); r.configure("clean"); r.say("x"); time.sleep(0.5)
check("both fail: silent, error remembered", not pl3.played and "internet" in r.last_error, r.last_error)

# ---- Speaker routing & settings
config.SETTINGS_FILE.write_text("{}")
sp = speaker.Speaker()
check("default mode is boy", config.VOICE_MODE == "boy" and sp.mode == "boy", sp.mode)
check("speed default normal", config.SPEECH_RATE == 0.0)
check("ai robot is clean style, troy, no glitches", sp.ai.style == "clean" and sp.ai.voice == "troy" and sp.ai.glitch == 0)
sp.apply_settings(mode="ai", ai_voice="daniel"); check("apply ai options", sp.ai.voice == "daniel")
sp.apply_settings(name="Microsoft David - English (United States)", mode="ai")
check("fallback voice = base name", sp.ai.fallback_voice == "Microsoft David", sp.ai.fallback_voice)
spoke = []
sp.ai.say = lambda t: spoke.append(("ai", t)) or True
sp.robot.say = lambda t: spoke.append(("robot", t)) or True
sp.apply_settings(mode="ai"); sp.say("Hello **there** https://x.com"); sp.apply_settings(mode="robot"); sp.say("Hi")
check("say routes by mode", spoke == [("ai", "Hello there a link"), ("robot", "Hi")], spoke)
stopped = []
sp.ai.stop = lambda: stopped.append("ai"); sp.stop(); check("stop stops the ai voice too", "ai" in stopped)
config.SETTINGS_FILE.write_text('{"voice_mode":"ai","ai_voice":"austin"}')
sp2 = speaker.Speaker(); check("saved settings used", sp2.ai.voice == "austin" and sp2.ai.glitch == 0)
check("estimate_ms not babble in ai mode", speaker._BABBLE_RATE is None)
print("\nFAILED:" if bad else "\nALL PASSED", bad if bad else "")
sys.exit(1 if bad else 0)
