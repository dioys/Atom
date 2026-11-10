"""babble.py - Atom's "voice" as cute babble: one short blip per syllable (like Capri).

No words are spoken. When Atom talks, a little synthesized sound plays for every
syllable of his answer, with the pitch going up and down like a happy chatter.
Nothing is downloaded and nothing is sent to the internet: the sounds are made
here, with plain maths, and saved as small .wav files in  C:\\Users\\you\\.atom\\sounds .

  plan(text, rate)        - when each blip plays, and which note (no sound code: easy to test)
  duration_ms(text, rate) - how long the babble lasts (so his mouth moves for exactly that long)
  Babbler                 - say(text) / stop(); style and pitch are set with configure()

Styles: soft (round and gentle), retro (8-bit game), bubbly (little bloops), deep (low and calm).
"""

from __future__ import annotations

import math
import re
import struct
import sys
import threading
import wave
from pathlib import Path

RATE_HZ = 22050
STYLES = {
    "soft": "Soft - round and gentle",
    "retro": "Retro - 8-bit game",
    "bubbly": "Bubbly - little bloops",
    "deep": "Deep - low and calm",
}
BASE_HZ = {"soft": 392.0, "retro": 523.0, "bubbly": 349.0, "deep": 196.0}
SCALE = (0, 2, 4, 7, 9, 12, 14, 16)   # a happy pentatonic ladder: any order of these sounds nice
NOTES = len(SCALE)

try:
    import winsound  # Windows only (Atom is a Windows app)
except ImportError:  # pragma: no cover - other systems stay silent
    winsound = None

_TOKEN = re.compile(r"[A-Za-z0-9']+|[,.!?;:]")
_VOWELS = re.compile(r"[aeiouy]+", re.I)


# ================================================================== timing
def syllables(word: str) -> int:
    """About how many syllables a word has (1 to 6)."""
    if word.isdigit():
        return max(1, min(6, (len(word) + 1) // 2))
    count = len(_VOWELS.findall(word))
    if count > 1 and word.lower().endswith("e") and not word.lower().endswith(("le", "ee")):
        count -= 1   # a silent final e: "make", "like"
    return max(1, min(6, count))


def plan(text: str, rate: float = 0.0) -> list[tuple[int, int]]:
    """[(wait in milliseconds before the blip, note number 0-7), ...] for `text`.
    `rate` goes from -1 (slow) to 1 (fast)."""
    rate = max(-1.0, min(1.0, float(rate)))
    step = 100.0 / (1.0 + 0.6 * rate)       # time between two syllables
    steps: list[tuple[int, int]] = []
    pending = 0.0                            # extra silence to add before the next blip
    tokens = _TOKEN.findall(text or "")
    for token in tokens:
        if token in ",;:":
            pending += step * 1.3
        elif token in ".!?":
            pending += step * 2.6
            if steps and token in "!?":   # the last note of a question rises, of an exclamation jumps
                wait, note = steps[-1]
                steps[-1] = (wait, min(NOTES - 1, note + 3) if token == "?" else NOTES - 1)
        else:
            base = sum(ord(c) for c in token.lower())
            for i in range(syllables(token)):
                note = (base + i * 3 + (i % 2) * 2) % NOTES
                gap = step * (0.55 if i == 0 and steps else 1.0)   # a short breath between words
                steps.append((int(gap + pending), note))
                pending = 0.0
    return steps


def duration_ms(text: str, rate: float = 0.0) -> int:
    """How long the babble for `text` takes."""
    steps = plan(text, rate)
    return int(sum(w for w, _ in steps) + 120) if steps else 0


# ================================================================== sounds
def _envelope(i: int, n: int, attack: int, decay: float) -> float:
    if i < attack:
        return i / attack
    return math.exp(-decay * (i - attack) / n)


def blip_samples(style: str, hz: float, amp: float) -> list[float]:
    """One blip as numbers between -1 and 1."""
    if style == "retro":
        n = int(RATE_HZ * 0.075)
        out = []
        for i in range(n):
            phase = (i * hz / RATE_HZ) % 1.0
            wave_ = 1.0 if phase < 0.25 else -1.0       # a thin square wave: the classic 8-bit voice
            out.append(wave_ * _envelope(i, n, 60, 4.5) * amp * 0.55)
        return out
    if style == "bubbly":
        n = int(RATE_HZ * 0.11)
        out, phase = [], 0.0
        for i in range(n):
            t = i / n
            f = hz * (0.78 + 0.45 * math.sqrt(t))        # glides upward: a little "bloop"
            phase += 2 * math.pi * f / RATE_HZ
            out.append(math.sin(phase) * _envelope(i, n, 90, 3.2) * amp)
        return out
    if style == "deep":
        n = int(RATE_HZ * 0.12)
        out = []
        for i in range(n):
            phase = (i * hz / RATE_HZ) % 1.0
            tri = 4 * abs(phase - 0.5) - 1                # a soft triangle wave
            sub = math.sin(2 * math.pi * i * hz / 2 / RATE_HZ)
            out.append((0.8 * tri + 0.4 * sub) * _envelope(i, n, 140, 3.6) * amp * 0.8)
        return out
    n = int(RATE_HZ * 0.095)   # soft
    out = []
    for i in range(n):
        vibrato = 1 + 0.012 * math.sin(2 * math.pi * 24 * i / RATE_HZ)
        t = 2 * math.pi * hz * vibrato * i / RATE_HZ
        out.append((math.sin(t) + 0.28 * math.sin(2 * t)) * _envelope(i, n, 110, 4.0) * amp * 0.75)
    return out


def write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE_HZ)
        f.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples))


def sounds_dir() -> Path:
    return Path.home() / ".atom" / "sounds"


def ensure_sounds(style: str, pitch: float, amp: float = 0.8, folder: Path | None = None) -> list[Path]:
    """The 8 blip files for a style and pitch (made the first time, then reused).
    `pitch` goes from -1 (deep) to 1 (high)."""
    style = style if style in STYLES else "soft"
    step = round(max(-1.0, min(1.0, float(pitch))) * 10)
    folder = folder or sounds_dir()
    files = []
    for note, degree in enumerate(SCALE):
        path = folder / f"{style}_{step}_{note}.wav"
        if not path.exists():
            hz = BASE_HZ[style] * 2 ** ((degree + step * 0.7) / 12)
            write_wav(path, blip_samples(style, hz, amp))
        files.append(path)
    return files


# ================================================================ playing
class WinPlayer:
    """Plays a .wav file without waiting for it (Windows)."""

    @property
    def available(self) -> bool:
        return winsound is not None

    def play(self, path: Path) -> None:
        if winsound:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    def stop(self) -> None:
        if winsound:
            winsound.PlaySound(None, winsound.SND_PURGE)


class Babbler:
    """say(text) plays the babble in the background; stop() cuts it off."""

    def __init__(self, player=None, folder: Path | None = None):
        self.player = player or WinPlayer()
        self.folder = folder
        self.style, self.pitch, self.rate = "soft", 0.0, 0.0
        self._files: list[Path] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return bool(self.player.available)

    def configure(self, style: str = "soft", pitch: float = 0.0, rate: float = 0.0, volume: float = 0.8) -> None:
        self.style = style if style in STYLES else "soft"
        self.pitch = max(-1.0, min(1.0, float(pitch)))
        self.rate = max(-1.0, min(1.0, float(rate)))
        self._files = []
        if self.available:
            try:
                self._files = ensure_sounds(self.style, self.pitch, max(0.1, min(1.0, volume)), self.folder)
            except OSError as error:   # can't write the sound files: stay silent
                print(f"[atom] couldn't make the babble sounds: {error}")

    def say(self, text: str) -> bool:
        self.stop()
        steps = plan(text, self.rate)
        if not steps or not self._files:
            return False
        stop = threading.Event()
        self._stop = stop
        self._thread = threading.Thread(target=self._run, args=(steps, self._files, stop), daemon=True)
        self._thread.start()
        return True

    def _run(self, steps, files, stop: threading.Event) -> None:
        for wait, note in steps:
            if stop.wait(wait / 1000.0):
                return
            try:
                self.player.play(files[note % len(files)])
            except Exception as error:  # a sound problem must never break Atom
                print(f"[atom] babble: {error}")
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)
        try:
            self.player.stop()
        except Exception:
            pass


if __name__ == "__main__":  # python babble.py [style] : hear it
    import time

    style = sys.argv[1] if len(sys.argv) > 1 else "soft"
    b = Babbler()
    b.configure(style)
    sample = "Hello! I'm Atom. Do you want me to open your files?"
    print(f"{style}: {duration_ms(sample)} ms" + ("" if b.available else "  (no sound on this system)"))
    b.say(sample)
    time.sleep(duration_ms(sample) / 1000 + 0.5)
