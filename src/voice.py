"""voice.py - helpers for turning your speech into text. No window code here.

The microphone itself is handled by the Recorder in ui.py (it needs Qt).
This file does the rest: measuring loudness, deciding when you've stopped
talking, converting audio, and sending it to a speech-to-text service.
"""

from __future__ import annotations

import io
import math
import re
import sys
import wave
from array import array

import config


class SpeechError(Exception):
    """A voice problem, with a message that is safe to show the user."""


def rms_level(pcm: bytes) -> float:
    """Loudness of 16-bit mono audio: 0.0 (silent) to 1.0 (as loud as possible)."""
    pcm = pcm[: len(pcm) // 2 * 2]
    if not pcm:
        return 0.0
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    total = sum(s * s for s in samples)
    return math.sqrt(total / len(samples)) / 32768


# sample format name -> (array typecode, factor that scales values to -1..1)
_SAMPLE_TYPES = {
    "int16": ("h", 1 / 32768),
    "int32": ("i", 1 / 2147483648),
    "float32": ("f", 1.0),
}


def convert_audio(raw: bytes, sample_rate: int, channels: int, sample_format: str,
                  target_rate: int | None = None) -> bytes:
    """Convert microphone audio to 16-bit mono at `target_rate` (default 16 kHz)."""
    if sample_format not in _SAMPLE_TYPES:
        raise SpeechError(f"Your microphone uses an audio format I can't read ({sample_format}).")
    code, scale = _SAMPLE_TYPES[sample_format]
    target_rate = target_rate or config.SAMPLE_RATE

    samples = array(code)
    raw = raw[: len(raw) // samples.itemsize * samples.itemsize]
    samples.frombytes(raw)

    channels = max(1, channels)
    frames = len(samples) // channels
    if channels == 1:
        mono = [s * scale for s in samples]
    else:  # mix all channels down to one
        mono = [
            sum(samples[i * channels:(i + 1) * channels]) / channels * scale
            for i in range(frames)
        ]

    if sample_rate != target_rate and frames > 1:
        ratio = sample_rate / target_rate
        resampled = []
        for n in range(int(frames / ratio)):
            start = int(n * ratio)
            end = max(start + 1, min(frames, int((n + 1) * ratio)))
            window = mono[start:end]
            resampled.append(sum(window) / len(window))  # averaging also softens aliasing
        mono = resampled

    result = array("h", (max(-32768, min(32767, int(v * 32767))) for v in mono))
    if sys.byteorder == "big":
        result.byteswap()
    return result.tobytes()


class EndpointDetector:
    """Decides when you have finished speaking.

    Feed it 16-bit mono chunks as they arrive. It reports "finished" after you
    spoke and then went quiet, after the maximum length, or if nothing was said.
    """

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self.heard_speech = False
        self._quiet = 0.0
        self._total = 0.0

    def feed(self, pcm: bytes) -> tuple[float, bool]:
        """Returns (loudness 0-1, finished?)."""
        level = rms_level(pcm)
        seconds = len(pcm) / 2 / self.sample_rate
        self._total += seconds
        if level >= config.SILENCE_LEVEL:
            self.heard_speech = True
            self._quiet = 0.0
        else:
            self._quiet += seconds
        finished = (
            (self.heard_speech and self._quiet >= config.SILENCE_SECONDS)
            or self._total >= config.MAX_RECORD_SECONDS
            or (not self.heard_speech and self._total >= config.NO_SPEECH_SECONDS)
        )
        return level, finished


# ---------------------------------------------------------------- engines
def to_wav(pcm: bytes, rate: int | None = None) -> bytes:
    """16-bit mono audio as the bytes of a .wav file."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate or config.SAMPLE_RATE)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _language_code(language: str | None) -> str:
    """'en-US' -> 'en' (Whisper wants the short code)."""
    return (language or config.get_speech_language() or "en").split("-")[0].lower()


def _whisper_call(wav: bytes, key: str, language: str, prompt: str):
    """Send audio to Groq's Whisper. Returns the reply as a dict. Tests replace this."""
    import openai

    client = openai.OpenAI(api_key=key, base_url=config.PROVIDERS["groq"]["base_url"], timeout=30)
    request = dict(
        model=config.WHISPER_MODEL,
        file=("speech.wav", wav),
        language=language,
        temperature=0,
        response_format="verbose_json",
    )
    if prompt:
        request["prompt"] = prompt[:600]
    result = client.audio.transcriptions.create(**request)
    return result.model_dump() if hasattr(result, "model_dump") else dict(result)


# Whisper sometimes "hears" these in near-silence
_PHANTOM = {"thank you", "thanks", "thanks for watching", "thank you for watching", "you", "bye", "okay", "so"}


def _clean_whisper(reply: dict) -> str:
    """The text of the confident parts of a Whisper reply ('' if it heard no one)."""
    segments = reply.get("segments") or []
    if segments:
        kept = [
            (s.get("text") or "").strip()
            for s in segments
            if not ((s.get("no_speech_prob") or 0) > 0.6 and (s.get("avg_logprob") or 0) < -0.8)
        ]
        text = " ".join(t for t in kept if t).strip()
    else:
        text = (reply.get("text") or "").strip()
    if re.sub(r"[^a-z ]", "", text.lower()).strip() in _PHANTOM and len(text) < 25:
        return ""  # a classic silence hallucination
    return text


def transcribe_whisper(pcm: bytes, language: str | None = None, hint: str = "") -> str:
    """Turn speech into text with Whisper on Groq (far better than the free Google one).
    Needs a Groq key (the one from Settings) and internet. Raises SpeechError."""
    key = config.get_api_key("groq")
    if not key:
        raise SpeechError("Whisper needs a Groq key. Add one in Settings.")
    try:
        reply = _whisper_call(
            to_wav(pcm), key, _language_code(language), (config.WHISPER_PROMPT + " " + hint).strip()
        )
    except ImportError:
        raise SpeechError("Whisper needs the 'openai' package (python -m pip install openai).")
    except Exception as error:
        raise SpeechError(f"Whisper failed ({type(error).__name__}: {error})")
    return _clean_whisper(reply)


def transcribe_google(pcm: bytes, language: str | None = None) -> str:
    """Turn 16 kHz 16-bit mono audio into text with Google's free web speech service.
    Returns "" if no words were understood. Needs internet; the audio is sent to Google."""
    try:
        import speech_recognition as sr
    except ImportError:
        raise SpeechError(
            "Voice needs one more package. Run: python -m pip install SpeechRecognition "
            "then restart me."
        )
    recognizer = sr.Recognizer()
    audio = sr.AudioData(pcm, config.SAMPLE_RATE, 2)
    try:
        return recognizer.recognize_google(
            audio, language=language or config.get_speech_language()
        ).strip()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as error:
        raise SpeechError(
            f"I couldn't reach the speech service ({error}). Check your internet connection."
        )


def speech_engine() -> str:
    """Which engine will be used: 'whisper' or 'google'."""
    choice = config.load_settings().get("speech_engine") or config.SPEECH_ENGINE
    if choice == "google":
        return "google"
    return "whisper" if config.get_api_key("groq") else "google"  # "auto" and "whisper"


def transcribe(pcm: bytes, language: str | None = None, hint: str = "") -> str:
    """Speech to text with the best engine available. If Whisper fails (no
    internet, free limit used up), Atom quietly falls back to Google."""
    if speech_engine() == "whisper":
        try:
            return transcribe_whisper(pcm, language, hint)
        except SpeechError as error:
            print(f"[atom] {error}; using Google speech instead")
    return transcribe_google(pcm, language)
