"""speaker.py - Step 8: Atom can read his answers out loud.

Four kinds of voice, chosen in Settings:
  * boy     - a young robot-boy voice made on this PC by the free Kokoro model (kokovoice.py), made younger and given a
                faint robot shimmer (robot.py). The default. Needs a one-time set-up;
                until then a Windows voice (with the same boy sound) takes over.
  * robot   - real words from a Windows voice with an electric sound on top (robot.py).
  * babble  - a cute blip for every syllable, like Capri (babble.py).
  * windows - the real voices that come with Windows (Qt's text-to-speech).
All are free and work without internet.

  speakable(text)  - turns an answer into something pleasant to listen to
  Speaker          - say() and stop(); `available` is False if this PC has no voice
"""

from __future__ import annotations

import re

import aivoice
import babble
import config
import kokovoice
import robot

# set by Speaker.apply_settings(): the babble speed while his voice is the babble, otherwise None
_BABBLE_RATE: float | None = None

try:
    from PySide6.QtTextToSpeech import QTextToSpeech
except ImportError:  # the add-on isn't installed: Atom just stays silent
    QTextToSpeech = None

_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\\/\s]+){2,}")
_MARKDOWN = re.compile(r"[*_`#>|~]+")
_SYMBOLS = re.compile(r"[^\w\s.,!?;:'\"()%$€£₱&@/+=-]", re.UNICODE)  # emoji and other noise


def speakable(text: str, limit: int | None = None) -> str:
    """Clean an answer for speaking: no links, file paths, markdown or emoji,
    and not too long (long answers are read only up to a sentence boundary)."""
    limit = limit or config.SPEAK_MAX_CHARS
    text = _URL.sub("a link", text or "")
    text = _PATH.sub(lambda m: re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1], text)
    text = _MARKDOWN.sub(" ", text)
    text = _SYMBOLS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= limit * 0.4:
        return cut[: end + 1]
    return cut[: cut.rfind(" ")].rstrip(",;:") + "."


_BOUNDARY = re.compile(r"[.!?\u2026]+[\"')\]]*\s+|\n+")


class StreamSplitter:
    """Cuts an answer that is still being written into sentences he can start saying right away.

    feed(text_so_far) gives back the sentences that are finished and new since the last call;
    feed(final_text, final=True) also gives back the last piece. Very short sentences are joined with the next one."""

    FIRST_MIN, MIN, MAX = 24, 60, 230

    def __init__(self, limit: int | None = None):
        self.limit = limit or config.SPEAK_MAX_CHARS
        self.count = 0              # sentences given out so far
        self.spoken = 0             # characters given out so far
        self.finished = False       # the length limit was reached: nothing more is said
        self._done = 0              # how much of the text has been used
        self._seen = ""

    def _emit(self, raw: str, out: list) -> None:
        chunk = speakable(raw, 10**6)
        if not re.search(r"\w", chunk):
            return
        if self.count and self.spoken + len(chunk) > self.limit:
            self.finished = True
            return
        if not self.count and len(chunk) > self.limit:
            chunk = speakable(raw, self.limit)
        out.append(chunk)
        self.count += 1
        self.spoken += len(chunk)

    def feed(self, text: str, final: bool = False) -> list[str]:
        out: list[str] = []
        text = text or ""
        if not text.startswith(self._seen):       # a new try at the answer (after a tool): start again
            self._done, self._seen = 0, ""
        if self.finished:
            return out
        pending = text[self._done:]
        start = 0
        for m in _BOUNDARY.finditer(pending):
            piece = pending[start:m.end()]
            need = self.FIRST_MIN if self.count == 0 else self.MIN
            if len(speakable(piece, 10**6)) >= need:
                self._emit(piece, out)
                start = m.end()
                if self.finished:
                    break
        rest = pending[start:]
        if not self.finished and not final and len(rest) > self.MAX:   # a very long sentence: cut it at a comma or space
            cut = max(rest.rfind(", ", 0, self.MAX), rest.rfind(" ", 0, self.MAX))
            if cut > 40:
                self._emit(rest[:cut + 1], out)
                start += cut + 1
        elif not self.finished and final:
            self._emit(rest, out)
            start = len(pending)
        self._done += start
        self._seen = text[: self._done]
        return out


def estimate_ms(text: str, spoken: bool = False) -> int:
    """How long Atom's mouth should move for this answer: the time his voice takes
    when he speaks it (about 14 characters a second), or a fast reading pace when he doesn't."""
    if spoken and _BABBLE_RATE is not None:   # his voice is the babble: the mouth moves as long as the blips last
        return int(min(max(babble.duration_ms(speakable(text), _BABBLE_RATE) + 300, 1200), 30000))
    if spoken:
        length = len(speakable(text))
        return int(min(max(length * 72, 1500), 30000))
    return int(min(max(len(text or "") * 20, 1200), 6000))  # about as long as the text takes to type


class Speaker:
    SAMPLE = "Hello! I'm Atom. This is how I sound when I read your answers."

    def __init__(self):
        self._tts = None
        self._voices: list[dict] | None = None  # filled the first time the list is asked for
        self.babbler = babble.Babbler()
        self.robot = robot.Robot()
        self.ai = robot.Robot(synth=aivoice.GroqVoice(), fallback=robot.windows_say_to_file)    # kept, but Settings no longer offers it
        self.boy = robot.Robot(synth=kokovoice.KokoroVoice(), fallback=robot.windows_say_to_file)
        self._splitter: StreamSplitter | None = None
        self._stream_engine = None              # the voice that is speaking an answer while it is still being written
        self.muted = False                      # True during a call: he stays silent so he is never heard on the call
        self.mode = "windows"                   # "boy", "robot" (electric words), "babble" (cute blips) or "windows" (a real voice)
        if QTextToSpeech is not None:
            try:
                if QTextToSpeech.availableEngines():
                    self._tts = QTextToSpeech()
                    self._tts.setRate(config.SPEECH_RATE)
                    self._tts.setVolume(config.SPEECH_VOLUME)
            except Exception as error:  # no voices installed, driver problem...
                print(f"[atom] text-to-speech unavailable: {error}")
                self._tts = None
        self.apply_settings()

    @property
    def has_windows_voice(self) -> bool:
        return self._tts is not None

    @property
    def available(self) -> bool:
        """Can he make any sound with the voice type chosen now?"""
        if self.muted:
            return False
        if self.mode == "babble":
            return self.babbler.available
        if self.mode == "robot":
            return self.robot.available
        if self.mode == "boy":
            return self.boy.available
        if self.mode == "ai":
            return self.ai.available
        return self._tts is not None

    # ------------------------------------------------------------ voices
    def voices(self) -> list[dict]:
        """Every voice installed on this PC: [{"name", "locale", "label"}], best guesses first
        (voices for your own language at the top)."""
        if self._voices is not None:
            return [dict(v) for v in self._voices]
        found: list[dict] = []
        if self._tts:
            try:
                keep = self._tts.locale()
                for locale in self._tts.availableLocales():
                    self._tts.setLocale(locale)
                    for voice in self._tts.availableVoices():
                        found.append({"name": voice.name(), "locale": locale.name(), "_voice": voice, "_loc": locale})
                self._tts.setLocale(keep)
            except Exception as error:
                print(f"[atom] couldn't list voices: {error}")
        seen, unique = set(), []
        for v in found:
            key = (v["name"], v["locale"])
            if key not in seen:
                seen.add(key)
                unique.append(v)
        home = (config.get_speech_language() or "en")[:2].lower()
        unique.sort(key=lambda v: (not v["locale"].lower().startswith(home), v["locale"], v["name"]))
        for v in unique:
            v["label"] = f"{v['name']}  ({v['locale'].replace('_', '-')})"
        self._voices = unique
        return [dict(v) for v in unique]

    def apply_settings(self, name: str | None = None, locale: str | None = None,
                       rate: float | None = None, pitch: float | None = None,
                       mode: str | None = None, style: str | None = None, fx: str | None = None,
                       ai_voice: str | None = None,
                       boy_voice: str | None = None, age: str | None = None) -> None:
        """Use the voice type, voice, speed and pitch you chose (from settings.json unless given)."""
        global _BABBLE_RATE
        saved = config.load_settings()
        mode = mode or saved.get("voice_mode") or config.VOICE_MODE
        self.mode = mode if mode in ("boy", "ai", "babble", "robot") else "windows"
        style = style or saved.get("babble_style") or config.BABBLE_STYLE
        speed = saved.get("speech_rate", config.SPEECH_RATE) if rate is None else rate
        tone = saved.get("speech_pitch", config.SPEECH_PITCH) if pitch is None else pitch
        self.babbler.configure(style, tone, speed, config.SPEECH_VOLUME)
        _BABBLE_RATE = max(-1.0, min(1.0, float(speed))) if self.mode == "babble" else None
        voice_saved = saved.get("voice") or {}
        name = voice_saved.get("name") if name is None else name
        base_name = re.split(r"\s[-(]", name or "")[0].strip()   # "Microsoft David - English" -> "Microsoft David"
        self.robot.configure(fx or saved.get("robot_style") or config.ROBOT_STYLE, base_name, speed, tone,
                             config.SPEECH_VOLUME)
        age = robot.AGES.get(age or saved.get("boy_age") or config.BOY_AGE, robot.AGES["teen"])
        self.ai.configure("clean", ai_voice or saved.get("ai_voice") or config.AI_VOICE, speed, tone,
                          config.SPEECH_VOLUME, fallback_voice=base_name)
        self.boy.configure("android", boy_voice or saved.get("boy_voice") or config.BOY_VOICE, speed, tone,
                           config.SPEECH_VOLUME, fallback_voice=base_name, young=age)
        if not self._tts:
            return
        locale = voice_saved.get("locale") if locale is None else locale
        rate = saved.get("speech_rate", config.SPEECH_RATE) if rate is None else rate
        pitch = saved.get("speech_pitch", config.SPEECH_PITCH) if pitch is None else pitch
        try:
            if name:
                match = next((v for v in self.voices() if v["name"] == name and (not locale or v["locale"] == locale)), None)
                if match:
                    self._tts.setLocale(match["_loc"])
                    self._tts.setVoice(match["_voice"])
            self._tts.setRate(max(-1.0, min(1.0, float(rate))))
            self._tts.setPitch(max(-1.0, min(1.0, float(pitch))))
        except Exception as error:
            print(f"[atom] couldn't set the voice: {error}")

    def say(self, text: str) -> bool:
        """Speak `text` (replacing anything still being spoken). Returns False if it couldn't."""
        if self.muted:
            return False
        spoken = speakable(text)
        if self.mode == "babble":
            self.stop()
            return bool(spoken) and self.babbler.say(spoken)
        if self.mode == "robot":
            self.stop()
            return bool(spoken) and self.robot.say(spoken)
        if self.mode == "boy":
            self.stop()
            return bool(spoken) and self.boy.say(spoken)
        if self.mode == "ai":
            self.stop()
            return bool(spoken) and self.ai.say(spoken)
        if not self._tts or not spoken:
            return False
        try:
            self._tts.stop()
            self._tts.say(spoken)
            return True
        except Exception as error:
            print(f"[atom] couldn't speak: {error}")
            return False

    # ----------------------------------------------------- speaking while he writes
    STREAM_MODES = ("boy", "ai", "robot")

    def can_stream(self) -> bool:
        """Can this voice start talking while the answer is still being written?"""
        return self.mode in self.STREAM_MODES and self.available

    def begin_stream(self, on_play=None) -> bool:
        """on_play(text, seconds): called as each sentence starts to sound, so the window can show it just then."""
        self.stop()
        engine = {"boy": self.boy, "ai": self.ai, "robot": self.robot}.get(self.mode)
        if engine is None or not engine.start_stream(on_play):
            return False
        self._splitter, self._stream_engine = StreamSplitter(), engine
        return True

    def feed(self, text: str, final: bool = False) -> None:
        """The answer so far. Every finished sentence is spoken in turn."""
        if self._stream_engine is None or self._splitter is None:
            return
        for chunk in self._splitter.feed(text, final):
            self._stream_engine.feed(chunk)
        if final:
            self._stream_engine.finish()

    def end_stream(self, answer: str) -> None:
        self.feed(answer, final=True)

    @property
    def streaming(self) -> bool:
        return self._stream_engine is not None

    def warm_up(self) -> None:
        """Load the boy voice in the background, so his first sentence isn't slow."""
        import threading

        synth = getattr(self.boy, "synth", None)
        if self.mode != "boy" or not kokovoice.ready() or not hasattr(synth, "_load"):
            return

        def load() -> None:
            try:
                synth._load().create("Hi.", voice=kokovoice.DEFAULT_VOICE, speed=1.0, lang="en-us")
            except Exception as error:      # never a reason to bother anyone
                print(f"[atom] boy voice warm-up: {error}")

        threading.Thread(target=load, daemon=True).start()

    def stream_remaining_ms(self) -> int:
        return self._stream_engine.remaining_ms() if self._stream_engine is not None else 0

    def stop(self) -> None:
        self._stream_engine, self._splitter = None, None
        self.babbler.stop()
        self.robot.stop()
        self.ai.stop()
        self.boy.stop()
        if self._tts:
            try:
                self._tts.stop()
            except Exception:
                pass
