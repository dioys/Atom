"""checkup.py - Step 9: "Check my setup". Looks at everything Atom depends on and says, in plain words,
what works, what is optional and missing, and what to do about it.

    python checkup.py          # prints the report in the terminal
    Settings > Check my setup  # same report inside Atom

Nothing here changes anything or sends anything out; it only looks.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import config

HERE = Path(__file__).resolve().parent
OK, WARN, BAD = "ok", "warn", "bad"
MARK = {OK: "OK  ", WARN: "NOTE", BAD: "FIX "}


@dataclass
class Check:
    name: str
    status: str          # ok / warn / bad
    detail: str
    fix: str = ""

    def line(self) -> str:
        text = f"[{MARK[self.status]}] {self.name}: {self.detail}"
        if self.fix and self.status != OK:
            text += f"\n         -> {self.fix}"
        return text


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


# ------------------------------------------------------------------ files
def file_problems(folder: Path | None = None) -> tuple[list[str], list[str], str]:
    """(missing files, files that differ from this version's list, version of the list).
    config.py is never compared: you may change settings in it."""
    folder = folder or HERE
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except OSError:
        return [], [], ""
    except ValueError:
        return [], [], "?"
    from make_manifest import fingerprint
    missing, differ = [], []
    for name, want in (manifest.get("files") or {}).items():
        target = folder / name
        if not target.is_file():
            missing.append(name)
        elif fingerprint(target) != want:
            differ.append(name)
    for name, want in (manifest.get("optional") or {}).items():
        target = folder / name
        if target.is_file() and fingerprint(target) != want:
            differ.append(name)
    return missing, differ, str(manifest.get("version", ""))


def check_files(folder: Path | None = None) -> Check:
    if getattr(sys, "frozen", False):
        return Check("Atom's files", WARN, "this is a packaged Atom.exe: it is a frozen COPY and does NOT get the new files you copy in",
                     "run  python make_shortcut.py  in the Atom folder and start Atom from that shortcut instead")
    import version
    missing, differ, listed = file_problems(folder)
    if not listed:
        return Check("Atom's files", WARN, "no manifest.json next to Atom, so I can't tell if every file is the newest",
                     "copy manifest.json from the newest round into the Atom folder")
    if listed == "?":
        return Check("Atom's files", WARN, "manifest.json is damaged", "copy manifest.json again from the newest round")
    if missing or differ:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if differ:
            parts.append("different from version " + listed + ": " + ", ".join(differ))
        return Check("Atom's files", BAD, "; ".join(parts),
                     "copy those files from the newest round over the ones in the Atom folder, then restart Atom")
    here = (folder or Path(__file__).resolve().parent)
    return Check("Atom's files", OK, f"all match version {listed} (running {version.VERSION} from {here})")


# --------------------------------------------------------------- the rest
def check_ai() -> Check:
    provider = config.get_provider()
    label = config.PROVIDERS[provider].get("label", provider)
    if config.get_api_key(provider):
        return Check("AI key", OK, f"{label} key is set ({config.get_model(provider)})")
    return Check("AI key", BAD, f"no key for {label}", "Settings > paste your key (Groq keys are free at console.groq.com)")


def check_spotify() -> Check:
    try:
        import spotify
        if spotify.connected():
            return Check("Spotify", OK, "connected")
        if spotify.client_id():
            return Check("Spotify", WARN, "Client ID saved but not connected yet", "Settings > Connect Spotify")
    except Exception as error:
        return Check("Spotify", WARN, f"couldn't check ({error})")
    return Check("Spotify", WARN, "not set up (optional - only needed for playing music)",
                 "Settings > Spotify: paste your Client ID, then Connect")


def check_mic() -> Check:
    try:
        from PySide6.QtMultimedia import QMediaDevices
        if QMediaDevices.defaultAudioInput().isNull():
            return Check("Microphone", BAD, "Windows reports no microphone", "plug one in or check Windows sound settings")
        return Check("Microphone", OK, "found: " + (QMediaDevices.defaultAudioInput().description() or "default"))
    except ImportError:
        return Check("Microphone", WARN, "Qt multimedia isn't installed", "python -m pip install --upgrade PySide6")
    except Exception as error:
        return Check("Microphone", WARN, f"couldn't check ({error})")


def check_voice() -> Check:
    mode = config.load_settings().get("voice_mode") or config.VOICE_MODE
    if mode == "boy":
        import kokovoice
        problem = kokovoice.problem()
        if problem:
            return Check("Voice", WARN, "boy voice is chosen but " + problem + " (until then Atom uses a Windows voice)")
        return Check("Voice", OK, "boy voice (Kokoro) is ready")
    return Check("Voice", OK, f"voice mode: {mode}")


def check_hotkey() -> Check:
    hotkey = config.load_settings().get("hotkey") or config.HOTKEY
    if not hotkey:
        return Check("Hotkey", OK, "turned off")
    if not sys.platform.startswith("win"):
        return Check("Hotkey", WARN, "the global hotkey only works on Windows")
    try:
        import hotkey as hk
        hk.parse_hotkey(hotkey)
    except Exception as error:
        return Check("Hotkey", BAD, f"'{hotkey}' isn't understood ({error})", "fix HOTKEY in config.py, e.g. ctrl+alt+space")
    return Check("Hotkey", OK, f"{hotkey.upper()} calls Atom")


def check_watcher() -> Check:
    if not config.WATCH_FILES:
        return Check("File watching", OK, "turned off in config.py")
    if _has("watchdog"):
        return Check("File watching", OK, "ready")
    return Check("File watching", WARN, "watchdog isn't installed, so Atom only notices changes every couple of minutes",
                 "python -m pip install watchdog")


def check_web() -> Check:
    if not config.WEB_SEARCH:
        return Check("Web search", OK, "turned off in config.py")
    if _has("ddgs"):
        return Check("Web search", OK, "ready")
    return Check("Web search", WARN, "the 'ddgs' add-on isn't installed", "python -m pip install ddgs")


def check_powerbi() -> Check:
    if not sys.platform.startswith("win"):
        return Check("Power BI", WARN, "Power BI Desktop only exists on Windows")
    try:
        import tools
        found = tools.find_powerbi()
    except Exception:
        found = None
    if not found:
        return Check("Power BI", WARN, "Power BI Desktop wasn't found (optional)", "install it from the Microsoft Store if you want Atom to build reports")
    import pbiauto
    if pbiauto.available():
        return Check("Power BI", OK, "installed, and Atom can press Refresh himself")
    return Check("Power BI", WARN, "installed, but Atom can't press Refresh himself yet", "python -m pip install pywinauto")


def check_daily() -> Check:
    if not getattr(config, "DAILY", True):
        return Check("Reminders and to-do list", OK, "turned off in config.py")
    try:
        import daily
        book = daily.Daily()
        text = f"{len(book.reminders())} reminder(s) waiting, {len(book.todos())} open to-do item(s)"
        book.close()
    except Exception as error:
        return Check("Reminders and to-do list", BAD, f"can't open daily.db ({error})", "check the .atom folder isn't read-only")
    return Check("Reminders and to-do list", OK, text)


def check_call() -> Check:
    """Step 13: can Atom hear a call and read the screen? (Both are optional.)"""
    if not getattr(config, "CALL_HELPER", True):
        return Check("Call helper", OK, "turned off in config.py")
    missing = [name for name, module in (("soundcard", "soundcard"), ("numpy", "numpy")) if not _has(module)]
    if missing:
        return Check("Call helper", WARN, "can't hear calls yet (needs " + " and ".join(missing) + ")",
                     "python -m pip install soundcard numpy")
    try:
        import soundcard as sc
        speaker = sc.default_speaker()
        sc.get_microphone(id=str(speaker.name), include_loopback=True)
    except Exception as error:
        return Check("Call helper", WARN, f"couldn't open the speaker's loopback ({type(error).__name__}: {str(error)[:80]})",
                     "run  python loopback_test.py  for details")
    notes = []
    if not (_has("PIL") and _has("pytesseract")):
        notes.append("screen reading needs: python -m pip install Pillow pytesseract")
    else:
        import screenreader
        if not (shutil.which("tesseract") or any(os.path.isfile(p) for p in screenreader._TESSERACT_PLACES if p)):
            notes.append("screen reading needs the Tesseract program (https://github.com/UB-Mannheim/tesseract/wiki)")
    if not config.get_api_key("groq"):
        notes.append("turning the call's voice into text needs a free Groq key (Settings)")
    if notes:
        return Check("Call helper", WARN, "can hear calls; " + "; ".join(notes), "see the notes above")
    return Check("Call helper", OK, "can hear the speakers' sound and read the screen")


def check_data() -> Check:
    folder = config.DATA_DIR
    try:
        probe = folder / ".write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return Check("Atom's data folder", BAD, f"can't write to {folder} ({error})", "check the folder isn't read-only")
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file() and "backups" not in f.parts) / 1_000_000
    return Check("Atom's data folder", OK, f"{folder} ({size:.1f} MB)")


def check_backup() -> Check:
    import backup
    last = backup.latest()
    if last is None:
        return Check("Backup", WARN, "no backup yet", "Settings > Back up now")
    age = backup.age_days(last)
    if age > 30:
        return Check("Backup", WARN, f"last backup is {age:.0f} days old", "Settings > Back up now")
    return Check("Backup", OK, f"last backup {last.name}")


ALL = (check_files, check_ai, check_spotify, check_mic, check_voice, check_hotkey,
       check_watcher, check_web, check_powerbi, check_daily, check_call, check_data, check_backup)


def run_all() -> list[Check]:
    results = []
    for fn in ALL:
        try:
            results.append(fn())
        except Exception as error:      # one broken check must not hide the others
            results.append(Check(fn.__name__.replace("check_", "").title(), WARN, f"couldn't check ({type(error).__name__}: {error})"))
    return results


def quick() -> list[Check]:
    """What Atom looks at every time he starts: only the things that stop him from working."""
    return [c for c in (_safe(check_files), _safe(check_ai)) if c and c.status == BAD]


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def startup_note(problems: list[Check]) -> str:
    """A short sentence for Atom to say, or '' when everything is fine."""
    if not problems:
        return ""
    first = problems[0]
    more = f" (and {len(problems) - 1} more - see Settings > Check my setup)" if len(problems) > 1 else ""
    return f"Heads up: {first.name} - {first.detail}. {first.fix}{more}"


def report(results: list[Check] | None = None) -> str:
    import version
    results = results if results is not None else run_all()
    bad = sum(c.status == BAD for c in results)
    warn = sum(c.status == WARN for c in results)
    head = f"Atom {version.VERSION} - {version.STEP}\n"
    if bad:
        head += f"{bad} thing(s) need fixing, {warn} optional.\n"
    elif warn:
        head += f"Everything needed works. {warn} optional thing(s) not set up.\n"
    else:
        head += "Everything works.\n"
    return head + "\n" + "\n".join(c.line() for c in results)


if __name__ == "__main__":
    print(report())
