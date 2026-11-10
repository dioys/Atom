"""loopback.py - Step 13: lets Atom hear a call.

A call's other side comes out of your speakers or headphones. Windows can hand Atom a copy of exactly that sound
("loopback"), so Atom hears the caller without touching the microphone and without joining the call. This file:

    Source        gets the sound (loopback of your speakers, or your microphone)
    Cutter        cuts the sound into sentences by listening for pauses
    Listener      a background thread that does both and hands each sentence on (to be turned into text)

Needs:  python -m pip install soundcard numpy     Test it:  python loopback_test.py
"""

from __future__ import annotations

import threading
import warnings
from collections import deque

import config
import voice

MIN_SPEECH_SECONDS = 0.4          # shorter noises (a click, a cough) are not sentences
PRE_ROLL_SECONDS = 0.3            # keep this much sound from before the first loud moment, so first words aren't clipped


# ------------------------------------------------------------------ format
def to_16k_mono(raw: bytes, rate: int, channels: int, sample_format: str = "float32") -> bytes:
    """Any block of audio -> 16 kHz 16-bit mono (what speech recognition wants)."""
    try:
        import numpy as np
    except ImportError:
        return voice.convert_audio(raw, rate, channels, sample_format)
    dtype = {"float32": np.float32, "int16": np.int16, "int32": np.int32}[sample_format]
    data = np.frombuffer(raw[: len(raw) // np.dtype(dtype).itemsize * np.dtype(dtype).itemsize], dtype=dtype).astype(np.float32)
    if sample_format == "int16":
        data /= 32768.0
    elif sample_format == "int32":
        data /= 2147483648.0
    channels = max(1, channels)
    data = data[: len(data) // channels * channels].reshape(-1, channels).mean(axis=1)
    target = config.SAMPLE_RATE
    if rate != target and len(data) > 1:
        positions = np.arange(int(len(data) * target / rate)) * (rate / target)
        # average over the window each new sample covers: softens the sound the way a low-pass would
        edges = np.minimum(len(data), np.maximum(positions + 1, positions + rate / target)).astype(int)
        csum = np.concatenate(([0.0], np.cumsum(data)))
        starts = positions.astype(int)
        data = (csum[edges] - csum[starts]) / np.maximum(1, edges - starts)
    return (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


# ------------------------------------------------------------------ cutting
class Cutter:
    """Feed it 16 kHz 16-bit mono sound in small pieces; it returns each finished sentence as one block of sound."""

    def __init__(self, level: float | None = None, pause: float | None = None, max_seconds: float | None = None):
        self.level = config.CALL_SPEECH_LEVEL if level is None else level
        self.pause = config.CALL_PAUSE_SECONDS if pause is None else pause
        self.max_seconds = config.CALL_MAX_UTTERANCE if max_seconds is None else max_seconds
        self._pre: deque[bytes] = deque()
        self._pre_seconds = 0.0
        self._reset()

    def _reset(self) -> None:
        self._buffer = bytearray()
        self._active = False
        self._speech = 0.0
        self._quiet = 0.0
        self._total = 0.0

    @staticmethod
    def _seconds(pcm: bytes) -> float:
        return len(pcm) / 2 / config.SAMPLE_RATE

    def feed(self, pcm: bytes) -> list[bytes]:
        if not pcm:
            return []
        seconds = self._seconds(pcm)
        loud = voice.rms_level(pcm) >= self.level
        out: list[bytes] = []
        if not self._active:
            if not loud:
                self._pre.append(pcm)
                self._pre_seconds += seconds
                while self._pre_seconds > PRE_ROLL_SECONDS and len(self._pre) > 1:
                    self._pre_seconds -= self._seconds(self._pre.popleft())
                return out
            self._active = True
            for piece in self._pre:
                self._buffer += piece
                self._total += self._seconds(piece)
            self._pre.clear()
            self._pre_seconds = 0.0
        self._buffer += pcm
        self._total += seconds
        if loud:
            self._speech += seconds
            self._quiet = 0.0
        else:
            self._quiet += seconds
        if self._quiet >= self.pause or self._total >= self.max_seconds:
            block = self._finish()
            if block:
                out.append(block)
        return out

    def _finish(self) -> bytes | None:
        block = bytes(self._buffer) if self._speech >= MIN_SPEECH_SECONDS else None
        self._reset()
        return block

    def flush(self) -> list[bytes]:
        block = self._finish() if self._active else None
        return [block] if block else []


# ------------------------------------------------------------------ sources
class SoundcardSource:
    """Sound from the `soundcard` package: loopback of the default speakers ('speaker') or the microphone ('mic')."""

    fmt = "float32"

    def __init__(self, kind: str = "speaker", block_seconds: float = 0.1):
        self.kind = kind
        self.block_seconds = block_seconds
        self.rate = 48000
        self.channels = 2
        self._recorder = None
        self._frames = 0

    def open(self) -> None:
        import soundcard as sc
        warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)   # "data discontinuity" is normal for loopback
        if self.kind == "mic":
            device = sc.default_microphone()
        else:
            speaker = sc.default_speaker()
            device = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        self.channels = max(1, min(2, int(getattr(device, "channels", 2) or 2)))
        self._frames = int(self.rate * self.block_seconds)
        self._recorder = device.recorder(samplerate=self.rate, channels=self.channels, blocksize=self._frames)
        self._recorder.__enter__()

    def read(self) -> bytes:
        data = self._recorder.record(numframes=self._frames)
        return data.astype("float32").tobytes()

    def close(self) -> None:
        if self._recorder is not None:
            try:
                self._recorder.__exit__(None, None, None)
            except Exception:
                pass
            self._recorder = None


# ------------------------------------------------------------------ listener
class Listener(threading.Thread):
    """Reads a source until stopped and calls on_utterance(pcm, speaker) for each sentence heard."""

    def __init__(self, source, on_utterance, speaker: str = "them", on_error=None, cutter: Cutter | None = None):
        super().__init__(name=f"atom-listen-{speaker}", daemon=True)
        self.source = source
        self.on_utterance = on_utterance
        self.speaker = speaker
        self.on_error = on_error or (lambda message: None)
        self.cutter = cutter or Cutter()
        self._stop_flag = threading.Event()
        self.heard_anything = False

    def stop(self) -> None:
        self._stop_flag.set()

    def run(self) -> None:
        try:
            self.source.open()
        except Exception as error:
            self.on_error(describe_problem(error))
            return
        try:
            while not self._stop_flag.is_set():
                raw = self.source.read()
                pcm = to_16k_mono(raw, self.source.rate, self.source.channels, self.source.fmt)
                if voice.rms_level(pcm) > 0.002:
                    self.heard_anything = True
                for block in self.cutter.feed(pcm):
                    self.on_utterance(block, self.speaker)
            for block in self.cutter.flush():
                self.on_utterance(block, self.speaker)
        except Exception as error:
            if not self._stop_flag.is_set():
                self.on_error(describe_problem(error))
        finally:
            self.source.close()


def describe_problem(error: Exception) -> str:
    name = type(error).__name__
    if isinstance(error, ImportError):
        return "Listening to a call needs the 'soundcard' package. Run: python -m pip install soundcard numpy"
    text = str(error)
    if "fromstring" in text or "binary mode" in text:
        return "The 'soundcard' package is too old for this numpy. Run: python -m pip install -U soundcard"
    return f"I couldn't listen to the call audio ({name}: {text[:160]}). Run  python loopback_test.py  to see what is wrong."


def make_listeners(controller, hear_me: bool | None = None, source_factory=SoundcardSource) -> list[Listener]:
    """The listeners for one call: the caller (what comes out of your speakers) and, if wanted, you (your microphone)."""
    hear_me = config.CALL_HEAR_ME if hear_me is None else hear_me
    def report(message):                       # looked up when it happens: the window sets on_error after this is built
        controller.on_error(message)

    listeners = [Listener(source_factory("speaker"), controller.hear, "them", on_error=report)]
    if hear_me:
        listeners.append(Listener(source_factory("mic"), controller.hear, "me", on_error=report))
    return listeners
