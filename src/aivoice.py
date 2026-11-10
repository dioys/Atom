"""aivoice.py - Atom's AI voice: a natural young-sounding boy, made by Groq's AI speech model.

He talks at normal speed in a normal voice. Now and then a small digital glitch hits his voice
(that part is robot.glitch). If the AI voice can't be reached (no internet, no key, the daily limit
is used up) Atom quietly uses a Windows voice instead, so he is never silent.

  chunks(text)      - cuts an answer into pieces the speech model accepts (200 characters at most)
  GroqVoice         - GroqVoice()(text, out_path, voice, rate, stop) -> True when the .wav was made
  VOICES            - the boy voices to choose from

Needs the same Groq key Atom already uses for chatting. The first time, Groq may ask you to accept the
terms of the speech model: open  https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english
while signed in, press "Accept" once, and it works from then on.
"""

from __future__ import annotations

import io
import re
import threading
import wave
from pathlib import Path

import numpy as np

import config
from robot import write_wav

MODEL = "canopylabs/orpheus-v1-english"
LIMIT = 190            # the model takes at most 200 characters in one go
VOICES = {
    "troy": "Troy - young and easy-going",
    "austin": "Austin - friendly and bright",
    "daniel": "Daniel - calm and clear",
}
DEFAULT_VOICE = "troy"

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def chunks(text: str, limit: int = LIMIT) -> list[str]:
    """Pieces of at most `limit` characters, cut at the ends of sentences (or at spaces if a sentence is long)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE.split(text):
        while len(sentence) > limit:                       # a very long sentence: cut it at a space
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > limit * 0.4 else limit
            head, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if current:
                pieces.append(current)
                current = ""
            pieces.append(head)
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return [p for p in pieces if re.search(r"\w", p)]


def _friendly(error: Exception) -> str:
    """A short, human reason for a failed request."""
    text = str(error)
    low = text.lower()
    if "model_terms_required" in low or ("terms" in low and "accept" in low):
        return ("Groq needs you to accept the speech model's terms once: open console.groq.com/playground, "
                "choose the model canopylabs/orpheus-v1-english and press Accept")
    if "429" in low or "rate limit" in low or "rate_limit" in low:
        return "Groq's free limit for the AI voice is used up for now"
    if "401" in low or "invalid api key" in low or "authentication" in low:
        return "Groq did not accept the key"
    if "connect" in low or "timeout" in low or "timed out" in low or "network" in low:
        return "no internet connection to Groq"
    return text[:160]


def join_wavs(parts: list[bytes], gap_ms: int = 120) -> tuple[np.ndarray, int]:
    """Glue several .wav recordings (bytes) into one list of samples with a short breath between them."""
    pieces, rate = [], 0
    for blob in parts:
        with wave.open(io.BytesIO(blob), "rb") as w:
            this_rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if width != 2:
            raise ValueError(f"unsupported sample size: {width} bytes")
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        if rate and this_rate != rate:
            raise ValueError("the pieces have different sample rates")
        rate = this_rate
        pieces.append(data)
    if not pieces:
        return np.zeros(0), 22050
    gap = np.zeros(int(rate * gap_ms / 1000))
    out = pieces[0]
    for p in pieces[1:]:
        out = np.concatenate([out, gap, p])
    return out, rate


class GroqVoice:
    """Makes speech with Groq. Call it like a function; `last_error` says why it failed, if it did."""

    def __init__(self, client_factory=None):
        self._factory = client_factory or self._default_client
        self.last_error = ""
        self.model = MODEL

    @staticmethod
    def _default_client():
        key = config.get_api_key("groq")
        if not key:
            raise RuntimeError("there is no Groq key yet (add it in Settings)")
        from openai import OpenAI   # already needed by Atom's chat
        return OpenAI(api_key=key, base_url=config.PROVIDERS["groq"]["base_url"], timeout=25.0, max_retries=0)

    @property
    def ready(self) -> bool:
        return bool(config.get_api_key("groq"))

    def __call__(self, text: str, out: Path, voice: str = "", rate: int = 0,
                 stop: threading.Event | None = None) -> bool:
        self.last_error = ""
        voice = voice if voice in VOICES else DEFAULT_VOICE
        try:
            client = self._factory()
            blobs = []
            for piece in chunks(text):
                if stop is not None and stop.is_set():
                    return False
                reply = client.audio.speech.create(model=self.model, voice=voice, input=piece, response_format="wav")
                blobs.append(reply.content if hasattr(reply, "content") else reply.read())
            if not blobs:
                self.last_error = "nothing to say"
                return False
            samples, sample_rate = join_wavs(blobs)
            write_wav(out, samples, sample_rate)
            return True
        except Exception as error:   # the internet or the service can fail in many ways: never crash Atom
            self.last_error = _friendly(error)
            print(f"[atom] AI voice: {self.last_error}")
            return False
