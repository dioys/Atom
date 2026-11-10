"""charpack.py - Atom's character as a folder of pictures, and how it moves.

No window code here (so it can be tested): ui.py draws what this file decides.

A character folder (for example  characters/jester/ ) contains:
  * one see-through PNG per expression (smug.png, happy.png, ...)
  * character.json, which says which picture to show for which mood:

      {
        "name": "Jester",
        "height": 210,                         # how tall he is on screen, in pixels
        "states": {"idle": ["smug"], "happy": ["happy", "laughing"], ...},
        "talk": ["talk_a", "talk_b", "talk_c"],  # pictures swapped quickly while he talks
        "rest": "smug",                          # the closed-mouth picture between words
        "icon": "happy"                          # picture used for the tray icon
      }

Moods Atom knows: idle, talking, thinking, listening, happy, laughing, proud,
worried, sad, surprised, curious, annoyed, sleepy, looking. A mood that has no
picture falls back to a similar one (see FALLBACKS), and finally to "idle", so
a character only needs "idle" to work.
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

FALLBACKS = {
    "proud": ["happy"],
    "laughing": ["happy"],
    "surprised": ["curious", "happy"],
    "curious": ["listening", "thinking"],
    "sad": ["worried"],
    "worried": ["sad"],
    "annoyed": ["worried"],
    "looking": ["idle"],
    "sleepy": ["idle"],
    "thinking": ["idle"],
    "listening": ["curious"],
    "happy": ["talking"],
    "talking": ["idle"],
}


# ============================================================= finding packs
def characters_dirs() -> list[Path]:
    """Where character folders may live: your own (C:\\Users\\you\\.atom\\characters)
    first, then the ones that come with Atom."""
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # _MEIPASS = inside Atom.exe
    dirs = [Path.home() / ".atom" / "characters", here / "characters"]
    return dirs


def find_pack(name: str) -> "Pack | None":
    """Load the character called `name` ("" or "orb" means: use the built-in orb)."""
    if not name or name.lower() == "orb":
        return None
    for base in characters_dirs():
        folder = base / name
        for candidate in [folder] + sorted(p for p in folder.glob("*") if p.is_dir()):
            # the second form catches a zip unpacked one folder too deep (jester\\jester\\smug.png)
            pack = Pack.load(candidate)
            if pack:
                return pack
    return None


def explain(name: str) -> str:
    """A plain-words report of where Atom looked for a character and what he found.
    Run  python charpack.py  to see it."""
    lines = [f"Looking for the character '{name}':"]
    for base in characters_dirs():
        folder = base / name
        if not folder.is_dir():
            lines.append(f"  - {folder}: no such folder")
            continue
        pngs = len(list(folder.glob("*.png")))
        has_json = (folder / "character.json").exists()
        lines.append(f"  - {folder}: found, {pngs} pictures, character.json {'yes' if has_json else 'MISSING'}")
    pack = find_pack(name)
    lines.append(f"Result: {'OK - ' + str(pack.folder) if pack else 'not usable, so Atom shows the orb'}")
    return "\n".join(lines)


# ================================================================= the pack
@dataclass
class Pack:
    folder: Path
    name: str
    height: int
    states: dict[str, list[str]]
    talk: list[str]
    rest: str
    icon: str
    sprites: dict[str, Path]
    face: tuple[int, int, int, int] | None = None   # x, y, width, height of the face in a picture (for the chat portrait)

    @classmethod
    def load(cls, folder: Path) -> "Pack | None":
        """Read a character folder. Returns None if it is missing or unusable
        (no character.json, or no picture for 'idle')."""
        folder = Path(folder)
        try:
            data = json.loads((folder / "character.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        sprites = {p.stem: p for p in folder.glob("*.png") if p.stem != "preview"}

        def known(names) -> list[str]:
            return [n for n in (names or []) if n in sprites]

        states = {s: known(names) for s, names in (data.get("states") or {}).items()}
        states = {s: names for s, names in states.items() if names}
        if "idle" not in states:
            return None
        talk = known(data.get("talk"))
        rest = data.get("rest") if data.get("rest") in sprites else states["idle"][0]
        icon = data.get("icon") if data.get("icon") in sprites else states["idle"][0]
        box = data.get("face")
        face = tuple(int(v) for v in box) if isinstance(box, (list, tuple)) and len(box) == 4 else None
        return cls(
            face=face,
            folder=folder,
            name=str(data.get("name") or folder.name),
            height=max(60, min(400, int(data.get("height") or 200))),
            states=states,
            talk=talk,
            rest=rest,
            icon=icon,
            sprites=sprites,
        )

    def face_box(self, width: int, height: int) -> tuple[int, int, int, int]:
        """The square of a picture shown as his portrait: from character.json ("face"), or
        a guess (a square from near the top, in the middle)."""
        if self.face:
            x, y, w, h = self.face
        else:
            side = int(min(width, height) * 0.8)
            x, y, w, h = (width - side) // 2, int(height * 0.1), side, side
        x, y = max(0, min(x, width - 1)), max(0, min(y, height - 1))
        return x, y, max(1, min(w, width - x)), max(1, min(h, height - y))

    def frames(self, state: str) -> list[str]:
        """The pictures for a mood, following the fallbacks if it has none of its own."""
        seen = set()
        queue = [state]
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            if self.states.get(current):
                return self.states[current]
            queue.extend(FALLBACKS.get(current, []))
        return self.states["idle"]


# ============================================================== the motion
@dataclass
class Pose:
    frame: str                 # picture to show now
    previous: str | None       # picture fading out (None when not changing)
    blend: float               # 0..1: how far the new picture has faded in
    dx: float = 0.0            # sideways shift in pixels
    dy: float = 0.0            # up/down shift (negative = up)
    rot: float = 0.0           # lean in degrees (turns around his shoulders)
    sx: float = 1.0            # width scale (squash and stretch)
    sy: float = 1.0            # height scale
    ring: float = 0.0          # 0..1 listening ring strength
    zzz: bool = False          # draw the sleeping z z z


class Animator:
    """Decides which picture to show and how it moves. Call set_state() when his
    mood changes and tick(seconds) about 30 times a second."""

    CROSSFADE = 0.09  # seconds to dissolve between two pictures

    def __init__(self, pack: Pack, rng: random.Random | None = None):
        self.pack = pack
        self.rng = rng or random.Random()
        self.state = "idle"
        self.t = 0.0           # total time
        self.state_t = 0.0     # time since the mood changed
        self.level = 0.0       # microphone loudness 0..1 while listening
        self.look = 0.0        # where the mouse is, -1 (left) .. 1 (right)
        self._look_smooth = 0.0
        self.frame = pack.frames("idle")[0]
        self.previous: str | None = None
        self._blend = 1.0
        self._flap_left = 0.0
        self._until_rest = 1.0
        self._rest_left = 0.0

    # ------------------------------------------------------------ inputs
    def set_state(self, state: str) -> bool:
        """Change mood. Returns False (and does nothing) if he is already in it."""
        if state == self.state:
            return False
        self.state = state
        self.state_t = 0.0
        self._flap_left = 0.0
        self._rest_left = 0.0
        self._until_rest = self.rng.uniform(0.9, 1.8)
        if state != "talking":
            self._show(self.rng.choice(self.pack.frames(state)))
        return True

    def set_level(self, level: float) -> None:
        self.level = max(self.level, min(1.0, level * 5))

    def set_look(self, x: float) -> None:
        self.look = max(-1.0, min(1.0, x))

    def _show(self, name: str, fade: bool = True) -> None:
        if name == self.frame:
            return
        self.previous = self.frame if fade else None
        self.frame = name
        self._blend = 0.0 if fade else 1.0

    # ------------------------------------------------------------- tick
    def tick(self, dt: float) -> Pose:
        dt = max(0.0, min(dt, 0.1))
        self.t += dt
        self.state_t += dt
        self.level *= 0.85 ** (dt / 0.033)
        self._look_smooth += (self.look - self._look_smooth) * min(1.0, dt * 6)
        if self._blend < 1.0:
            self._blend = min(1.0, self._blend + dt / self.CROSSFADE)
            if self._blend >= 1.0:
                self.previous = None
        if self.state == "talking":
            self._flap(dt)
        return self._pose()

    def _flap(self, dt: float) -> None:
        """Swap mouth pictures like speech: bursts of words with short pauses."""
        talk = self.pack.talk or self.pack.frames("talking")
        if self._rest_left > 0:
            self._rest_left -= dt
            if self._rest_left <= 0:
                self._until_rest = self.rng.uniform(0.9, 1.8)
                self._flap_left = 0.0
            return
        self._until_rest -= dt
        if self._until_rest <= 0 and len(talk) > 1:
            self._rest_left = self.rng.uniform(0.16, 0.28)
            self._show(self.pack.rest)
            return
        self._flap_left -= dt
        if self._flap_left <= 0:
            self._flap_left = self.rng.uniform(0.09, 0.18)
            choices = [n for n in talk if n != self.frame] or talk
            self._show(self.rng.choice(choices))

    # ------------------------------------------------------------- pose
    def _pose(self) -> Pose:
        t, s = self.t, self.state_t
        pose = Pose(self.frame, self.previous, self._blend)
        pose.dy = math.sin(t * 1.7) * 3.0               # gentle bobbing
        pose.sy = 1.0 + math.sin(t * 2.0) * 0.008       # breathing
        pose.sx = 1.0 - math.sin(t * 2.0) * 0.004
        pose.dx = self._look_smooth * 3.0               # leans a little toward your mouse
        pose.rot = self._look_smooth * 1.6
        pop = max(0.0, 1.0 - s / 0.35)                  # a quick "pop" when a mood starts

        st = self.state
        if st == "talking":
            beat = abs(math.sin(t * 9.5))
            pose.dy -= beat * 4.0
            pose.sy += beat * 0.02
            pose.sx -= beat * 0.012
            pose.rot += math.sin(t * 3.1) * 1.4
        elif st in ("happy", "laughing", "proud"):
            pose.dy -= abs(math.sin(t * 9.0)) * 14.0 * (1.0 if st != "proud" else 0.45)
            pose.rot += math.sin(t * 6.0) * (3.0 if st == "laughing" else 1.5)
            pose.sy += pop * 0.05
        elif st == "thinking":
            pose.rot += math.sin(t * 1.2) * 2.2
            pose.dx += math.sin(t * 0.9) * 3.0
        elif st in ("listening", "curious"):
            pose.rot += 2.5
            pose.sx += self.level * 0.05
            pose.sy += self.level * 0.05
            pose.ring = 1.0 if st == "listening" else 0.0
            pose.dy -= self.level * 6.0
        elif st in ("worried", "annoyed"):
            fade = max(0.0, 1.0 - s / 1.2)
            pose.dx += math.sin(t * 38.0) * 2.5 * fade   # a nervous tremble that settles
            pose.rot += math.sin(t * 2.0) * 1.0
        elif st == "sad":
            pose.dy += 5.0
            pose.rot -= 2.5
            pose.sy -= 0.015
        elif st == "surprised":
            pose.sx += pop * 0.10
            pose.sy += pop * 0.10
            pose.dy -= pop * 12.0
        elif st == "sleepy":
            pose.dy = 6.0 + math.sin(t * 0.9) * 4.0
            pose.sy = 1.0 + math.sin(t * 0.9) * 0.025
            pose.rot = -3.0 + math.sin(t * 0.45) * 1.5
            pose.zzz = True
        elif st == "looking":
            pose.rot += math.sin(t * 1.8) * 5.0
            pose.dx += math.sin(t * 1.8) * 7.0
        return pose


if __name__ == "__main__":
    import config

    print(explain(config.CHARACTER))
