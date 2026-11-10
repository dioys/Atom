"""make_manifest.py - writes manifest.json: a list of Atom's files with a fingerprint of each.

Atom checks this list when he starts, so if you copied only SOME of a round's files he tells you which ones
are still old. Whoever hands you a new round runs this last; you never need to.
(config.py is left out on purpose: you are allowed to change settings in it.)

    python make_manifest.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import version

HERE = Path(__file__).resolve().parent
SKIP = {"config.py"}                       # yours to edit
SKIP_PREFIXES = ("test_",)
MANIFEST = HERE / "manifest.json"
OPTIONAL = {"make_shortcut.py", "loopback_test.py"}  # tools, not needed to run


def fingerprint(path: Path) -> str:
    """Same answer on Windows and Linux: line endings are ignored."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()[:16]


def python_files(folder: Path = HERE) -> list[Path]:
    return sorted(
        p for p in folder.glob("*.py")
        if p.name not in SKIP and not p.name.startswith(SKIP_PREFIXES) and p.name != "manifest.py"
    )


def build(folder: Path = HERE) -> dict:
    names = [p for p in python_files(folder) if p.name != "make_manifest.py"]
    return {
        "version": version.VERSION,
        "files": {p.name: fingerprint(p) for p in names if p.name not in OPTIONAL},
        "optional": {p.name: fingerprint(p) for p in names if p.name in OPTIONAL},
    }


def write(folder: Path = HERE) -> dict:
    data = build(folder)
    (folder / "manifest.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


if __name__ == "__main__":
    info = write()
    print(f"manifest.json written: version {info['version']}, {len(info['files'])} files")
