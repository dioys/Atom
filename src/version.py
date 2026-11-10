"""version.py - which Atom this is. Shown in Settings > Check my setup and written at the top of atom.log.

Bump VERSION when you hand Atom a new round of files."""

import re

VERSION = "0.16.2"
STEP = "Step 16 - GitHub repo layout, CI/CD (Spotify wakes an idle app before playing)"


def as_tuple(text: str) -> tuple[int, ...]:
    """'0.12.0' -> (0, 12, 0)."""
    return tuple(int(n) for n in re.findall(r"\d+", str(text))[:3])


def hello() -> bytes:
    """What a newly started Atom tells an Atom that is already running."""
    return f"show|{VERSION}".encode()


def reply_to(message: bytes | str, own: str = VERSION) -> str:
    """The running Atom's answer to a newly started one:
    'replace' = the newcomer is a NEWER version, so I close and let it take over;
    'show'    = same or older version (or just a ping): I stay and come to the front;
    'ping'    = nothing to do (the newcomer only checks whether I am still alive)."""
    text = message.decode("utf-8", "ignore") if isinstance(message, bytes) else str(message)
    if text.startswith("ping"):
        return "ping"
    if text.startswith("show|") and as_tuple(text[5:]) > as_tuple(own):
        return "replace"
    return "show"