"""loopback_test.py - checks that Atom can hear a call, and shows what he would hear.

    1. Play a YouTube video or a voice message on your computer (or be in a call).
    2. Run:   python loopback_test.py
    3. For 10 seconds Atom listens to what comes out of your DEFAULT speakers/headphones, cuts it into sentences,
       and (if a Groq key is saved) writes down what was said. Nothing is saved to disk.
"""

from __future__ import annotations

import time

import loopback
import voice

LISTEN_SECONDS = 10


def main() -> int:
    try:
        import soundcard as sc
    except ImportError:
        print("The 'soundcard' package is missing.\n  Run: python -m pip install soundcard numpy")
        return 1
    try:
        print("Default speakers:", sc.default_speaker().name)
    except Exception as error:
        print(f"Windows gave me no default speakers: {error}")
        return 1

    found = []

    def got(pcm: bytes, speaker: str) -> None:
        found.append(pcm)
        print(f"  heard a sentence of {len(pcm) / 2 / 16000:.1f} seconds")

    problems = []
    listener = loopback.Listener(loopback.SoundcardSource("speaker"), got, "them", on_error=problems.append)
    print(f"Listening for {LISTEN_SECONDS} seconds - play something with a voice now...")
    listener.start()
    time.sleep(LISTEN_SECONDS)
    listener.stop()
    listener.join(timeout=5)

    if problems:
        print("\nPROBLEM:", problems[0])
        return 1
    if not listener.heard_anything:
        print("\nI heard silence. Is the sound playing on the DEFAULT output? (Windows sound settings > Output)")
        return 1
    print(f"\nI can hear your speakers. {len(found)} sentence(s) were cut out.")
    if found:
        try:
            print("The first one says:", voice.transcribe(found[0]) or "(no words recognised)")
        except Exception as error:
            print(f"Turning it into text did not work yet: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
