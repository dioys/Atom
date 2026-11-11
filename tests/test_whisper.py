import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, wave, io, json
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
for k in ("GROQ_API_KEY",): os.environ.pop(k, None)
sys.path.insert(0, SRC)
import config, voice
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)

pcm = (b"\x10\x00\xf0\xff" * 8000)   # 0.5 s of fake audio at 16 kHz
w = voice.to_wav(pcm)
with wave.open(io.BytesIO(w)) as f:
    check("wav header", f.getnchannels() == 1 and f.getsampwidth() == 2 and f.getframerate() == 16000 and f.getnframes() == 16000)
check("language code", voice._language_code("en-US") == "en" and voice._language_code("fil-PH") == "fil" and voice._language_code(None) == "en")

# cleaning
seg = lambda t, ns, lp: {"text": t, "no_speech_prob": ns, "avg_logprob": lp}
check("keeps confident speech", voice._clean_whisper({"segments": [seg(" play Dare by Gorillaz", 0.01, -0.2)]}) == "play Dare by Gorillaz")
check("drops no-speech segments", voice._clean_whisper({"segments": [seg("hello", 0.01, -0.3), seg("Thanks for watching", 0.9, -1.5)]}) == "hello")
check("keeps unsure-but-speech", voice._clean_whisper({"segments": [seg("open excel", 0.7, -0.3)]}) == "open excel")
check("phantom 'Thank you.' dropped", voice._clean_whisper({"text": "Thank you."}) == "")
check("real thank you sentence kept", voice._clean_whisper({"text": "Thank you for opening the report, Atom."}) != "")
check("plain text reply", voice._clean_whisper({"text": " hi atom "}) == "hi atom")
check("empty reply", voice._clean_whisper({}) == "")

# engine choice
check("no groq key -> google", voice.speech_engine() == "google")
os.environ["GROQ_API_KEY"] = "gsk_test"
check("groq key -> whisper", voice.speech_engine() == "whisper")
config.save_settings({"speech_engine": "google"})
check("user can force google", voice.speech_engine() == "google")
config.save_settings({})

# whisper call is built right
seen = {}
def fake_call(wav, key, language, prompt):
    seen.update(wav=wav, key=key, language=language, prompt=prompt)
    return {"text": "play dare", "segments": [seg("play Dare", 0.0, -0.1)]}
voice._whisper_call = fake_call
check("whisper used", voice.transcribe(pcm, language="en-US", hint="budget, sales") == "play Dare")
check("call details", seen["key"] == "gsk_test" and seen["language"] == "en" and "budget, sales" in seen["prompt"] and "Spotify" in seen["prompt"] and seen["wav"][:4] == b"RIFF")

# fallbacks
google_calls = []
voice.transcribe_google = lambda pcm, language=None: google_calls.append(1) or "from google"
def boom(*a): raise ConnectionError("no internet")
voice._whisper_call = boom
check("whisper failure falls back to google", voice.transcribe(pcm) == "from google" and google_calls)
try:
    voice.transcribe_whisper(pcm); check("transcribe_whisper raises SpeechError", False)
except voice.SpeechError as e:
    check("transcribe_whisper raises SpeechError", "ConnectionError" in str(e))
os.environ.pop("GROQ_API_KEY")
try:
    voice.transcribe_whisper(pcm); check("no key -> SpeechError", False)
except voice.SpeechError as e:
    check("no key -> SpeechError", "Groq key" in str(e))
google_calls.clear(); voice._whisper_call = fake_call
voice.transcribe(pcm); check("no key: google directly", len(google_calls) == 1)
print("ALL PASSED" if not bad else bad)
