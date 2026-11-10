"""backup.py - Step 9: save and restore everything Atom has learned about you.

A backup is one .zip of your Atom data folder (~/.atom): settings and keys, memory, the files you added,
your Spotify login. It sits in ~/.atom/backups (the newest 5 are kept) - copy one to a USB stick or cloud
drive if you want a safe copy off this computer. Treat it as private: it contains your API keys.

Restoring does not touch the files Atom is using right now. It unpacks the backup to a waiting folder and
Atom swaps it in the next time he starts (after saving a safety copy of what you had).
"""

from __future__ import annotations

import shutil
import sqlite3
import time
import zipfile
from datetime import datetime
from pathlib import Path

import config

KEEP = 5
SKIP_DIRS = {"backups", "restore_pending", "powerbi", "charts", "reports"}   # made again on demand, can be big
SKIP_NAMES = {"atom.log", "atom.log.1", ".write_test"}


def folder() -> Path:
    return config.DATA_DIR / "backups"


def pending() -> Path:
    return config.DATA_DIR / "restore_pending"


def _wanted(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if relative.parts[0] in SKIP_DIRS or path.name in SKIP_NAMES:
        return False
    return path.suffix not in {".wal", ".shm", ".journal"}


def _copy_database(source: Path, target: Path) -> None:
    """A safe copy of a SQLite file even while Atom is using it."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def create(root: Path | None = None, where: Path | None = None) -> Path:
    """Make a backup now and return its path."""
    root = root or config.DATA_DIR
    where = where or folder()
    where.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = where / f"atom-backup-{stamp}.zip"
    scratch = where / f".tmp-{stamp}"
    scratch.mkdir(exist_ok=True)
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or not _wanted(path, root):
                    continue
                arcname = path.relative_to(root).as_posix()
                source = path
                if path.suffix == ".db":
                    copy = scratch / path.name
                    try:
                        _copy_database(path, copy)
                        source = copy
                    except sqlite3.Error:
                        source = path           # not a real database file: store as it is
                bundle.write(source, arcname)
            bundle.writestr("BACKUP-INFO.txt", f"Atom backup made {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    _prune(where)
    return target


def list_backups(where: Path | None = None) -> list[Path]:
    where = where or folder()
    return sorted(where.glob("atom-backup-*.zip"), key=lambda p: p.name, reverse=True)


def latest(where: Path | None = None) -> Path | None:
    found = list_backups(where)
    return found[0] if found else None


def age_days(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 86400


def _prune(where: Path) -> None:
    for old in list_backups(where)[KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass


def is_backup(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as bundle:
            return "BACKUP-INFO.txt" in bundle.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def stage_restore(zip_path: Path, root: Path | None = None) -> int:
    """Unpack a backup to the waiting folder. Returns how many files. Raises ValueError if it isn't an Atom backup."""
    root = root or config.DATA_DIR
    if not is_backup(zip_path):
        raise ValueError("That isn't an Atom backup file.")
    wait = root / "restore_pending"
    shutil.rmtree(wait, ignore_errors=True)
    wait.mkdir(parents=True)
    count = 0
    with zipfile.ZipFile(zip_path) as bundle:
        for info in bundle.infolist():
            name = info.filename
            if info.is_dir() or name == "BACKUP-INFO.txt":
                continue
            target = (wait / name).resolve()
            if wait.resolve() not in target.parents:       # a name like ../../x must never escape
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count


def apply_pending(root: Path | None = None) -> str:
    """At start-up, before anything is opened: swap in a staged restore. Returns a message ('' if none)."""
    root = root or config.DATA_DIR
    wait = root / "restore_pending"
    if not wait.is_dir():
        return ""
    files = [p for p in wait.rglob("*") if p.is_file()]
    if not files:
        shutil.rmtree(wait, ignore_errors=True)
        return ""
    safety = create(root, root / "backups")                  # keep what you had, just in case
    for path in files:
        target = root / path.relative_to(wait)
        target.parent.mkdir(parents=True, exist_ok=True)
        for leftover in (target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")):
            leftover.unlink(missing_ok=True)
        shutil.copy2(path, target)
    shutil.rmtree(wait, ignore_errors=True)
    return f"Restored {len(files)} files from your backup. What you had before is saved as {safety.name}."
