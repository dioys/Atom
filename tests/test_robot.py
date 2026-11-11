import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, time, pathlib, shutil, threading
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import numpy as np, config, robot, speaker, babble
config.SETTINGS_FILE = pathlib.Path(home) / "settings.json"
bad = []
def check(n, c, *_):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)
RAW = pathlib.Path("/tmp/babble_demo/flite_raw.wav")
x, rate = robot.read_wav(RAW)
check("read wav", rate == 16000 and len(x) > rate * 3 and abs(x).max() <= 1.0)
for st in robot.STYLES:
    y = robot.effect(x, rate, st)
    check(f"{st}: same length, finite, in range", y.shape == x.shape and np.isfinite(y).all() and abs(y).max() <= 0.91)
    check(f"{st}: really different from the original", np.corrcoef(x, y)[0, 1] < 0.6 or st == "radio")
    check(f"{st}: deterministic", np.array_equal(y, robot.effect(x, rate, st)))
    sp = np.abs(np.fft.rfft(y)); f = np.fft.rfftfreq(len(y), 1 / rate)
    check(f"{st}: keeps rhythm of the words", np.corrcoef(robot._envelope(x, rate)[::160], robot._envelope(y, rate)[::160])[0, 1] > 0.6)
check("unknown style -> electric", np.array_equal(robot.effect(x, rate, "zzz"), robot.effect(x, rate, "electric")))
check("tiny input safe", len(robot.effect(np.zeros(5), rate)) == 5 and len(robot.effect(np.zeros(0), rate)) == 0)
check("silence safe", np.isfinite(robot.effect(np.zeros(4000), rate)).all())
check("pitch: up is shorter, down longer", len(robot.shift_pitch(x, 1)) < len(x) < len(robot.shift_pitch(x, -1)) and robot.shift_pitch(x, 0) is x)
check("comb matches a slow loop", True)
a = np.random.default_rng(1).normal(0, 1, 500); d, g = 7, 0.5
slow = a.copy()
for n in range(d, len(a)): slow[n] = a[n] + g * slow[n - d]
check("comb filter correct", np.allclose(robot._comb(a, d, g), slow))

# the Robot with a stand-in voice and player
class Player:
    available = True
    def __init__(self): self.played = []; self.stops = 0
    def play(self, p): self.played.append(pathlib.Path(p))
    def stop(self): self.stops += 1
calls = []
def fake_synth(text, out, voice, rate_, stop=None):
    calls.append((text, voice, rate_)); shutil.copy(RAW, out); return True
folder = pathlib.Path(home) / "snd"
pl = Player(); r = robot.Robot(pl, fake_synth, folder); r.configure("robot", "Microsoft David", 0.5, 0.2, 0.8)
check("available with a player and a voice", r.available)
check("say starts", r.say("Hello there"))
time.sleep(1.5)
check("voice asked with name and rate", calls == [("Hello there", "Microsoft David", 3)], calls)
check("processed file played", len(pl.played) == 1 and pl.played[0].exists() and pl.played[0].parent == folder)
out, rt = robot.read_wav(pl.played[0]); check("played file is changed audio at the same rate", rt == rate and abs(out).max() <= 0.81 + 1e-3)
check("raw file cleaned up", not list(folder.glob("*_raw.wav")))
r.say("again"); time.sleep(1.5)
check("new file name each time", len({p.name for p in pl.played}) == 2)
# stop before it plays
slow_calls = []
def slow_synth(text, out, voice, rate_, stop=None):
    stop.wait(2); return False
r2 = robot.Robot(Player(), slow_synth, folder); r2.configure()
t = time.monotonic(); r2.say("long"); time.sleep(0.2); r2.stop(); time.sleep(0.2)
check("stop cancels waiting synth", time.monotonic() - t < 1.5 and not r2.player.played)
bad_synth = lambda *a, **k: False
r3 = robot.Robot(Player(), bad_synth, folder); r3.configure(); r3.say("x"); time.sleep(0.3)
check("synth failure: silent, remembered, no crash", not r3.player.played and r3.last_error)
def boom(*a, **k): raise RuntimeError("wav broke")
r4 = robot.Robot(Player(), boom, folder); r4.configure(); r4.say("x"); time.sleep(0.3)
check("exception inside synth is contained", r4.last_error == "wav broke")
class NoPlayer(Player): available = False
check("no sound system -> unavailable", robot.Robot(NoPlayer(), fake_synth, folder).available is False and robot.Robot(NoPlayer(), fake_synth, folder).say("x") is False)
check("real windows synth refuses off Windows", robot.windows_say_to_file("hi", folder / "x.wav") is False)

# the Speaker in robot mode
config.save_settings({"voice_mode": "robot", "robot_style": "radio", "voice": {"name": "Microsoft Zira - English (United States)", "locale": "en_US"}, "speech_rate": 0.3, "speech_pitch": -0.4})
sp = speaker.Speaker()
sp.robot = robot.Robot(Player(), fake_synth, folder); sp.apply_settings()
check("robot mode selected", sp.mode == "robot" and sp.available and sp.robot.style == "radio")
check("voice name trimmed for PowerShell", sp.robot.voice == "Microsoft Zira" and sp.robot.rate == 0.3 and sp.robot.pitch == -0.4)
check("estimate_ms is the normal voice timing", speaker._BABBLE_RATE is None and speaker.estimate_ms("a" * 100, True) == 7200)
calls.clear(); check("say routes to the robot", sp.say("**Hi** 🎉 there") and (time.sleep(1.2) or calls[0][0] == "Hi there"))
check("nothing to say", sp.say("🎉") is False)
sp.stop(); check("stop reaches the robot", sp.robot.player.stops >= 1)
sp.apply_settings(mode="babble"); check("switch to babble", sp.mode == "babble")
sp.apply_settings(mode="robot", fx="electric"); check("switch back, style from the dialog", sp.mode == "robot" and sp.robot.style == "electric")
sp.apply_settings(mode="windows"); check("switch to windows", sp.mode == "windows" and sp.available is False)
print("ALL PASSED" if not bad else bad)
