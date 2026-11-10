"""robot.py - Atom's electric voice: real words, with a robot / electric sound on top.

How it works (all on your own PC, nothing is sent to the internet):
  1. A Windows voice says the text into a .wav file (the voice you picked in Settings,
     through PowerShell's built-in System.Speech - nothing extra to install).
  2. effect() changes that recording: a ring modulator makes it metallic, a comb filter makes
     it ring, and the "electric" style adds bit-crushing, a buzz and crackles that follow his words.
  3. The new recording is played.

  effect(samples, rate, style)  - the sound change (pure numpy, easy to test)
  Robot                         - say(text) / stop(); configure() sets style, voice, speed, pitch

Styles: electric (buzz and crackle), robot (metallic, like a movie robot), radio (a crackly walkie-talkie),
and clean (no robot sound at all; used by the AI voice, which only adds an occasional glitch).

glitch(samples, rate, amount)  - now and then a digital stutter, bit-crush burst, tape-slow or drop-out.
"""

from __future__ import annotations

import base64
import math
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

import babble

STYLES = {
    "electric": "Electric - buzzing and crackling",
    "robot": "Robot - metallic, like a movie robot",
    "radio": "Radio - a crackly walkie-talkie",
}
# "android" (a faint metallic shimmer on a natural voice) and "clean" are used by the boy voice, not offered in Settings
AGES = {"boy": 4.5, "teen": 2.5, "natural": 0.0}      # how many semitones higher his voice is made
AGE_LABELS = {
    "boy": "Young boy (higher)",
    "teen": "Teenage boy",
    "natural": "Natural voice (not changed)",
}
GLITCH_LEVELS = {"never": 0.0, "rarely": 0.6, "sometimes": 1.2, "often": 2.5}
GLITCH_LABELS = {
    "never": "Never glitches",
    "rarely": "Glitches rarely",
    "sometimes": "Glitches sometimes",
    "often": "Glitches often",
}

_PS_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$want = $env:ATOM_VOICE
if ($want) {
  $hit = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name } | Where-Object { $_ -like "*$want*" } | Select-Object -First 1
  if ($hit) { $s.SelectVoice($hit) }
}
$s.Rate = [int]$env:ATOM_RATE
$s.SetOutputToWaveFile($env:ATOM_OUT)
$s.Speak([System.IO.File]::ReadAllText($env:ATOM_TEXT, [System.Text.Encoding]::UTF8))
$s.Dispose()
"""

_ENCODED = base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")   # no quoting problems on the command line


# ================================================================== the sound change
def _envelope(x: np.ndarray, rate: int) -> np.ndarray:
    """How loud he is at each moment (0..1), smoothed over about 12 ms."""
    n = max(1, int(rate * 0.012))
    env = np.convolve(np.abs(x), np.ones(n) / n, mode="same")
    peak = env.max()
    return env / peak if peak > 0 else env


def _comb(x: np.ndarray, delay: int, gain: float) -> np.ndarray:
    """y[n] = x[n] + gain * y[n - delay]: a metallic ring (done a block at a time, so it is fast)."""
    y = x.copy()
    for k in range(delay, len(x), delay):
        y[k:k + delay] += gain * y[k - delay:k][: len(y[k:k + delay])]
    return y


def _bandpass(x: np.ndarray, rate: int, low: float, high: float) -> np.ndarray:
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / rate)
    spectrum[(freqs < low) | (freqs > high)] = 0
    return np.fft.irfft(spectrum, len(x))


def effect(samples: np.ndarray, rate: int, style: str = "electric", seed: int = 7) -> np.ndarray:
    """Make `samples` (floats between -1 and 1) sound electric. Returns the same length."""
    x = np.asarray(samples, dtype=np.float64)
    if x.size < 32:
        return x
    rng = np.random.default_rng(seed)
    t = np.arange(x.size) / rate
    env = _envelope(x, rate)
    if style == "clean":
        peak = np.abs(x).max()
        return x / peak * 0.9 if peak > 0 else x
    if style == "android":   # the voice stays natural; a quiet metallic ring and a touch of digital grit ride along
        ring = _comb(x, max(2, int(rate * 0.0034)), 0.30)
        grit = np.round(np.repeat(x[::3], 3)[: x.size] * 24) / 24
        y = 0.82 * ring + 0.10 * grit + 0.08 * x * np.sin(2 * math.pi * 90 * t)
        peak = np.abs(y).max()
        return y / peak * 0.9 if peak > 0 else y
    if style == "robot":
        ring = x * np.sin(2 * math.pi * 55 * t)
        y = 0.25 * x + 0.85 * ring
        y = _comb(y, max(2, int(rate * 0.0042)), 0.55)
        y = np.tanh(1.6 * y)
    elif style == "radio":
        y = _bandpass(x, rate, 420, 3000)
        y = np.tanh(3.0 * y)
        hold = 2   # a little bit-crushing: sample and hold
        y = np.repeat(y[::hold], hold)[: x.size]
        hiss = rng.normal(0, 1, x.size)
        hiss = _bandpass(hiss, rate, 1500, 5500)
        y = y + 0.07 * hiss * (0.25 + 0.75 * env)
        crackles = (rng.random(x.size) < 14 / rate) * rng.choice([-1.0, 1.0], x.size)
        y = y + 0.35 * crackles
    else:   # electric
        ring = x * np.sin(2 * math.pi * 120 * t)
        y = 0.45 * x + 0.75 * ring
        y = _comb(y, max(2, int(rate * 0.0031)), 0.45)
        hold = 3
        y = np.repeat(y[::hold], hold)[: x.size]            # sample and hold: a gritty, digital edge
        y = np.round(y * 40) / 40                           # about 6-bit
        saw = ((t * 95) % 1.0) * 2 - 1                      # a 95 Hz buzz that only sounds while he talks
        y = y + 0.10 * saw * env
        sparks = (rng.random(x.size) < 55 / rate) * rng.choice([-1.0, 1.0], x.size)
        y = y + 0.55 * sparks * (0.2 + 0.8 * env)           # crackles, more when he is loud
        y = np.tanh(1.8 * y)
    peak = np.abs(y).max()
    return y / peak * 0.9 if peak > 0 else y


def _fade(seg: np.ndarray, rate: int, ms: float = 2.0) -> np.ndarray:
    n = min(len(seg) // 2, max(1, int(rate * ms / 1000)))
    seg = seg.copy()
    ramp = np.linspace(0, 1, n)
    seg[:n] *= ramp
    seg[-n:] *= ramp[::-1]
    return seg


def glitch(samples: np.ndarray, rate: int, amount: float = 1.0, seed: int | None = None) -> np.ndarray:
    """Now and then, a short digital glitch while he is talking: a stutter, a bit-crushed burst,
    a tape-slow dip or a drop-out. `amount` 0 = never, about 1 = once or twice per answer. The length never changes."""
    x = np.asarray(samples, dtype=np.float64)
    if amount <= 0 or x.size < rate * 1.0:
        return x
    rng = np.random.default_rng(seed)
    seconds = x.size / rate
    count = min(6, int(rng.poisson(amount * (0.3 + 0.2 * seconds))))
    if count == 0:
        return x
    env = _envelope(x, rate)
    lo, hi = int(rate * 0.2), x.size - int(rate * 0.35)
    spots = np.flatnonzero(env[lo:hi] > 0.2) + lo      # only where he is actually talking
    if spots.size == 0:
        return x
    y = x.copy()
    for _ in range(count):
        p = int(rng.choice(spots))
        kind = rng.choice(["stutter", "stutter", "stutter", "crush", "crush", "slow", "drop"])
        if kind == "stutter":
            size = int(rate * rng.uniform(0.04, 0.09))
            seg = _fade(y[p:p + size], rate)
            reps = int(rng.integers(3, 6))
            block = np.tile(seg, reps)[: max(0, len(y) - p)]
            y[p:p + len(block)] = block
        elif kind == "crush":
            span = int(rate * rng.uniform(0.10, 0.22))
            hold = int(rng.integers(6, 12))
            part = np.repeat(y[p:p + span:hold], hold)[: len(y[p:p + span])]
            part = np.round(part * 6) / 6
            part = part + 0.08 * rng.normal(0, 1, len(part))
            y[p:p + len(part)] = part
        elif kind == "slow":
            span = int(rate * 0.18)
            seg = y[p:p + span]
            if len(seg) > 8:
                speed = np.linspace(1.0, 0.4, len(seg))
                pos = np.minimum(np.cumsum(speed) - speed[0], len(seg) - 1)
                y[p:p + len(seg)] = np.interp(pos, np.arange(len(seg)), seg)
        else:   # drop-out, then a tiny digital click where the sound comes back
            span = int(rate * rng.uniform(0.05, 0.10))
            y[p:p + span] = 0
            if p + span < len(y):
                y[p + span:p + span + 8] += 0.5 * rng.choice([-1.0, 1.0])
    return np.clip(y, -1.0, 1.0)


def time_stretch(x: np.ndarray, factor: float, n_fft: int = 1024, hop: int = 256) -> np.ndarray:
    """Make `x` `factor` times longer (2.0 = twice as long) without changing its pitch (a phase vocoder)."""
    x = np.asarray(x, dtype=np.float64)
    if abs(factor - 1.0) < 1e-3 or x.size < n_fft * 2:
        return x
    win = np.hanning(n_fft)
    padded = np.concatenate([np.zeros(n_fft // 2), x, np.zeros(n_fft)])
    starts = np.arange(0, len(padded) - n_fft, hop)
    frames = np.stack([padded[i:i + n_fft] * win for i in starts])
    spec = np.fft.rfft(frames, axis=1).T                          # (bins, frames)
    bins = spec.shape[0]
    advance = hop * 2 * np.pi * np.arange(bins) / n_fft
    steps = np.arange(0, spec.shape[1] - 1, 1.0 / factor)
    out = np.empty((bins, len(steps)), dtype=np.complex128)
    phase = np.angle(spec[:, 0])
    for k, step in enumerate(steps):
        i, frac = int(step), step - int(step)
        a, b = spec[:, i], spec[:, i + 1]
        mag = (1 - frac) * np.abs(a) + frac * np.abs(b)
        out[:, k] = mag * np.exp(1j * phase)
        delta = np.angle(b) - np.angle(a) - advance
        delta -= 2 * np.pi * np.round(delta / (2 * np.pi))
        phase = phase + advance + delta
    blocks = np.fft.irfft(out.T, n=n_fft, axis=1) * win
    y = np.zeros(hop * (len(steps) - 1) + n_fft)
    norm = np.zeros_like(y)
    for k in range(len(steps)):
        y[k * hop:k * hop + n_fft] += blocks[k]
        norm[k * hop:k * hop + n_fft] += win ** 2
    y /= np.maximum(norm, 1e-6)
    y = y[n_fft // 2:]
    return y[: int(round(len(x) * factor))]


def young(x: np.ndarray, semitones: float) -> np.ndarray:
    """A younger voice: higher pitch and a smaller-sounding throat (the whole sound is shifted up),
    but just as long and as fast as before."""
    if abs(semitones) < 0.05 or len(x) < 2048:
        return x
    factor = 2 ** (semitones / 12)
    idx = np.arange(0, len(x) - 1, factor)
    higher = np.interp(idx, np.arange(len(x)), x)                # higher, but shorter
    y = time_stretch(higher, factor)                              # back to the first length
    if len(y) < len(x):
        y = np.concatenate([y, np.zeros(len(x) - len(y))])
    return y[: len(x)]


def shift_pitch(x: np.ndarray, pitch: float) -> np.ndarray:
    """Higher or lower, by changing the playback speed (pitch -1..1 is about 3 semitones each way)."""
    factor = 2 ** (max(-1.0, min(1.0, pitch)) * 0.25)
    if abs(factor - 1) < 0.01:
        return x
    idx = np.arange(0, len(x) - 1, factor)
    return np.interp(idx, np.arange(len(x)), x)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate, channels, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128) / 128
    else:
        raise ValueError(f"unsupported sample size: {width} bytes")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


# ================================================================== the voice
def windows_say_to_file(text: str, out: Path, voice: str = "", rate: int = 0, stop: threading.Event | None = None) -> bool:
    """Have a Windows voice say `text` into `out` (a .wav). `rate` is -10 (slow) .. 10 (fast)."""
    if sys.platform != "win32":
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        text_file = f.name
    env = dict(os.environ, ATOM_TEXT=text_file, ATOM_OUT=str(out), ATOM_VOICE=voice or "", ATOM_RATE=str(int(rate)))
    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", _ENCODED],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=0x08000000,   # CREATE_NO_WINDOW: no black console window flashes up
        )
        while proc.poll() is None:
            if stop is not None and stop.wait(0.05):
                proc.kill()
                return False
            if stop is None:
                proc.wait(30)
        if proc.returncode != 0:
            print(f"[atom] robot voice: PowerShell said: {(proc.stderr.read() or b'').decode(errors='replace')[:300]}")
            return False
        return out.exists() and out.stat().st_size > 100
    except (OSError, subprocess.SubprocessError) as error:
        print(f"[atom] robot voice: couldn't run PowerShell: {error}")
        return False
    finally:
        try:
            os.unlink(text_file)
        except OSError:
            pass


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


class Robot:
    """say(text) makes the voice in the background and plays it; stop() cuts it off.

    Streaming (for answers that are still being written): start_stream(), then feed(sentence) for each finished
    sentence, then finish(). The next sentence is prepared while the last one is playing, so he starts talking
    after the first sentence instead of after the whole answer."""

    def __init__(self, player=None, synth=None, folder: Path | None = None, fallback=None):
        self.player = player or babble.WinPlayer()
        self.synth = synth or windows_say_to_file     # synth(text, out_path, voice, rate, stop) -> bool
        self.fallback = fallback                      # used when synth fails (for example, no internet)
        self.fallback_voice = ""
        self.glitch = 0.0
        self.young = 0.0
        self.latency_ms = 0                           # how long the last answer took to prepare
        self.notice = ""                              # why the fallback voice was used, if it was
        self.folder = folder or (Path.home() / ".atom" / "sounds")
        self.style, self.voice, self.rate, self.pitch, self.volume = "electric", "", 0.0, 0.0, 0.9
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._count = 0
        self.last_error = ""
        self._chunks: queue.Queue | None = None      # streaming: sentences waiting to be prepared
        self._ready: queue.Queue | None = None       # streaming: prepared sentences waiting to play
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._queued_chars = 0                       # fed but not prepared yet
        self._ready_ms = 0.0                         # prepared but not started yet
        self._play_until = 0.0                       # when the sound playing now ends (time.monotonic)
        self._streaming = False

    @property
    def available(self) -> bool:
        return bool(self.player.available) and (self.synth is not windows_say_to_file or sys.platform == "win32")

    def configure(self, style: str = "electric", voice: str = "", rate: float = 0.0, pitch: float = 0.0,
                  volume: float = 0.9, glitch: float = 0.0, fallback_voice: str = "", young: float = 0.0) -> None:
        self.style = style if style in STYLES or style in ("clean", "android") else "electric"
        self.young = max(0.0, min(8.0, float(young)))
        self.glitch = max(0.0, min(5.0, float(glitch)))
        self.fallback_voice = fallback_voice or ""
        self.voice = voice or ""
        self.rate = max(-1.0, min(1.0, float(rate)))
        self.pitch = max(-1.0, min(1.0, float(pitch)))
        self.volume = max(0.1, min(1.0, float(volume)))

    def say(self, text: str) -> bool:
        self.stop()
        if not text or not self.available:
            return False
        stop = threading.Event()
        self._stop = stop
        self._count = (self._count + 1) % 6   # a fresh file name each time: the last one may still be playing
        out = self.folder / f"robot_{self._count}.wav"
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.last_error = str(error)
            return False
        self._thread = threading.Thread(target=self._run, args=(text, out, stop), daemon=True)
        self._thread.start()
        return True

    def render(self, text: str, raw: Path, out: Path, stop: threading.Event | None = None) -> bool:
        """Say it, change the sound, save it. (Separate from playing, so it can be tested.)"""
        self.notice = ""
        if not self.synth(text, raw, self.voice, round(self.rate * 6), stop):
            if (stop is not None and stop.is_set()) or not self.fallback:
                return False
            self.notice = getattr(self.synth, "last_error", "") or "the first voice was not available"
            print(f"[atom] using the Windows voice instead ({self.notice})")
            if not self.fallback(text, raw, self.fallback_voice, round(self.rate * 6), stop):
                return False
        samples, rate = read_wav(raw)
        samples = young(samples, self.young)
        samples = shift_pitch(samples, self.pitch)
        samples = effect(samples, rate, self.style)
        samples = glitch(samples, rate, self.glitch) * self.volume
        write_wav(out, samples, rate)
        return True

    def _run(self, text: str, out: Path, stop: threading.Event) -> None:
        raw = out.with_name(out.stem + "_raw.wav")
        started = time.monotonic()
        try:
            if not self.render(text, raw, out, stop):
                if not stop.is_set():
                    self.last_error = (getattr(self.synth, "last_error", "")
                                       or "the Windows voice could not make the recording")
                    print(f"[atom] robot voice: {self.last_error}")
                return
            if not stop.is_set():
                took = int((time.monotonic() - started) * 1000)
                self.latency_ms = took if not self.latency_ms else int(0.5 * self.latency_ms + 0.5 * took)
                self.player.play(out)
        except Exception as error:  # a sound problem must never break Atom
            self.last_error = str(error)
            print(f"[atom] robot voice: {error}")
        finally:
            try:
                raw.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------ streaming
    @property
    def streaming(self) -> bool:
        return self._streaming

    def start_stream(self, on_play=None) -> bool:
        """on_play(text, seconds) is called the moment each sentence starts to sound (from a helper thread)."""
        self.stop()
        if not self.available:
            return False
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.last_error = str(error)
            return False
        stop = threading.Event()
        self._stop = stop
        self._chunks, self._ready = queue.Queue(), queue.Queue()
        self._queued_chars, self._ready_ms, self._play_until = 0, 0.0, 0.0
        self._on_play = on_play
        self._streaming = True
        self._threads = [
            threading.Thread(target=self._prepare_loop, args=(self._chunks, self._ready, stop), daemon=True),
            threading.Thread(target=self._play_loop, args=(self._ready, stop), daemon=True),
        ]
        for t in self._threads:
            t.start()
        return True

    def feed(self, text: str) -> None:
        """One finished sentence (or a few): it is prepared and played after the ones before it."""
        if self._streaming and self._chunks is not None and text and text.strip():
            with self._lock:
                self._queued_chars += len(text)
            self._chunks.put(text)

    def finish(self) -> None:
        """No more sentences are coming."""
        if self._streaming and self._chunks is not None:
            self._chunks.put(None)

    def remaining_ms(self) -> int:
        """About how much longer he will be talking (sound playing + prepared + still to prepare)."""
        with self._lock:
            playing = max(0.0, self._play_until - time.monotonic()) * 1000
            return int(playing + self._ready_ms + self._queued_chars * 72)

    def _prepare_loop(self, chunks: queue.Queue, ready: queue.Queue, stop: threading.Event) -> None:
        index = 0
        try:
            while not stop.is_set():
                text = chunks.get()
                if text is None:
                    break
                index = (index + 1) % 16
                out = self.folder / f"robot_s{index}.wav"
                raw = out.with_name(out.stem + "_raw.wav")
                try:
                    ok = self.render(text, raw, out, stop)
                    seconds = wav_seconds(out) if ok else 0.0
                except Exception as error:   # a sound problem must never break Atom
                    ok, seconds = False, 0.0
                    self.last_error = str(error)
                    print(f"[atom] voice: {error}")
                finally:
                    try:
                        raw.unlink()
                    except OSError:
                        pass
                with self._lock:
                    self._queued_chars = max(0, self._queued_chars - len(text))
                    if ok and not stop.is_set():
                        self._ready_ms += seconds * 1000
                if ok and not stop.is_set():
                    ready.put((out, seconds, text))
                elif not ok and not stop.is_set():
                    self.last_error = self.last_error or "the voice could not make a sentence"
        finally:
            ready.put(None)

    def _play_loop(self, ready: queue.Queue, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                item = ready.get()
                if item is None:
                    break
                path, seconds, text = item
                wait = self._play_until - time.monotonic()
                if wait > 0 and stop.wait(wait):    # the sentence before this one is still being said
                    break
                self.player.play(path)
                with self._lock:
                    self._ready_ms = max(0.0, self._ready_ms - seconds * 1000)
                    self._play_until = time.monotonic() + seconds + 0.06
                callback = getattr(self, "_on_play", None)
                if callback is not None:
                    try:
                        callback(text, seconds)      # e.g. the window shows these words now
                    except Exception as error:
                        print(f"[atom] voice: {error}")
        except Exception as error:
            self.last_error = str(error)
            print(f"[atom] voice: {error}")

    def stop(self) -> None:
        self._stop.set()
        self._streaming = False
        for q in (self._chunks, self._ready):
            if q is not None:
                q.put(None)      # wakes the helper threads so they notice the stop
        for t in self._threads:
            if t.is_alive() and t is not threading.current_thread():
                t.join(timeout=0.3)
        self._threads = []
        with self._lock:
            self._queued_chars, self._ready_ms, self._play_until = 0, 0.0, 0.0
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        try:
            self.player.stop()
        except Exception:
            pass


if __name__ == "__main__":  # python robot.py [style] : hear it (Windows)
    style = sys.argv[1] if len(sys.argv) > 1 else "electric"
    r = Robot()
    r.configure(style)
    print(f"{style}" + ("" if r.available else "  (needs Windows)"))
    r.say("Hello! I'm Atom. I opened Spotify for you. Do you want me to play something?")
    time.sleep(8)
    if r.last_error:
        print("problem:", r.last_error)
