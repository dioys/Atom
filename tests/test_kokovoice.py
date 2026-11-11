import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, time, pathlib, shutil, threading
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import numpy as np, config, robot, speaker, kokovoice
config.SETTINGS_FILE = pathlib.Path(home) / "settings.json"
bad = []
def check(n, c, *_):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, _))
RAW = pathlib.Path("/tmp/babble_demo/flite_raw.wav")
x, rate = robot.read_wav(RAW)
dom = lambda y, r: np.fft.rfftfreq(len(y), 1 / r)[np.abs(np.fft.rfft(y)).argmax()]

# ---- young / time_stretch
r = 24000; t = np.arange(r * 2) / r
tone = 0.5 * np.sin(2 * np.pi * 200 * t) * (1 + 0.3 * np.sin(2 * np.pi * 3 * t))
for st in (2.5, 4.5):
    y = robot.young(tone, st)
    check(f"young {st}: same length", len(y) == len(tone))
    check(f"young {st}: pitch up by {st} semitones", abs(dom(y, r) / 200 - 2 ** (st / 12)) < 0.02, dom(y, r))
    check(f"young {st}: finite and in range", np.isfinite(y).all() and abs(y).max() < 1.2)
check("young 0 = untouched", robot.young(tone, 0) is tone)
check("young on tiny clip safe", len(robot.young(np.zeros(100), 4)) == 100)
y = robot.young(x, 2.5); check("real speech: same length, keeps its loudness rhythm", len(y) == len(x) and np.corrcoef(robot._envelope(x, rate)[::160], robot._envelope(y, rate)[::160])[0, 1] > 0.8)
check("stretch 1.5 is 1.5x longer, same pitch", abs(len(robot.time_stretch(tone, 1.5)) / len(tone) - 1.5) < 0.01 and abs(dom(robot.time_stretch(tone, 1.5), r) - 200) < 3)
check("stretch 1 untouched", robot.time_stretch(tone, 1.0) is tone or np.array_equal(robot.time_stretch(tone, 1.0), tone))
a = robot.effect(x, rate, "android")
check("android: same length, finite, peak .9", len(a) == len(x) and np.isfinite(a).all() and abs(abs(a).max() - 0.9) < 1e-6)
check("android keeps the words (very similar to the original)", np.corrcoef(a, x)[0, 1] > 0.8, np.corrcoef(a, x)[0, 1])
check("android silence safe", np.isfinite(robot.effect(np.zeros(500), rate, "android")).all())
check("ages", robot.AGES["natural"] == 0 and robot.AGES["teen"] < robot.AGES["boy"])

# ---- KokoroVoice with a fake model
calls = []
class Fake:
    def create(self, text, voice, speed, lang):
        calls.append((text, voice, speed, lang)); return (0.3 * np.sin(np.arange(12000) / 9)).astype(np.float32), 24000
loads = []
def factory(): loads.append(1); return Fake()
k = kokovoice.KokoroVoice(factory)
out = pathlib.Path(home) / "k.wav"
text = " ".join(f"This is sentence number {i}." for i in range(14))
check("synth ok", k(text, out, "am_liam", 0, None) and out.exists())
check("model loaded once, even for many pieces", len(loads) == 1 and len(calls) >= 2)
check("voice, speed 1.0, lang us english", all(c[1] == "am_liam" and c[2] == 1.0 and c[3] == "en-us" for c in calls))
check("pieces <= 240", all(len(c[0]) <= 240 for c in calls))
d, rt = robot.read_wav(out); check("one file at 24000", rt == 24000 and len(d) > 12000 * len(calls))
k(text, out, "zzz", 6, None); check("unknown voice -> puck; speed capped", calls[-1][1] == "am_puck" and abs(calls[-1][2] - 1.3) < 1e-9)
k(text, out, "am_puck", -6, None); check("slow = 0.7", abs(calls[-1][2] - 0.7) < 1e-9)
n = len(calls); k.model = None
st = threading.Event(); st.set(); check("stop first -> no work", k(text, out, "am_puck", 0, st) is False and len(calls) == n)
check("nothing to say", k("...", out, "am_puck", 0, None) is False and k.last_error == "nothing to say")
def broken(): raise RuntimeError("onnx   exploded\nbadly")
kb = kokovoice.KokoroVoice(broken); check("model error -> False, one-line reason", kb("Hi.", out, "am_puck", 0, None) is False and "\n" not in kb.last_error and "exploded" in kb.last_error, kb.last_error)
# the real thing, not installed here
kr = kokovoice.KokoroVoice(); ok = kr("Hi there.", out, "am_puck", 0, None)
check("not installed -> False with the fix in words", ok is False and "pip install kokoro-onnx" in kr.last_error, kr.last_error)
check("ready() false here, problem() explains", not kokovoice.ready() and "pip install" in kokovoice.problem())
# files-ready logic
w = pathlib.Path(home) / "kk"; w.mkdir()
check("files_ready false", not kokovoice.files_ready(w))
(w / kokovoice.MODEL_FILE).write_bytes(b"x"); check("one file isn't enough", not kokovoice.files_ready(w))
(w / kokovoice.VOICES_FILE).write_bytes(b"x"); check("both files -> ready", kokovoice.files_ready(w))
kokovoice.BASE_URL = "https://localhost.invalid/"
shutil.rmtree(w); w.mkdir()
msgs = []; check("download without internet fails cleanly", kokovoice.download(w, say=msgs.append) is False and any("couldn't download" in m for m in msgs), msgs)
check("no .part files left", not list(w.glob("*.part")))
big = pathlib.Path(home) / "big"; big.mkdir()
for n in (kokovoice.MODEL_FILE, kokovoice.VOICES_FILE): (big / n).write_bytes(b"x" * 2_000_000)
m2 = []; check("big files already there are skipped", kokovoice.download(big, say=m2.append) is True and all("already here" in m for m in m2), m2)

# ---- Robot pipeline with young + android + glitch
class Player:
    available = True
    def __init__(s): s.played = []
    def play(s, p): s.played.append(pathlib.Path(p))
    def stop(s): pass
def fake_kokoro(text, out, voice, rate_, stop=None): shutil.copy(RAW, out); return True
pl = Player(); rb = robot.Robot(pl, fake_kokoro, pathlib.Path(home) / "snd")
rb.configure("android", "am_puck", 0, 0, 0.9, glitch=1.2, young=2.5)
check("configure keeps young", rb.young == 2.5 and rb.style == "android")
rb.say("Hello"); time.sleep(1.5)
o, ort = robot.read_wav(pl.played[0]); check("played: same length as the raw voice, in range", len(o) == len(x) and abs(o).max() <= 0.9 + 1e-3, (len(o), len(x)))
rb.configure("android", young=99); check("young capped at 8", rb.young == 8.0)

# ---- Speaker
config.SETTINGS_FILE.write_text("{}")
sp = speaker.Speaker()
check("default is boy mode, puck, teen, no glitches", sp.mode == "boy" and sp.boy.voice == "am_puck" and sp.boy.young == 2.5 and sp.boy.glitch == 0 and sp.boy.style == "android")
sp.apply_settings(mode="boy", boy_voice="am_liam", age="boy")
check("apply boy options", sp.boy.voice == "am_liam" and sp.boy.young == 4.5 and sp.boy.glitch == 0)
sp.apply_settings(mode="boy", age="natural"); check("natural", sp.boy.young == 0)
sp.apply_settings(mode="boy", age="???"); check("bad age -> teen", sp.boy.young == 2.5)
sp.apply_settings(name="Microsoft David - English (United States)", mode="boy"); check("fallback voice base name", sp.boy.fallback_voice == "Microsoft David")
check("fallback is the Windows synth", sp.boy.fallback is robot.windows_say_to_file)
said = []; sp.boy.say = lambda t: said.append(t) or True
sp.say("Hi **there**"); check("say routes to boy", said == ["Hi there"])
stopped = []; sp.boy.stop = lambda: stopped.append(1); sp.stop(); check("stop stops boy", stopped)
config.SETTINGS_FILE.write_text('{"voice_mode":"boy","boy_voice":"am_eric","boy_age":"boy"}')
s2 = speaker.Speaker(); check("saved settings used", s2.boy.voice == "am_eric" and s2.boy.young == 4.5 and s2.boy.glitch == 0)
config.SETTINGS_FILE.write_text('{"voice_mode":"robot"}'); s3 = speaker.Speaker(); check("old robot choice respected", s3.mode == "robot")
check("speed default normal", config.SPEECH_RATE == 0.0)
print("\nFAILED:" if bad else "\nALL PASSED", bad if bad else "")
sys.exit(1 if bad else 0)
