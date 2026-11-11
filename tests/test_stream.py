import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, time, pathlib, threading
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import numpy as np, config, robot, speaker
config.SETTINGS_FILE = pathlib.Path(home) / "settings.json"
bad = []
def check(n, c, *i):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, i))

# ---------------- splitter
S = speaker.StreamSplitter
sp = S(limit=350)
check("nothing until a sentence is finished", sp.feed("Hello there, I am Atom and") == [])
check("first sentence out when it ends (needs the space after)", sp.feed("Hello there, I am Atom and I opened it.") == [] )
out = sp.feed("Hello there, I am Atom and I opened it. Next")
check("first sentence given out", out == ["Hello there, I am Atom and I opened it."], out)
check("not given twice", sp.feed("Hello there, I am Atom and I opened it. Next one is clearly longer than sixty characters, so it can go out alone. And more") == ["Next one is clearly longer than sixty characters, so it can go out alone."])
check("final flushes the rest", sp.feed("Hello there, I am Atom and I opened it. Next one is clearly longer than sixty characters, so it can go out alone. And more words", final=True) == ["And more words"])
check("short sentences are joined", S().feed("Ok. Sure. Fine. Now this is a longer one to say out loud. Then", False) == ["Ok. Sure. Fine. Now this is a longer one to say out loud."])
check("markdown/links cleaned", S().feed("See **this** at https://example.com/a/b right now, friend. More", False) == ["See this at a link right now, friend."])
check("emoji/symbols only skipped", S().feed("!!! ??? \n\n", final=True) == [])
check("newlines count as boundaries", S().feed("First line is long enough to go.\nSecond line here", False) == ["First line is long enough to go."])
long = "word " * 80
o = S().feed(long, False); check("a never-ending sentence is cut at a space", len(o) == 1 and len(o[0]) <= 235 and o[0].count("word") > 20, o and len(o[0]))
# limit
sp = S(limit=120); got = []
for i in range(1, 8):
    got += sp.feed(" ".join(f"This is sentence number {k} of the story." for k in range(i)) + " ", False)
check("limit: stops at a sentence boundary", sum(len(x) for x in got) <= 120 and sp.finished and len(got) >= 2, got)
check("limit: nothing more afterwards", sp.feed("Another long sentence that will not be said at all. ", True) == [])
# restart after a tool round
sp = S(); a = sp.feed("Let me check that for you now. More", False)
b = sp.feed("The answer is forty-two, as far as I can tell from everything I found. Next", False)
check("text that restarts (after a tool) is treated as new", a == ["Let me check that for you now."] and b == ["The answer is forty-two, as far as I can tell from everything I found."], (a, b))
# huge first sentence over limit
check("first sentence longer than the limit is cut, not dropped", S(limit=30).feed("This sentence is a lot longer than the limit allows for. ", False) != [])

# ---------------- robot streaming with stand-ins
rate = 16000
def tone(sec): return 0.3 * np.sin(np.arange(int(rate * sec)) / 7)
def write(path, sec): robot.write_wav(pathlib.Path(path), tone(sec), rate)
class Player:
    available = True
    def __init__(s): s.events = []; s.t0 = time.monotonic()
    def play(s, p): s.events.append((time.monotonic() - s.t0, pathlib.Path(p).name, robot.wav_seconds(pathlib.Path(p))))
    def stop(s): s.events.append((time.monotonic() - s.t0, "STOP", 0))
texts = []
def synth(text, out, voice, rate_, stop=None):
    texts.append(text); time.sleep(0.05); write(out, 0.4); return True
pl = Player(); r = robot.Robot(pl, synth, pathlib.Path(home) / "st"); r.configure("clean", "v", 0, 0, 0.9)
check("start", r.start_stream() and r.streaming)
t0 = time.monotonic()
r.feed("First sentence."); time.sleep(0.25)
check("he starts talking BEFORE the answer is finished", len([e for e in pl.events if e[1] != "STOP"]) == 1, pl.events)
r.feed("Second one."); r.feed("Third one is here."); time.sleep(0.2)
check("remaining time is a sensible number", 200 < r.remaining_ms() < 2000, r.remaining_ms())
r.finish(); time.sleep(1.6)
plays = [e for e in pl.events if e[1] != "STOP"]
check("all three played in order", len(plays) == 3 and texts == ["First sentence.", "Second one.", "Third one is here."], (texts, plays))
gaps = [plays[i + 1][0] - (plays[i][0] + plays[i][2]) for i in range(2)]
check("one starts after the other ends (no overlap) and with only a short gap", all(-0.02 <= g < 0.3 for g in gaps), gaps)
check("remaining is 0 when done", r.remaining_ms() == 0, r.remaining_ms())
# the next sentence is prepared while one plays
texts.clear(); pl2 = Player(); slow_calls = []
def synth2(text, out, voice, rate_, stop=None):
    slow_calls.append(time.monotonic()); time.sleep(0.3); write(out, 0.6); return True
r2 = robot.Robot(pl2, synth2, pathlib.Path(home) / "st2"); r2.configure("clean")
r2.start_stream(); r2.feed("One."); r2.feed("Two."); r2.feed("Three."); r2.finish(); time.sleep(2.6)
p2 = [e for e in pl2.events if e[1] != "STOP"]
check("prepared ahead: gaps stay small even though preparing takes 0.3s", len(p2) == 3 and all((p2[i + 1][0] - (p2[i][0] + p2[i][2])) < 0.15 for i in range(2)), p2)
# stop
pl3 = Player(); r3 = robot.Robot(pl3, synth, pathlib.Path(home) / "st3"); r3.configure("clean")
r3.start_stream(); r3.feed("One."); r3.feed("Two."); r3.feed("Three."); time.sleep(0.15)
t = time.monotonic(); r3.stop(); took = time.monotonic() - t; time.sleep(1.5)
pl_ = [e for e in pl3.events if e[1] != "STOP"]
check("stop is quick, silences, and nothing more plays afterwards", took < 0.8 and len(pl_) <= 1 and any(e[1] == "STOP" for e in pl3.events) and not r3.streaming and r3.remaining_ms() == 0, (took, pl3.events))
# start again after stop
check("can start a new stream after stop", r3.start_stream()); r3.stop()
# a failing sentence doesn't kill the rest
calls = []
def synth_flaky(text, out, voice, rate_, stop=None):
    calls.append(text)
    if text == "Bad.": return False
    write(out, 0.2); return True
pl4 = Player(); r4 = robot.Robot(pl4, synth_flaky, pathlib.Path(home) / "st4"); r4.configure("clean")
r4.start_stream(); r4.feed("Good one."); r4.feed("Bad."); r4.feed("Another good one."); r4.finish(); time.sleep(1.2)
check("a failed sentence is skipped, the others are said", [e[1] for e in pl4.events if e[1] != "STOP"] and len([e for e in pl4.events if e[1] != "STOP"]) == 2, pl4.events)
# synth raising
def synth_boom(text, out, voice, rate_, stop=None): raise RuntimeError("kaput")
r5 = robot.Robot(Player(), synth_boom, pathlib.Path(home) / "st5"); r5.configure("clean"); r5.start_stream(); r5.feed("Hi there."); r5.finish(); time.sleep(0.4)
check("exception in the voice: no crash, error remembered", "kaput" in r5.last_error)
# fallback voice used in streaming too
fb = []
def fallback(text, out, voice, rate_, stop=None): fb.append(text); write(out, 0.2); return True
pl6 = Player(); r6 = robot.Robot(pl6, lambda *a, **k: False, pathlib.Path(home) / "st6", fallback); r6.configure("clean"); r6.start_stream(); r6.feed("Hello."); r6.finish(); time.sleep(0.6)
check("fallback voice works while streaming", fb == ["Hello."] and len([e for e in pl6.events if e[1] != "STOP"]) == 1)
# regular say still works
pl7 = Player(); r7 = robot.Robot(pl7, synth, pathlib.Path(home) / "st7"); r7.configure("clean"); r7.say("Plain."); time.sleep(0.8)
check("old say() still works", len([e for e in pl7.events if e[1] != "STOP"]) == 1)

# ---------------- speaker
config.SETTINGS_FILE.write_text("{}")
spk = speaker.Speaker()
pl8 = Player(); spk.boy = robot.Robot(pl8, synth, pathlib.Path(home) / "st8"); spk.boy.configure("android")
spk.mode = "boy"
check("boy can stream", spk.can_stream())
check("begin_stream", spk.begin_stream() and spk.streaming)
spk.feed("Hello there, this is the start of a long answer. And it is"); time.sleep(0.4)
check("first sentence spoken while the rest is still coming", len([e for e in pl8.events if e[1] != "STOP"]) == 1, pl8.events)
spk.end_stream("Hello there, this is the start of a long answer. And it is done now."); time.sleep(1.0)
check("the rest is spoken at the end", len([e for e in pl8.events if e[1] != "STOP"]) == 2)
check("stream_remaining_ms >= 0", spk.stream_remaining_ms() >= 0)
spk.stop(); check("stop ends the stream", not spk.streaming and spk.stream_remaining_ms() == 0)
for m in ("babble", "windows"):
    spk.mode = m; check(f"{m} does not stream", not spk.can_stream())
spk.mode = "boy"; spk.boy = robot.Robot(Player(), synth, pathlib.Path(home) / "st9")
check("feed without a stream does nothing", (spk.stop(), spk.feed("Hi there friend."))[1] is None)
print("\nFAILED:" if bad else "\nALL PASSED", bad or "")
sys.exit(1 if bad else 0)
