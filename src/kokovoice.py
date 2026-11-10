"""kokovoice.py - Atom's boy voice, made on YOUR computer (no internet while he talks, no Groq, no Microsoft voice).

It uses Kokoro, a small free open-source speech model. robot.py then makes the voice younger and
adds a faint robot shimmer.

One-time set-up (in the VS Code terminal, with the venv on, from the atom folder):

    pip install kokoro-onnx
    python kokovoice.py setup        # downloads the voice files (about 120 MB) to  C:\\Users\\you\\.atom\\kokoro
    python kokovoice.py              # say a test sentence

  KokoroVoice()(text, out_path, voice, rate, stop) -> True when the .wav was made
  ready()        - are the add-on and the voice files there?
"""

from __future__ import annotations

import re
import sys
import threading
import urllib.request
from pathlib import Path

import numpy as np

from aivoice import chunks
from robot import write_wav

BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILE = "kokoro-v1.0.int8.onnx"        # the small version (about 90 MB)
VOICES_FILE = "voices-v1.0.bin"
VOICES = {
    "am_puck": "Puck - light and playful",
    "am_liam": "Liam - clear and young",
    "am_eric": "Eric - steady",
    "am_echo": "Echo - soft",
    "am_adam": "Adam - deeper (try Young boy)",
}
DEFAULT_VOICE = "am_puck"
RATE = 24000
PIECE = 240        # characters per piece of an answer


def folder() -> Path:
    return Path.home() / ".atom" / "kokoro"


def files_ready(where: Path | None = None) -> bool:
    where = where or folder()
    return (where / MODEL_FILE).is_file() and (where / VOICES_FILE).is_file()


def addon_installed() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def ready() -> bool:
    return addon_installed() and files_ready()


def problem() -> str:
    """What is missing, in plain words ('' when everything is there)."""
    if not addon_installed():
        return "the add-on is missing: in the terminal run   pip install kokoro-onnx"
    if not files_ready():
        return "the voice files are missing: in the terminal run   python kokovoice.py setup"
    return ""


def download(where: Path | None = None, say=print) -> bool:
    """Download the two voice files (once). Returns True when both are there."""
    where = where or folder()
    where.mkdir(parents=True, exist_ok=True)
    for name in (MODEL_FILE, VOICES_FILE):
        target = where / name
        if target.is_file() and target.stat().st_size > 1_000_000:
            say(f"{name}: already here")
            continue
        say(f"downloading {name} ...")
        part = target.with_suffix(target.suffix + ".part")
        try:
            with urllib.request.urlopen(BASE_URL + name, timeout=60) as reply, open(part, "wb") as out:
                total = int(reply.headers.get("Content-Length") or 0)
                done, shown = 0, -1
                while True:
                    block = reply.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    if total and done * 10 // total != shown:
                        shown = done * 10 // total
                        say(f"  {shown * 10}%")
            part.replace(target)
        except OSError as error:
            say(f"couldn't download {name}: {error}")
            try:
                part.unlink()
            except OSError:
                pass
            return False
    return files_ready(where)


class KokoroVoice:
    """Makes speech with Kokoro. Call it like a function; `last_error` says why it failed, if it did."""

    def __init__(self, model_factory=None, where: Path | None = None):
        self._factory = model_factory or self._default_model
        self._where = where
        self._model = None
        self._lock = threading.Lock()
        self.last_error = ""

    def _default_model(self):
        where = self._where or folder()
        from kokoro_onnx import Kokoro
        return Kokoro(str(where / MODEL_FILE), str(where / VOICES_FILE))

    def _load(self):
        with self._lock:
            if self._model is None:
                self._model = self._factory()      # takes a second or two the first time only
            return self._model

    def __call__(self, text: str, out: Path, voice: str = "", rate: int = 0,
                 stop: threading.Event | None = None) -> bool:
        self.last_error = ""
        voice = voice if voice in VOICES else DEFAULT_VOICE
        speed = max(0.7, min(1.3, 1.0 + int(rate) * 0.05))      # rate -6..6 -> a little slower or faster than normal
        try:
            if self._factory == self._default_model and problem():
                self.last_error = problem()
                print(f"[atom] boy voice: {self.last_error}")
                return False
            model = self._load()
            pieces = []
            for piece in chunks(text, PIECE):
                if stop is not None and stop.is_set():
                    return False
                samples, sample_rate = model.create(piece, voice=voice, speed=speed, lang="en-us")
                pieces.append((np.asarray(samples, dtype=np.float64), int(sample_rate)))
            if not pieces:
                self.last_error = "nothing to say"
                return False
            rates = {r for _, r in pieces}
            if len(rates) != 1:
                self.last_error = "the pieces have different sample rates"
                return False
            gap = np.zeros(int(pieces[0][1] * 0.12))
            parts = [pieces[0][0]]
            for samples, _ in pieces[1:]:
                parts += [gap, samples]
            write_wav(out, np.concatenate(parts), pieces[0][1])
            return True
        except Exception as error:      # a voice problem must never crash Atom
            self.last_error = re.sub(r"\s+", " ", str(error))[:160] or error.__class__.__name__
            print(f"[atom] boy voice: {self.last_error}")
            return False


if __name__ == "__main__":      # python kokovoice.py [setup]
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        if not addon_installed():
            print("First run:   pip install kokoro-onnx")
            sys.exit(1)
        print("The voice files are ready." if download() else "The download did not finish: check the internet and run this again.")
        sys.exit(0)
    import time

    import config
    from robot import Robot, windows_say_to_file

    if problem():
        print(f"Not ready yet: {problem()}")
        sys.exit(1)
    r = Robot(synth=KokoroVoice(), fallback=windows_say_to_file)
    r.configure("android", DEFAULT_VOICE, 0.0, 0.0, config.SPEECH_VOLUME, young=2.5)
    r.say("Hello! I'm Atom. I opened Spotify for you. Do you want me to play something?")
    time.sleep(10)
    if r.last_error:
        print(r.last_error)
    elif r.notice:
        print(f"That was the Windows voice, not Kokoro ({r.notice}).")
    else:
        print("That was Kokoro.")
