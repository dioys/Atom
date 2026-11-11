import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import math, struct, sys, time, threading, array
sys.path.insert(0, SRC)
import config, voice, loopback as lb

def tone_f32(seconds, rate=48000, channels=2, amp=0.3, freq=440):
    n = int(seconds * rate); out = array.array("f")
    for i in range(n):
        v = amp * math.sin(2 * math.pi * freq * i / rate)
        out.extend([v] * channels)
    return out.tobytes()

def silence_f32(seconds, rate=48000, channels=2):
    return bytes(4 * int(seconds * rate) * channels)

# ---- format conversion: numpy path and the plain-python fallback agree
raw = tone_f32(0.5)
fast = lb.to_16k_mono(raw, 48000, 2, "float32")
assert abs(len(fast) / 2 - 8000) <= 2, len(fast)
assert 0.15 < voice.rms_level(fast) < 0.25, voice.rms_level(fast)            # 0.3 sine -> rms 0.21
import numpy
_np = sys.modules["numpy"]
sys.modules["numpy"] = None                                                   # pretend numpy is missing
slow = lb.to_16k_mono(raw, 48000, 2, "float32")
sys.modules["numpy"] = _np
assert abs(len(slow) / 2 - 8000) <= 2 and abs(voice.rms_level(slow) - voice.rms_level(fast)) < 0.03
assert voice.rms_level(lb.to_16k_mono(silence_f32(0.3), 48000, 2)) == 0
i16 = array.array("h", [int(10000 * math.sin(i / 5)) for i in range(16000)]).tobytes()
assert len(lb.to_16k_mono(i16, 16000, 1, "int16")) == len(i16)              # already 16 kHz mono: same length

# ---- cutting into sentences
def block(kind, seconds):          # 16 kHz mono
    n = int(16000 * seconds)
    if kind == "talk":
        return array.array("h", [int(8000 * math.sin(i / 4)) for i in range(n)]).tobytes()
    return bytes(2 * n)
c = lb.Cutter(level=0.02, pause=0.9, max_seconds=20)
got = []
for kind, sec in [("quiet", 1.0), ("talk", 1.5), ("quiet", 0.5), ("talk", 0.8), ("quiet", 1.2), ("quiet", 1.0), ("talk", 0.2), ("quiet", 1.5)]:
    for k in range(int(sec * 10)):
        got += c.feed(block(kind, 0.1))
assert len(got) == 1, len(got)                       # "talk 1.5 + 0.5 pause + talk 0.8" is one sentence (pause < 0.9); the 0.2 s blip is dropped
assert 3.4 < len(got[0]) / 2 / 16000 < 4.6, len(got[0]) / 32000
# a pause of 0.9 s or more splits sentences
c = lb.Cutter(level=0.02, pause=0.9)
sent = []
for kind, sec in [("talk", 1.0), ("quiet", 1.0), ("talk", 1.0), ("quiet", 1.0)]:
    for k in range(int(sec * 10)):
        sent += c.feed(block(kind, 0.1))
assert len(sent) == 2
# the start of the first word is kept (pre-roll), long talking is cut, flush returns what is left
c = lb.Cutter(level=0.02, pause=0.9, max_seconds=3)
parts = []
for k in range(80):
    parts += c.feed(block("talk", 0.1))
assert len(parts) >= 2 and all(len(p) / 32000 <= 3.3 for p in parts)
c = lb.Cutter(level=0.02, pause=0.9)
for k in range(10): c.feed(block("talk", 0.1))
assert len(c.flush()) == 1 and c.flush() == []
c = lb.Cutter(level=0.02); [c.feed(block("quiet", 0.1)) for _ in range(20)]
assert c.feed(block("talk", 0.1)) == [] and len(c._buffer) / 32000 <= 0.5       # at most 0.3 s of the quiet before it is kept

# ---- the listener thread with a fake source
class FakeSource:
    fmt = "float32"; rate = 48000; channels = 2
    def __init__(s, script): s.script = list(script); s.opened = s.closed = False
    def open(s): s.opened = True
    def read(s):
        if not s.script: time.sleep(0.01); return silence_f32(0.1)
        return s.script.pop(0)
    def close(s): s.closed = True
script = [silence_f32(0.1)] * 5 + [tone_f32(0.1)] * 15 + [silence_f32(0.1)] * 12
heard, errors = [], []
l = lb.Listener(FakeSource(script), lambda pcm, who: heard.append((who, len(pcm))), "them", on_error=errors.append, cutter=lb.Cutter(level=0.02))
l.start()
for _ in range(200):
    if heard: break
    time.sleep(0.02)
l.stop(); l.join(2)
assert not errors and len(heard) == 1 and heard[0][0] == "them" and l.heard_anything and l.source.opened and l.source.closed, (heard, errors)
assert 2.0 < heard[0][1] / 32000 < 3.0, heard

class Broken:
    fmt = "float32"; rate = 48000; channels = 2
    def open(s): raise ImportError("No module named 'soundcard'")
    def read(s): pass
    def close(s): pass
errs = []; b = lb.Listener(Broken(), lambda *a: None, on_error=errs.append); b.start(); b.join(2)
assert errs and "pip install soundcard" in errs[0], errs
assert "-U soundcard" in lb.describe_problem(TypeError("The binary mode of fromstring is removed"))
assert "loopback_test.py" in lb.describe_problem(RuntimeError("boom"))

# ---- the listeners for one call
class Ctl:
    def __init__(s): s.errors = []
    def hear(s, pcm, who): pass
    def on_error(s, m): s.errors.append(m)
made = []
ls = lb.make_listeners(Ctl(), hear_me=True, source_factory=lambda kind: made.append(kind) or FakeSource([]))
assert made == ["speaker", "mic"] and [x.speaker for x in ls] == ["them", "me"]
assert len(lb.make_listeners(Ctl(), hear_me=False, source_factory=lambda kind: FakeSource([]))) == 1
print("LOOPBACK OK")
