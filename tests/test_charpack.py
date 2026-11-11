import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import sys, json, random, tempfile, shutil
from pathlib import Path
sys.path.insert(0, SRC)
import charpack
from charpack import Pack, Animator

pack = Pack.load(Path(SRC + "/characters/jester"))
assert pack and pack.name == "Jester" and pack.height == 190
assert pack.talk == ["talk_a", "talk_b", "talk_c"] and pack.rest == "smug"
assert pack.frames("idle") == ["smug"]
assert pack.frames("laughing") == ["laughing"]

# missing/unusable packs
assert Pack.load(Path("/nonexistent")) is None
d = Path(tempfile.mkdtemp()); (d / "character.json").write_text("{bad")
assert Pack.load(d) is None
(d / "character.json").write_text(json.dumps({"states": {"idle": ["nope"]}}))
assert Pack.load(d) is None        # idle picture missing
shutil.copy(pack.sprites["smug"], d / "smug.png")
(d / "character.json").write_text(json.dumps({"states": {"idle": ["smug"], "happy": ["gone"]}, "talk": ["gone"]}))
mini = Pack.load(d)
assert mini and mini.talk == [] and mini.rest == "smug" and mini.icon == "smug"
# fallbacks: a mood without its own picture still gives something
for mood in ["laughing", "proud", "sad", "annoyed", "surprised", "sleepy", "looking", "talking", "weird"]:
    assert mini.frames(mood) == ["smug"], mood
a = Animator(mini, random.Random(1)); a.set_state("talking")
for _ in range(100): a.tick(0.033)          # no talk frames: must not crash
shutil.rmtree(d)

# talking flaps through the mouth pictures, pauses on the rest picture
a = Animator(pack, random.Random(3))
assert a.set_state("talking") and not a.set_state("talking")
seen, rest_seen = set(), 0
for _ in range(300):                         # 10 seconds
    p = a.tick(0.033); seen.add(p.frame)
    rest_seen += p.frame == "smug"
assert {"talk_a", "talk_b", "talk_c"} <= seen, seen
assert rest_seen > 0, "never closed his mouth"
assert all(f in pack.sprites for f in seen)

# crossfade
a = Animator(pack, random.Random(1)); a.tick(0.033)
a.set_state("happy")
p = a.tick(0.033)
assert p.previous == "smug" and 0 < p.blend < 1, (p.previous, p.blend)
for _ in range(10): p = a.tick(0.033)
assert p.previous is None and p.blend == 1.0 and p.frame in ("happy", "laughing")

# every mood produces a sane pose
for mood in ["idle","talking","thinking","listening","happy","laughing","proud","worried","sad","surprised","curious","annoyed","sleepy","looking","unknown"]:
    a = Animator(pack, random.Random(2)); a.set_state(mood); a.set_look(0.7); a.set_level(0.2)
    for _ in range(120):
        p = a.tick(0.033)
        assert p.frame in pack.sprites, (mood, p.frame)
        assert abs(p.dx) < 25 and abs(p.dy) < 30 and abs(p.rot) < 12, (mood, p)
        assert 0.8 < p.sx < 1.25 and 0.8 < p.sy < 1.25, (mood, p)
assert Animator(pack).tick(0.033).zzz is False
s = Animator(pack); s.set_state("sleepy"); assert s.tick(0.033).zzz
l = Animator(pack); l.set_state("listening"); assert l.tick(0.033).ring == 1.0

# happy bounces up; sleepy sinks
h = Animator(pack, random.Random(1)); h.set_state("happy")
assert min(h.tick(0.033).dy for _ in range(60)) < -8
# huge dt (laggy window) is clamped
a = Animator(pack); a.tick(5.0); assert a.t <= 0.1 + 1e-9
print("charpack ok")
