"""tools.py - things Atom can DO (no window code, no AI code in here).

Step 2: file library, text extraction, SQLite + FTS5 full-text search.
Step 3: ToolBox - the actions the AI can choose to use on its own
        (search files, read a file, open a file, open an app).
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import atomlog
import config
import memory as memory_module
import websearch
from memory import KINDS

# file extension -> friendly label shown in the file list
KINDS = {
    ".xlsx": "Excel", ".xlsm": "Excel", ".xls": "Excel",
    ".csv": "CSV", ".tsv": "CSV",
    ".docx": "Word", ".doc": "Word",
    ".pptx": "PowerPoint", ".ppt": "PowerPoint",
    ".pdf": "PDF",
    ".txt": "Text", ".md": "Text", ".rtf": "Text", ".log": "Text",
    ".png": "Image", ".jpg": "Image", ".jpeg": "Image", ".gif": "Image",
    ".webp": "Image", ".bmp": "Image", ".tif": "Image", ".tiff": "Image",
    ".py": "Code", ".js": "Code", ".ts": "Code", ".html": "Code",
    ".css": "Code", ".java": "Code", ".go": "Code", ".rs": "Code",
    ".json": "Data", ".xml": "Data", ".yaml": "Data", ".yml": "Data",
    ".zip": "Archive", ".7z": "Archive", ".rar": "Archive",
}


def kind_of(path: Path) -> str:
    return KINDS.get(path.suffix.lower(), "File")


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


BUILTIN_FOLDERS = ("Work", "Reports", "About me")   # Atom's own folders; you can add more
DEFAULT_FOLDER = "Work"
REPORTS_FOLDER = "Reports"
ABOUT_ME_FOLDER = "About me"                      # the files Atom answers questions about you from


@dataclass
class FileRecord:
    id: int
    path: str          # original path the user dropped
    library_path: str  # path inside ~/.atom/library/
    name: str
    size: int
    kind: str
    added: str         # ISO timestamp
    status: str        # "ready" | "empty" | "error"
    error: str         # extraction error message if any
    folder: str = "Work"   # which of your Atom folders it is filed in (Work, Reports, About me, ...)

    @property
    def exists(self) -> bool:
        return Path(self.library_path).is_file() or Path(self.path).is_file()

    @property
    def subtitle(self) -> str:
        text = f"{self.kind} · {human_size(self.size)}"
        if self.status == "error":
            return text + " · extract failed"
        if self.status == "empty":
            return text + " · no text"
        if not self.exists:
            return text + " · missing"
        return text


@dataclass
class SearchHit:
    file_id: int
    name: str
    kind: str
    chunk_index: int
    text: str
    score: float = 0.0


# ================================================================= extractors
def _safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extract_text(path: Path) -> str:
    """Return plain text extracted from a file. Empty string if nothing found."""
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md", ".log", ".csv", ".tsv", ".json", ".xml",
                      ".yaml", ".yml", ".py", ".js", ".ts", ".html", ".css",
                      ".java", ".go", ".rs", ".rtf"}:
            return _extract_plain(path)
        if suffix in {".xlsx", ".xlsm", ".xls"}:
            return _extract_excel(path)
        if suffix == ".docx":
            return _extract_docx(path)
        if suffix == ".pdf":
            return _extract_pdf(path)
        if suffix in {".pptx", ".ppt"}:
            return _extract_pptx(path)
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}:
            return _extract_image(path)
    except Exception as exc:
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    return ""


def _extract_plain(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-16", "latin-1", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_excel(path: Path) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        parts.append(f"=== Sheet: {sheet.title} ===")
        for row in sheet.iter_rows(values_only=True):
            cells = [_safe_text(c) for c in row if c is not None and _safe_text(c)]
            if cells:
                parts.append(" | ".join(cells))
    wb.close()
    return "\n".join(parts)


def _extract_docx(path: Path) -> str:
    from docx import Document
    doc = Document(path)
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    parts: list[str] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            parts.append(f"=== Page {i + 1} ===\n{text}")
    return "\n".join(parts)


def _extract_pptx(path: Path) -> str:
    from pptx import Presentation
    prs = Presentation(str(path))
    parts: list[str] = []
    for i, slide in enumerate(prs.slides, start=1):
        texts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = para.text.strip()
                    if t:
                        texts.append(t)
            if shape.has_table:
                table = shape.table
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        texts.append(" | ".join(cells))
        if texts:
            parts.append(f"=== Slide {i} ===\n" + "\n".join(texts))
    return "\n".join(parts)


def _extract_image(path: Path) -> str:
    """Optional OCR. Returns empty string if pytesseract is not installed."""
    try:
        import pytesseract  # type: ignore  (optional add-on, safe to be missing)
        from PIL import Image
        img = Image.open(path)
        text = pytesseract.image_to_string(img) or ""
        return text.strip()
    except Exception:
        return ""  # OCR is optional; image is still stored


def chunk_text(text: str, size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks. Prefer breaking at paragraph/newline."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            # try to break at a natural boundary
            window = text[start:end]
            for sep in ("\n\n", "\n", ". ", "; ", ", ", " "):
                pos = window.rfind(sep)
                if pos > size // 3:
                    end = start + pos + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


# ================================================================= FileStore
def _locked(method):
    """Only one thread at a time may touch the database. This lets files be read
    in the background while you keep chatting."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class FileStore:
    """Library of files Atom knows about. Stored in SQLite with FTS5 search."""

    def __init__(self, db_path: Path | None = None):
        self._lock = threading.RLock()
        self.db_path = Path(db_path) if db_path else config.FILES_DB
        self.library_dir = config.LIBRARY_DIR
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate_legacy_json()

    # ---------------------------------------------------------- schema
    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                path          TEXT NOT NULL,
                library_path  TEXT NOT NULL,
                name          TEXT NOT NULL,
                size          INTEGER NOT NULL DEFAULT 0,
                kind          TEXT NOT NULL DEFAULT 'File',
                added         TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'ready',
                error         TEXT NOT NULL DEFAULT '',
                content_hash  TEXT NOT NULL DEFAULT ''
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_files_path ON files(path);

            CREATE TABLE IF NOT EXISTS folders (name TEXT PRIMARY KEY);

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                file_id UNINDEXED,
                name UNINDEXED,
                kind UNINDEXED,
                chunk_index UNINDEXED,
                text,
                tokenize = 'porter unicode61'
            );
            """
        )
        columns = {row[1] for row in cur.execute("PRAGMA table_info(files)").fetchall()}
        if "folder" not in columns:                    # a library made before folders existed: everything starts in Work
            cur.execute(f"ALTER TABLE files ADD COLUMN folder TEXT NOT NULL DEFAULT '{DEFAULT_FOLDER}'")
        self._conn.commit()

    def _migrate_legacy_json(self) -> None:
        """One-time import from the old files.json if it still exists."""
        legacy = config.DATA_DIR / "files.json"
        if not legacy.is_file():
            return
        if len(self) > 0:
            return
        try:
            import json
            raw = json.loads(legacy.read_text(encoding="utf-8"))
            paths = [item["path"] for item in raw if "path" in item]
            if paths:
                self.add(paths)
            legacy.rename(legacy.with_suffix(".json.bak"))
        except Exception:
            pass

    # --------------------------------------------------------------- reading
    @_locked
    def all(self) -> list[FileRecord]:
        rows = self._conn.execute(
            "SELECT id, path, library_path, name, size, kind, added, status, error, folder "
            "FROM files ORDER BY id"
        ).fetchall()
        return [FileRecord(**dict(r)) for r in rows]

    @_locked
    def __len__(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()
        return int(row["n"]) if row else 0

    @_locked
    def get(self, file_id: int) -> FileRecord | None:
        row = self._conn.execute(
            "SELECT id, path, library_path, name, size, kind, added, status, error, folder "
            "FROM files WHERE id = ?",
            (file_id,),
        ).fetchone()
        return FileRecord(**dict(row)) if row else None

    # --------------------------------------------------------------- changes
    @_locked
    def _store_record(self, key, lib_path, name, size, kind, added_ts, status, error, content_hash, chunks, folder=DEFAULT_FOLDER) -> int:
        """Save one file and its text chunks (the quick database part of add)."""
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO files (path, library_path, name, size, kind, added, status, error, content_hash, folder) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, str(lib_path), name, size, kind, added_ts, status, error, content_hash, folder),
        )
        file_id = cur.lastrowid
        for i, chunk in enumerate(chunks):
            cur.execute(
                "INSERT INTO chunks (file_id, name, kind, chunk_index, text) VALUES (?, ?, ?, ?, ?)",
                (file_id, name, kind, i, chunk),
            )
        self._conn.commit()
        return file_id

    def add(self, paths: Iterable[str | Path], folder: str | None = None) -> tuple[list[FileRecord], list[str]]:
        """Add files (or whole folders). Copies into library, extracts, indexes. `folder` = which Atom folder to file them in."""
        folder = self.create_folder(folder) if folder else DEFAULT_FOLDER
        added: list[FileRecord] = []
        problems: list[str] = []
        known = {r.path for r in self.all()}

        for file_path in self._expand(paths, problems):
            if len(self) + len(added) >= config.MAX_FILES:
                problems.append(f"File limit reached ({config.MAX_FILES}).")
                break
            key = str(file_path)
            if key in known:
                problems.append(f"{file_path.name} is already in the list.")
                continue
            try:
                size = file_path.stat().st_size
            except OSError:
                problems.append(f"Could not read {file_path.name}.")
                continue

            # copy into library under a unique name
            content_hash = self._file_hash(file_path)
            lib_name = f"{content_hash[:12]}_{file_path.name}"
            lib_path = self.library_dir / lib_name
            try:
                if not lib_path.exists():
                    shutil.copy2(file_path, lib_path)
            except OSError as exc:
                problems.append(f"Could not copy {file_path.name}: {exc}")
                continue

            # extract + chunk
            status = "ready"
            error = ""
            chunks: list[str] = []
            try:
                text = extract_text(lib_path)
                if len(text) > config.MAX_EXTRACT_CHARS:
                    text = text[: config.MAX_EXTRACT_CHARS]
                chunks = chunk_text(text)
                if not chunks:
                    status = "empty"
            except Exception as exc:
                status = "error"
                error = str(exc)[:300]

            added_ts = datetime.now().isoformat(timespec="seconds")
            kind = kind_of(file_path)
            file_id = self._store_record(
                key, lib_path, file_path.name, size, kind, added_ts, status, error, content_hash, chunks, folder
            )

            record = FileRecord(
                id=file_id,
                path=key,
                library_path=str(lib_path),
                name=file_path.name,
                size=size,
                kind=kind,
                added=added_ts,
                status=status,
                error=error,
                folder=folder,
            )
            known.add(key)
            added.append(record)

        return added, problems

    # ---------------------------------------------------------- folders
    @_locked
    def folders(self) -> list[str]:
        """Folder names: Work, Reports, About me first, then the ones you made (or that hold files)."""
        extra = {row[0] for row in self._conn.execute("SELECT name FROM folders").fetchall()}
        extra |= {row[0] for row in self._conn.execute("SELECT DISTINCT folder FROM files").fetchall()}
        extra -= set(BUILTIN_FOLDERS)
        return list(BUILTIN_FOLDERS) + sorted(extra, key=str.lower)

    @_locked
    def folder_counts(self) -> dict[str, int]:
        counts = {name: 0 for name in self.folders()}
        for row in self._conn.execute("SELECT folder, COUNT(*) FROM files GROUP BY folder").fetchall():
            counts[row[0]] = row[1]
        return counts

    @_locked
    def create_folder(self, name: str) -> str:
        """Make a folder (nothing happens if it exists, in any capitalisation). Returns its proper name."""
        clean = re.sub(r"\s+", " ", str(name or "")).strip().strip("/\\")[:40]
        if not clean:
            raise ValueError("A folder needs a name.")
        for known in self.folders():
            if known.lower() == clean.lower():
                return known
        self._conn.execute("INSERT OR IGNORE INTO folders (name) VALUES (?)", (clean,))
        self._conn.commit()
        return clean

    @_locked
    def set_folder(self, paths: Iterable[str], folder: str) -> int:
        """File these files (by the path they were added with) in `folder`, which is made if new."""
        folder = self.create_folder(folder)
        targets = list({str(p) for p in paths})
        if not targets:
            return 0
        cur = self._conn.execute(
            "UPDATE files SET folder = ? WHERE path IN ({})".format(",".join("?" * len(targets))), (folder, *targets))
        self._conn.commit()
        return cur.rowcount

    @_locked
    def in_folder(self, folder: str) -> list[FileRecord]:
        return [r for r in self.all() if r.folder.lower() == str(folder or "").strip().lower()]

    @_locked
    def delete_folder(self, name: str) -> tuple[bool, str]:
        """Remove an empty folder you made. Work, Reports and About me stay."""
        if str(name).strip().lower() in {b.lower() for b in BUILTIN_FOLDERS}:
            return False, f"'{name}' is one of Atom's own folders and stays."
        if self.in_folder(name):
            return False, f"'{name}' still has files in it. Move them first."
        self._conn.execute("DELETE FROM folders WHERE name = ? COLLATE NOCASE", (str(name).strip(),))
        self._conn.commit()
        return True, f"Removed the folder '{name}'."

    def stale_paths(self) -> list[str]:
        """Original files that were edited since Atom copied them in."""
        stale = []
        for record in self.all():
            original, copy = Path(record.path), Path(record.library_path)
            try:
                now, then = original.stat(), copy.stat()
                with open(original, "rb") as handle:  # skip files another program has locked
                    handle.read(1)
            except OSError:
                continue  # the original moved/vanished or is busy: leave it alone
            if now.st_size != then.st_size or abs(now.st_mtime - then.st_mtime) > 2:
                stale.append(record.path)
        return stale

    def refresh_changed(self) -> list[str]:
        """Read again every file that was edited on disk. Returns their names."""
        stale = self.stale_paths()
        if not stale:
            return []
        self.remove(stale)
        added, _problems = self.add(stale)
        return [record.name for record in added]

    @_locked
    def remove(self, paths: Iterable[str]) -> int:
        targets = set(paths)
        if not targets:
            return 0
        rows = self._conn.execute(
            "SELECT id, library_path FROM files WHERE path IN ({})".format(
                ",".join("?" * len(targets))
            ),
            tuple(targets),
        ).fetchall()
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        for r in rows:
            try:
                Path(r["library_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self._conn.execute(
            "DELETE FROM chunks WHERE file_id IN ({})".format(",".join("?" * len(ids))),
            ids,
        )
        self._conn.execute(
            "DELETE FROM files WHERE id IN ({})".format(",".join("?" * len(ids))),
            ids,
        )
        self._conn.commit()
        return len(ids)

    @_locked
    def clear(self) -> None:
        rows = self._conn.execute("SELECT library_path FROM files").fetchall()
        for r in rows:
            try:
                Path(r["library_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self._conn.execute("DELETE FROM chunks")
        self._conn.execute("DELETE FROM files")
        self._conn.commit()

    # --------------------------------------------------------------- search
    @_locked
    def search(self, query: str, limit: int = config.MAX_SEARCH_HITS, folder: str | None = None) -> list[SearchHit]:
        """Full-text search across all indexed chunks (or only those of one folder). Returns best matching pieces."""
        only = ""
        params: tuple = ()
        if folder:
            only = " AND file_id IN (SELECT id FROM files WHERE folder = ? COLLATE NOCASE)"
            params = (folder,)
        query = (query or "").strip()
        if not query:
            return []
        # FTS5 query: turn free text into AND of terms, keep quoted phrases
        fts_query = self._to_fts_query(query)
        if not fts_query:
            return []
        try:
            rows = self._conn.execute(
                """
                SELECT file_id, name, kind, chunk_index, text,
                       bm25(chunks) AS score
                FROM chunks
                WHERE chunks MATCH ?""" + only + """
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, *params, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # fallback: simple LIKE if FTS query is invalid
            like = f"%{query}%"
            rows = self._conn.execute(
                """
                SELECT file_id, name, kind, chunk_index, text, 0.0 AS score
                FROM chunks
                WHERE text LIKE ?""" + only + """
                LIMIT ?
                """,
                (like, *params, limit),
            ).fetchall()
        return [
            SearchHit(
                file_id=r["file_id"],
                name=r["name"],
                kind=r["kind"],
                chunk_index=r["chunk_index"],
                text=r["text"],
                score=float(r["score"] or 0),
            )
            for r in rows
        ]

    def context_for(self, query: str) -> str:
        """Build a short context block of relevant file excerpts for the brain."""
        hits = self.search(query, limit=config.MAX_SEARCH_HITS)
        if not hits:
            # if nothing matched, still give a short list of available files
            return self.describe()
        parts: list[str] = ["Relevant excerpts from your files:"]
        total = 0
        for h in hits:
            snippet = h.text.strip()
            if len(snippet) > 900:
                snippet = snippet[:900] + "…"
            block = f"\n--- {h.name} ({h.kind}, part {h.chunk_index + 1}) ---\n{snippet}"
            if total + len(block) > config.MAX_CONTEXT_CHARS:
                break
            parts.append(block)
            total += len(block)
        return "\n".join(parts)

    @_locked
    def chunks_of(self, file_id: int, limit: int = 3) -> list[str]:
        """The first `limit` pieces of text of one file (in reading order)."""
        rows = self._conn.execute(
            "SELECT text FROM chunks WHERE file_id = ? ORDER BY chunk_index LIMIT ?", (file_id, int(limit))
        ).fetchall()
        return [r["text"] for r in rows]

    def describe(self, folder: str | None = None) -> str:
        """Plain-text summary of the file list (used when no search hits). With several folders in use, grouped by folder."""
        records = self.in_folder(folder) if folder else self.all()
        if not records:
            return f"There are no files in the folder '{folder}'." if folder else "The user has not added any files yet."
        used = list(dict.fromkeys(r.folder for r in records))
        lines = []
        for name in used:
            if len(used) > 1:
                lines.append(f"{name}:")
            for r in (r for r in records if r.folder == name):
                extra = ""
                if r.status == "error":
                    extra = " [extract failed]"
                elif r.status == "empty":
                    extra = " [no searchable text]"
                lines.append(f"- {r.name} ({r.kind}, {human_size(r.size)}){extra}")
        head = f"Files in the folder '{folder}':" if folder else "Files the user has added:"
        return head + "\n" + "\n".join(lines)

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _file_hash(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
        return h.hexdigest()

    @staticmethod
    def _to_fts_query(text: str) -> str:
        """Turn free text into a safe FTS5 query (OR of tokens + phrases).

        OR is used so a question like "what is overdue and sales trend"
        still matches documents that contain only some of the words.
        """
        # keep quoted phrases
        phrases = re.findall(r'"([^"]+)"', text)
        rest = re.sub(r'"[^"]*"', " ", text)
        tokens = re.findall(r"[a-zA-Z0-9_]{2,}", rest)
        parts = [f'"{p}"' for p in phrases if p.strip()]
        parts += tokens
        # drop pure stop-ish noise
        noise = {
            "the", "and", "for", "what", "whats", "about", "from", "this",
            "that", "with", "have", "file", "files", "report", "on", "in",
            "is", "are", "can", "you", "tell", "me", "please", "how", "does",
            "any", "some", "just", "into", "over",
        }
        parts = [p for p in parts if p.lower().strip('"') not in noise]
        parts = parts[:12]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return " OR ".join(parts)

    @staticmethod
    def _expand(paths: Iterable[str | Path], problems: list[str]) -> list[Path]:
        """Turn dropped paths into a flat list of real files (folders are walked)."""
        files: list[Path] = []
        for raw in paths:
            p = Path(raw)
            try:
                p = p.resolve()
            except OSError:
                problems.append(f"Could not open {p.name}.")
                continue
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                found = 0
                for child in sorted(p.rglob("*")):
                    if not child.is_file():
                        continue
                    if any(part.startswith(".") for part in child.relative_to(p).parts):
                        continue  # skip hidden files and hidden folders
                    files.append(child)
                    found += 1
                    if found >= config.MAX_FILES_PER_FOLDER:
                        problems.append(
                            f"Folder {p.name}: only the first "
                            f"{config.MAX_FILES_PER_FOLDER} files were added."
                        )
                        break
            else:
                problems.append(f"{p.name} was not found.")
        return files


# ===================================================================== Step 3
# Atom may only open apps on this list. Format: key -> (label, Windows command,
# macOS app name, Linux command). To let Atom open another app, add a line.
APPS = {
    "excel": ("Excel", "excel", "Microsoft Excel", "libreoffice"),
    "word": ("Word", "winword", "Microsoft Word", "libreoffice"),
    "powerpoint": ("PowerPoint", "powerpnt", "Microsoft PowerPoint", "libreoffice"),
    "outlook": ("Outlook", "outlook", "Microsoft Outlook", "thunderbird"),
    "notepad": ("Notepad", "notepad", "TextEdit", "gedit"),
    "calculator": ("Calculator", "calc", "Calculator", "gnome-calculator"),
    "paint": ("Paint", "mspaint", "Preview", "gimp"),
    "file explorer": ("File Explorer", "explorer", "Finder", "xdg-open"),
    "chrome": ("Google Chrome", "chrome", "Google Chrome", "google-chrome"),
    "edge": ("Microsoft Edge", "msedge", "Microsoft Edge", "microsoft-edge"),
    "firefox": ("Firefox", "firefox", "Firefox", "firefox"),
    "vs code": ("VS Code", "code", "Visual Studio Code", "code"),
    # Power BI Desktop has no simple start name, so _launch_app looks for it (see find_powerbi). To use another
    # location, add  "power bi": "C:\\path\\PBIDesktop.exe"  to "apps" in ~/.atom/settings.json
    "power bi": ("Power BI", "pbidesktop", "Power BI Desktop", "pbidesktop"),
    # "name:" below is a link Windows hands to the installed app, so it works
    # for both the Microsoft Store and the normal installer versions
    "spotify": ("Spotify", "spotify:", "Spotify", "spotify"),
    "discord": ("Discord", "discord:", "Discord", "discord"),
    "teams": ("Microsoft Teams", "msteams:", "Microsoft Teams", "teams"),
    "slack": ("Slack", "slack:", "Slack", "slack"),
}

# other names people use -> key in APPS
APP_ALIASES = {
    "microsoft excel": "excel", "ms excel": "excel", "spreadsheet": "excel",
    "microsoft word": "word", "ms word": "word",
    "ppt": "powerpoint", "microsoft powerpoint": "powerpoint", "ms powerpoint": "powerpoint",
    "microsoft outlook": "outlook", "email": "outlook", "mail": "outlook",
    "calc": "calculator", "notes": "notepad",
    "explorer": "file explorer", "files": "file explorer", "finder": "file explorer",
    "google chrome": "chrome", "browser": "chrome",
    "microsoft edge": "edge",
    "vscode": "vs code", "visual studio code": "vs code", "code": "vs code",
    "powerbi": "power bi", "power bi desktop": "power bi", "pbi": "power bi", "microsoft power bi": "power bi",
}

# Atom never opens these kinds of files, even if you added them: opening
# them could RUN a program instead of just showing a document.
BLOCKED_SUFFIXES = {
    ".exe", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".msi", ".msc", ".scr", ".lnk", ".pif", ".reg", ".hta",
    ".jar", ".py", ".pyw", ".sh",
}


def all_apps() -> dict:
    """The built-in APPS plus any you added yourself in ~/.atom/settings.json:

        "apps": { "figma": "figma:", "my editor": "C:\\\\Tools\\\\editor.exe" }

    The value is a program path or a link like spotify: . Only you can add
    apps this way (the AI cannot), so Atom still can't be talked into running
    something you didn't approve.
    """
    apps = dict(APPS)
    extra = config.load_settings().get("apps")
    if isinstance(extra, dict):
        for name, command in extra.items():
            if isinstance(name, str) and isinstance(command, str) and name.strip() and command.strip():
                command = command.strip()
                apps[name.strip().lower()] = (name.strip().title(), command, command, command)
    return apps


def resolve_app(name: str) -> str | None:
    """Turn what the AI (or you) said, like 'Microsoft Excel', into a key of all_apps()."""
    key = (name or "").strip().lower()
    key = APP_ALIASES.get(key, key)
    return key if key in all_apps() else None


def _open_path(path: Path) -> None:
    """Open a file with the program Windows (or macOS/Linux) normally uses for it."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606 - only files from the user's own list
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _open_uri(uri: str) -> None:
    """Hand a link like spotify:search:... to the app that handles it."""
    if sys.platform.startswith("win"):
        os.startfile(uri)  # noqa: S606 - Atom only builds spotify: links itself
    elif sys.platform == "darwin":
        subprocess.Popen(["open", uri])
    else:
        subprocess.Popen(["xdg-open", uri])


POWERBI_STORE_APP = r"shell:AppsFolder\Microsoft.MicrosoftPowerBIDesktop_8wekyb3d8bbwe!Microsoft.MicrosoftPowerBIDesktop"


def _appx_installed() -> bool:
    """Is the Microsoft Store version of Power BI Desktop installed? (Windows only; asks PowerShell, takes ~1 second.)"""
    if not sys.platform.startswith("win"):
        return False
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-AppxPackage -Name Microsoft.MicrosoftPowerBIDesktop | Select-Object -First 1).Name"],
            capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "PowerBI" in (done.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return False


def _registered_powerbi() -> str | None:
    """The path Windows has on record for PBIDesktop.exe (installer versions), if any."""
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PBIDesktop.exe") as key:
                value = winreg.QueryValue(key, None)
                if value and Path(value).exists():
                    return value
        except OSError:
            continue
    return None


def find_powerbi() -> str | None:
    """How to start Power BI Desktop on this PC: a program path, or the Store app's link. None = not installed."""
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
    candidates = [Path(r) / "Microsoft Power BI Desktop" / "bin" / "PBIDesktop.exe" for r in roots if r]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Microsoft" / "WindowsApps" / "PBIDesktopStore.exe")
    found = next((str(p) for p in candidates if p.exists()), None)
    found = found or shutil.which("PBIDesktop.exe") or shutil.which("PBIDesktopStore.exe") or _registered_powerbi()
    if found:
        return found
    return POWERBI_STORE_APP if _appx_installed() else None


def _launch_app(key: str) -> None:
    """Start one of the apps in all_apps()."""
    _label, windows_cmd, mac_app, linux_cmd = all_apps()[key]
    if key == "power bi" and windows_cmd == APPS["power bi"][1]:      # not changed by the user: find it ourselves
        if not sys.platform.startswith("win"):
            raise RuntimeError("Power BI Desktop only runs on Windows")
        found = find_powerbi()
        if not found:
            raise RuntimeError(
                "I can't find Power BI Desktop on this PC. It is free in the Microsoft Store (search 'Power BI Desktop'); "
                "if it is installed, add its path under \"apps\" in ~/.atom/settings.json as \"power bi\""
            )
        windows_cmd = found
    if sys.platform.startswith("win"):
        # "start" finds apps that are registered with Windows (Excel, Chrome, ...)
        subprocess.Popen(
            ["cmd", "/c", "start", "", windows_cmd],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", mac_app])
    else:
        exe = shutil.which(linux_cmd)
        if not exe:
            raise RuntimeError(f"{linux_cmd} is not installed")
        subprocess.Popen([exe])


class ToolBox:
    """What the AI is allowed to do. The AI asks for a tool by name; this class
    runs it and returns plain text for the AI to read.

    Tools that change something on your computer (opening a file or an app)
    first call `confirm(question)`, which shows you a Yes/No box. If you say
    no, nothing happens and the AI is told you refused.
    """

    SPECS = [
        {
            "name": "search_files",
            "description": (
                "Search the text inside the files the user added. Use it when the "
                "excerpts already given are not enough, or for a different topic."
            ),
            "properties": {
                "query": {"type": "string", "description": "Words to look for"},
                "folder": {"type": "string", "description": "Only look in this folder (Work, Reports, About me, or one the user made). Leave empty for all."},
            },
            "required": ["query"],
        },
        {
            "name": "list_files",
            "description": "List the files the user has added to Atom, grouped by their folders (Work, Reports, About me, ...).",
            "properties": {"folder": {"type": "string", "description": "Only this folder (optional)"}},
            "required": [],
        },
        {
            "name": "organize_files",
            "description": (
                "Organise the user's files into folders. action 'folders' shows the folders and how many files are in each; "
                "'create' makes a folder; 'move' files the named files in a folder (it is made if new); 'delete' removes an empty "
                "folder the user made. Atom's own folders are Work, Reports and About me. 'About me' holds the files that describe the "
                "user (CV, certificates); Atom answers questions about the user from them. Files stay where they are on the computer; "
                "only Atom's list is organised."
            ),
            "properties": {
                "action": {"type": "string", "enum": ["folders", "create", "move", "delete"], "description": "What to do"},
                "folder": {"type": "string", "description": "The folder (for create, move, delete)"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "File names to move (part of a name is enough)"},
            },
            "required": ["action"],
        },
        {
            "name": "read_file",
            "description": (
                "Read the text of one added file (start of the file). Use it for "
                "summaries or when you need more than a search excerpt."
            ),
            "properties": {"name": {"type": "string", "description": "File name, e.g. budget.xlsx"}},
            "required": ["name"],
        },
        {
            "name": "table_summary",
            "description": (
                "Get real, counted numbers about an Excel or CSV file: row counts, how "
                "many items per status, totals, date ranges, and which items are past "
                "due and not done. Use this for status reports instead of guessing."
            ),
            "properties": {"name": {"type": "string", "description": "File name, e.g. tasks.xlsx"}},
            "required": ["name"],
        },
        {
            "name": "data_aggregate",
            "description": (
                "Calculate from an Excel/CSV file: total, average, count, min, max or "
                "median of a column, overall or grouped by a category column, or by "
                "year/quarter/month/week of a date column. Use split='year' with "
                "period='month' to compare years month by month. Gives exact numbers "
                "and the change between groups. Call table_summary first if you "
                "do not know the column names."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "value": {"type": "string", "description": "Column to calculate, e.g. Sales"},
                "by": {"type": "string", "description": "Column to group by (category or date); leave empty for one overall number"},
                "how": {"type": "string", "enum": ["sum", "mean", "count", "min", "max", "median"]},
                "period": {"type": "string", "enum": ["year", "quarter", "month", "week", "day"], "description": "Only when 'by' is a date column"},
                "split": {"type": "string", "description": "Second grouping column, or 'year' to compare years"},
                "sheet": {"type": "string", "description": "Sheet name if not the first"},
                "filter_column": {"type": "string"},
                "filter_value": {"type": "string", "description": "Keep only rows where filter_column equals this"},
            },
            "required": ["name", "value"],
        },
        {
            "name": "data_stats",
            "description": (
                "Statistics for an Excel/CSV file: mean, median, spread, min, max, "
                "outliers, missing values and which number columns move together."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "columns": {"type": "string", "description": "Comma-separated columns; empty = all number columns"},
                "sheet": {"type": "string"},
                "filter_column": {"type": "string"},
                "filter_value": {"type": "string"},
            },
            "required": ["name"],
        },
        {
            "name": "data_pivot",
            "description": (
                "Pivot table / cross-tab of an Excel/CSV file: one column down the side, optionally another "
                "across the top, with totals and optional percent shares. Set save=true only if the user "
                "wants it in Excel (gets a real Excel chart)."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "rows": {"type": "string", "description": "Column down the side (category or date)"},
                "columns": {"type": "string", "description": "Column across the top (optional)"},
                "value": {"type": "string", "description": "Number column to calculate (not needed for count)"},
                "how": {"type": "string", "enum": ["sum", "mean", "count", "min", "max", "median"]},
                "period": {"type": "string", "enum": ["year", "quarter", "month", "week", "day"], "description": "Only when rows is a date column"},
                "percent": {"type": "boolean", "description": "Show each cell as percent of the grand total"},
                "save": {"type": "boolean"},
                "sheet": {"type": "string"},
                "filter_column": {"type": "string"},
                "filter_value": {"type": "string"},
            },
            "required": ["name", "rows"],
        },
        {
            "name": "data_trend",
            "description": (
                "Trend over time from a date column: growth per period, vs a year ago, best/weakest period, "
                "straight-line trend and a simple forecast of the next periods. Call table_summary first if "
                "you don't know the column names."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "value": {"type": "string", "description": "Number column, e.g. Sales"},
                "date": {"type": "string", "description": "Date column (found automatically if empty)"},
                "period": {"type": "string", "enum": ["year", "quarter", "month", "week", "day"]},
                "how": {"type": "string", "enum": ["sum", "mean", "count", "min", "max", "median"]},
                "forecast": {"type": "integer", "description": "How many periods to forecast (0 = none)"},
                "sheet": {"type": "string"},
                "filter_column": {"type": "string"},
                "filter_value": {"type": "string"},
            },
            "required": ["name", "value"],
        },
        {
            "name": "data_relate",
            "description": (
                "Regression: how much column y changes when column x changes, strength of the link, "
                "and optional predictions for given x values."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "x": {"type": "string", "description": "The column that explains (e.g. Ad spend)"},
                "y": {"type": "string", "description": "The column explained (e.g. Sales)"},
                "at": {"type": "string", "description": "Optional x values to predict y for, comma separated"},
                "sheet": {"type": "string"},
                "filter_column": {"type": "string"},
                "filter_value": {"type": "string"},
            },
            "required": ["name", "x", "y"],
        },
        {
            "name": "data_compare",
            "description": (
                "Compare two Excel/CSV files, or two sheets of one workbook: columns added/removed, totals "
                "before vs after, and with a key column (ID, name) which rows are new, removed or changed."
            ),
            "properties": {
                "name": {"type": "string", "description": "First (older) file"},
                "name2": {"type": "string", "description": "Second (newer) file; same file name for two sheets"},
                "key": {"type": "string", "description": "Column that identifies a row, e.g. ID"},
                "key2": {"type": "string", "description": "Its name in the second file if different"},
                "sheet": {"type": "string"},
                "sheet2": {"type": "string"},
            },
            "required": ["name", "name2"],
        },
        {
            "name": "data_cleanup",
            "description": (
                "Check a spreadsheet for messy data: numbers stored as text, mixed date styles, extra spaces, "
                "N/A placeholders, misspelled or duplicate categories, duplicate rows. save=true also writes a "
                "cleaned COPY (the original is never changed)."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "save": {"type": "boolean", "description": "Also make a cleaned copy"},
                "sheet": {"type": "string"},
            },
            "required": ["name"],
        },
        {
            "name": "data_join",
            "description": (
                "Combine two Excel/CSV files into one new file by matching a shared column (like VLOOKUP). "
                "how: inner = only matches, left = everything from the first file, outer = everything."
            ),
            "properties": {
                "name": {"type": "string", "description": "First file (keeps all its rows when how=left)"},
                "name2": {"type": "string", "description": "Second file"},
                "key": {"type": "string", "description": "Shared column in the first file"},
                "key2": {"type": "string", "description": "Its name in the second file if different"},
                "how": {"type": "string", "enum": ["inner", "left", "outer"]},
                "sheet": {"type": "string"},
                "sheet2": {"type": "string"},
            },
            "required": ["name", "name2", "key"],
        },
        {
            "name": "reminder",
            "description": (
                "Set, list or cancel reminders. For add: text = what to remind about, when = the time exactly as "
                "the user said it ('in 20 minutes', 'tomorrow 9am', 'friday 3pm', 'every monday 9am'). "
                "Atom speaks up at that time."
            ),
            "properties": {
                "action": {"type": "string", "enum": ["add", "list", "cancel", "snooze"]},
                "text": {"type": "string", "description": "What to remind (add), or the words/number of the reminder to cancel or snooze (empty = the one that just rang)"},
                "when": {"type": "string", "description": "When, in the user's own words; for snooze how long, e.g. '15 minutes'"},
                "repeat": {"type": "string", "enum": ["none", "daily", "weekdays", "weekly", "monthly"]},
            },
            "required": ["action"],
        },
        {
            "name": "todo",
            "description": (
                "The user's to-do list: add an item, list the open items, mark one done, remove one or clear the "
                "finished ones. For done/remove, text = a few words of the item or its number."
            ),
            "properties": {
                "action": {"type": "string", "enum": ["add", "list", "done", "remove", "clear_done"]},
                "text": {"type": "string", "description": "The item (add) or which item (done/remove)"},
                "due": {"type": "string", "description": "Optional due date in the user's words, e.g. friday"},
            },
            "required": ["action"],
        },
        {
            "name": "briefing",
            "description": "Today's briefing: reminders for today, the open to-do items and what is overdue. Use when asked for a morning briefing, agenda or 'what's on today'.",
            "properties": {},
            "required": [],
        },
        {
            "name": "read_screen",
            "description": (
                "Look at what is on the user's screen right now and return the text on it. Use when the user asks what is on "
                "the screen, to read or explain something they are looking at (a question, code, an error, a slide, a chat). "
                "The text is read by OCR and may have mistakes; it may include Atom's own window."
            ),
            "properties": {
                "focus": {"type": "string", "description": "Optional: what to look for in it (only used to label the answer)"},
            },
            "required": [],
        },
        {
            "name": "profile",
            "description": (
                "The user's own skills memory: skills, experience, projects, education, strengths, and files that describe them "
                "(a CV, a skills list) from any folder. Actions: show (list it), add (text, kind), remove (text), "
                "use_file (file: a file name Atom has, or a full path), drop_file (file), learn (read the profile files and "
                "save the skills and experience in them). Use when the user talks about THEIR skills, CV or background."
            ),
            "properties": {
                "action": {"type": "string", "enum": ["show", "add", "remove", "use_file", "drop_file", "learn"]},
                "text": {"type": "string", "description": "What to add or remove, e.g. 'Python, SQL and Power BI'"},
                "kind": {"type": "string", "enum": ["skill", "experience", "project", "education", "strength", "about"]},
                "file": {"type": "string", "description": "File name or full path (use_file / drop_file)"},
            },
            "required": ["action"],
        },
        {
            "name": "call_notes",
            "description": (
                "What happened on the user's last call or interview: the things the other person asked the user to do (tasks), "
                "a summary, or the transcript. Actions: tasks (default), summary, transcript, done (mark a task done by number "
                "or words), add_todo (copy the call's open tasks to the user's to-do list)."
            ),
            "properties": {
                "action": {"type": "string", "enum": ["tasks", "summary", "transcript", "done", "add_todo"]},
                "which": {"type": "string", "description": "For done: the task number or a few of its words"},
            },
            "required": [],
        },
        {
            "name": "make_chart",
            "description": (
                "Draw a chart from an Excel/CSV file and open it as a picture. "
                "bar/line/pie: x = category or date column, y = number column, how = "
                "how to combine (sum, mean, count...). scatter: x and y are number "
                "columns. hist: x is a number column."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "kind": {"type": "string", "enum": ["bar", "line", "pie", "scatter", "hist"]},
                "x": {"type": "string"},
                "y": {"type": "string"},
                "how": {"type": "string", "enum": ["sum", "mean", "count", "min", "max", "median"]},
                "period": {"type": "string", "enum": ["year", "quarter", "month", "week", "day"]},
                "split": {"type": "string", "description": "One series per value, or 'year' to compare years"},
                "title": {"type": "string"},
                "sheet": {"type": "string"},
                "filter_column": {"type": "string"},
                "filter_value": {"type": "string"},
            },
            "required": ["name", "kind", "x"],
        },
        {
            "name": "save_report",
            "description": (
                "Save a finished report as a Word document and open it for the user. "
                "Write the content with lines starting '# ' or '## ' for headings, "
                "'- ' for bullets and **bold** for emphasis."
            ),
            "properties": {
                "title": {"type": "string", "description": "Report title, e.g. 'Project status report'"},
                "content": {"type": "string", "description": "The full report text"},
            },
            "required": ["title", "content"],
        },
        {
            "name": "open_file",
            "description": (
                "Open one of the added files in its normal program (Excel, Word, ...). "
                "The user is asked to confirm first."
            ),
            "properties": {"name": {"type": "string", "description": "File name, e.g. budget.xlsx"}},
            "required": ["name"],
        },
        {
            "name": "play_music",
            "description": (
                "Play music on Spotify: finds the best match and starts playing it. "
                "If Spotify is not connected in Settings, it only opens the search "
                "results and the user must press play."
            ),
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to play: the song title only (e.g. 'ilomilo'), or an "
                        "artist, album or playlist name (e.g. 'Taylor Swift', 'lofi beats')"
                    ),
                },
                "artist": {
                    "type": "string",
                    "description": "For one specific song: the singer or band (e.g. 'Billie Eilish')",
                },
                "kind": {
                    "type": "string",
                    "enum": ["track", "artist", "album", "playlist"],
                    "description": "artist = singer/band, track = one song, playlist = mood or genre mix",
                },
            },
            "required": ["query"],
        },
        {
            "name": "music_control",
            "description": "Pause, resume, skip to the next song or go back to the previous song on Spotify.",
            "properties": {
                "action": {"type": "string", "enum": ["pause", "resume", "next", "previous"]}
            },
            "required": ["action"],
        },
        {
            "name": "open_app",
            "description": (
                "Open a desktop app for the user. The user is asked to confirm first."
            ),
            "properties": {
                "app": {"type": "string", "enum": list(APPS), "description": "Which app"}
            },
            "required": ["app"],
        },
        {
            "name": "remember",
            "description": (
                "Save a short note about the user for future sessions: a project, "
                "a deadline (include the date) or a preference. Never passwords."
            ),
            "properties": {
                "note": {"type": "string", "description": "One short sentence"},
                "kind": {"type": "string", "enum": list(KINDS), "description": "Type of note"},
            },
            "required": ["note"],
        },
        {
            "name": "forget",
            "description": "Delete saved notes about a topic, or everything Atom remembers.",
            "properties": {
                "what": {
                    "type": "string",
                    "description": "Words from the note(s) to delete, or 'everything'",
                }
            },
            "required": ["what"],
        },
        {
            "name": "make_dashboard",
            "description": (
                "Draw a one-page dashboard picture (big number cards + up to 4 charts) from an Excel/CSV file and "
                "open it. Leave kpis and charts empty and Atom picks a good layout from the columns. To choose: "
                "kpis = 'sum:Sales, mean:Profit, count:' ; charts = 'bar,Region,Sales,sum; line,Date,Sales,sum,month; "
                "pie,Category,Sales' (kind,x,y,how,period,split)."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "title": {"type": "string", "description": "Dashboard title"},
                "kpis": {"type": "string", "description": "Optional, e.g. 'sum:Sales, mean:Profit'"},
                "charts": {"type": "string", "description": "Optional, semicolon-separated chart specs"},
                "sheet": {"type": "string"},
                "filter_column": {"type": "string"},
                "filter_value": {"type": "string"},
            },
            "required": ["name"],
        },
        {
            "name": "build_powerbi_report",
            "description": (
                "Build a finished Power BI report by yourself and open it in Power BI Desktop: a dark page with a "
                "title, a filter box, number cards and charts, plus a Data page. Use it when the user wants a Power "
                "BI report, dashboard or graph made in Power BI. Leave kpis and charts empty unless the user names "
                "them (same format as make_dashboard)."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name (Excel or CSV)"},
                "title": {"type": "string", "description": "Optional report title"},
                "kpis": {"type": "string", "description": "Optional, e.g. 'sum:Sales, mean:Profit'"},
                "charts": {"type": "string", "description": "Optional, semicolon-separated chart specs, e.g. 'bar,Region,Sales,sum; line,Date,Sales,sum'"},
                "sheet": {"type": "string"},
                "filter_column": {"type": "string"},
                "filter_value": {"type": "string"},
            },
            "required": ["name"],
        },
        {
            "name": "export_powerbi",
            "description": (
                "Prepare an Excel/CSV file for Microsoft Power BI: saves a clean Excel file Power BI loads in one "
                "click, a how-to with suggested visuals and measures, and a Power BI colour theme, then opens the "
                "folder. Only use it when the user wants the plain files; build_powerbi_report builds the whole report."
            ),
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "sheet": {"type": "string"},
            },
            "required": ["name"],
        },
        {
            "name": "web_search",
            "description": (
                "Check a fact on the internet. Use it for anything about the outside world (people, places, "
                "events, prices, dates, news, 'is it true that...') and whenever you are not sure. Search with a "
                "few plain words. Never put file contents, private file names, passwords or personal details "
                "in the search."
            ),
            "properties": {"query": {"type": "string", "description": "A few plain search words"}},
            "required": ["query"],
        },
        {
            "name": "recall",
            "description": "Search saved notes and earlier conversations for a topic.",
            "properties": {
                "query": {"type": "string", "description": "Topic words; empty for the latest messages"}
            },
            "required": [],
        },
    ]

    def __init__(self, store: FileStore, confirm=None, memory=None, daily=None, profile=None, calls=None):
        self.store = store
        self.profile = profile  # userprofile.Profile (your skills and CV files), set by Brain
        self.calls = calls      # callmode.CallLog (calls and what was asked of you), set by Brain
        self.screen_reader = None  # function() -> screenreader.ScreenResult; None = read the screen directly
        self.confirm = confirm  # function(question: str) -> bool, set per reply
        self.memory = memory    # memory.Memory, set by Brain (None = no memory)
        self.daily = daily      # daily.Daily (reminders and the to-do list), set by Brain
        self.web_engine = None  # search function(query, count) -> list of results; None = DuckDuckGo

    # ------------------------------------------------ descriptions for the AI
    def _schema(self, spec: dict) -> dict:
        return {
            "type": "object",
            "properties": spec["properties"],
            "required": spec["required"],
        }

    def _specs(self) -> list[dict]:
        """SPECS, with the open_app list refreshed (it can include your own apps)."""
        specs = []
        for spec in self.SPECS:
            if spec["name"] == "open_app":
                spec = dict(spec, properties={
                    "app": {"type": "string", "enum": list(all_apps()), "description": "Which app"}
                })
            specs.append(spec)
        return specs

    # Each request to the AI carries every tool's description, and free plans only
    # allow a small number of tokens per minute. So Atom sends just the tools that
    # fit your message. Words that switch a group on:
    TOOL_GROUPS = {
        "core": (None, ["search_files", "list_files", "read_file", "web_search"]),
        "open": (
            {"open", "launch", "excel", "word", "powerpoint", "outlook", "notepad", "calculator",
             "chrome", "edge", "firefox", "code", "discord", "teams", "slack", "paint", "explorer"},
            ["open_file", "open_app"],
        ),
        "music": (
            {"play", "pause", "resume", "skip", "next", "previous", "song", "songs", "music", "spotify",
             "track", "playlist", "album", "artist", "band", "listen", "stop"},
            ["play_music", "music_control", "open_app"],
        ),
        "report": (
            {"report", "status", "summary", "summarize", "summarise", "overview", "progress", "update",
             "weekly", "monthly", "overdue", "late", "deadline", "deadlines", "tasks", "task"},
            ["table_summary", "save_report"],
        ),
        "data": (
            {"total", "totals", "sum", "average", "mean", "median", "count", "compare", "comparison",
             "versus", "vs", "trend", "trends", "growth", "percent", "percentage", "statistic",
             "statistics", "stats", "correlation", "chart", "graph", "plot", "pie", "bar", "line",
             "histogram", "scatter", "distribution", "outlier", "outliers", "highest", "lowest",
             "biggest", "most", "least", "year", "years", "month", "months", "quarter", "sales",
             "revenue", "profit", "cost", "budget", "calculate", "analyze", "analyse", "analysis"},
            ["table_summary", "data_aggregate", "data_stats", "make_chart"],
        ),
        "pivot": (
            {"pivot", "pivots", "crosstab", "cross", "breakdown", "matrix"},
            ["table_summary", "data_pivot"],
        ),
        "trend": (
            {"trend", "trends", "forecast", "predict", "prediction", "projection", "project", "growth", "grow",
             "growing", "regression", "relationship", "relate", "related", "correlate", "correlation", "effect",
             "impact", "driver", "drivers"},
            ["table_summary", "data_trend", "data_relate"],
        ),
        "clean": (
            {"clean", "cleanup", "messy", "duplicate", "duplicates", "quality", "issues", "problems",
             "mistakes", "typos", "consistent"},
            ["table_summary", "data_cleanup"],
        ),
        "combine": (
            {"compare", "comparison", "join", "merge", "combine", "difference", "differences", "changed",
             "versus", "vs", "lookup", "vlookup"},
            ["table_summary", "data_compare", "data_join"],
        ),
        "daily": (
            {"remind", "reminder", "reminders", "alarm", "todo", "todos", "checklist", "briefing", "brief",
             "agenda", "tomorrow", "tonight", "schedule", "snooze", "wake"},
            ["reminder", "todo", "briefing"],
        ),
        "dashboard": (
            {"dashboard", "dashboards", "kpi", "kpis", "overview", "visual", "visuals", "powerbi", "power", "bi",
             "pbi", "export"},
            ["table_summary", "make_dashboard", "build_powerbi_report", "export_powerbi", "open_app"],
        ),
        "screen": (
            {"screen", "screenshot", "screenshots", "monitor", "onscreen"},
            ["read_screen"],
        ),
        "folders": (
            {"folder", "folders", "organize", "organise", "organizing", "organising", "move", "categorize", "categorise", "sort", "group"},
            ["organize_files", "list_files"],
        ),
        "profile": (
            {"skill", "skills", "cv", "resume", "résumé", "profile", "strengths", "strength", "experience", "background",
             "qualifications", "certificate", "certificates", "education", "yourself", "myself"},
            ["profile", "read_file"],
        ),
        "call": (
            {"call", "calls", "interview", "interviewer", "caller", "meeting", "meetings", "transcript"},
            ["call_notes", "todo"],
        ),
        "memory": (
            {"remember", "forget", "forgot", "note", "notes", "memory", "memorize", "recall", "remind",
             "reminder", "yesterday", "earlier", "before", "told", "prefer", "preference", "always",
             "never", "deadline", "deadlines", "project", "projects", "talked", "discussed", "last"},
            ["remember", "forget", "recall"],
        ),
    }

    def pick(self, text: str) -> list[str]:
        """Names of the tools worth sending for this message."""
        words = set(re.findall(r"[a-z]+", (text or "").lower()))
        years = bool(re.search(r"\b(19|20)\d\d\b", text or ""))
        names: list[str] = []
        for group, (triggers, members) in self.TOOL_GROUPS.items():
            hit = triggers is None or bool(words & triggers) or (group == "data" and years)
            if group == "daily" and re.search(r"\bto[- ]?do\b|\bwhat'?s on (today|my plate)\b|\bmy day\b", (text or "").lower()):
                hit = True
            if hit:
                names.extend(n for n in members if n not in names)
        return names

    def claude_tools(self, names: list[str] | None = None) -> list[dict]:
        return [
            {"name": s["name"], "description": s["description"], "input_schema": self._schema(s)}
            for s in self._specs()
            if names is None or s["name"] in names
        ]

    def openai_tools(self, names: list[str] | None = None) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s["description"],
                    "parameters": self._schema(s),
                },
            }
            for s in self._specs()
            if names is None or s["name"] in names
        ]

    def status_for(self, name: str, args: dict) -> str:
        """Short line shown in Atom's bubble while a tool runs."""
        args = args if isinstance(args, dict) else {}
        if name == "search_files":
            return "Searching your files..."
        if name == "list_files":
            return "Looking at your file list..."
        if name == "organize_files":
            return "Sorting your files..."
        if name == "read_file":
            return f"Reading {args.get('name') or 'a file'}..."
        if name == "open_file":
            return f"Opening {args.get('name') or 'a file'}..."
        if name == "table_summary":
            return f"Counting the rows in {args.get('name') or 'a spreadsheet'}..."
        if name == "save_report":
            return "Writing your report..."
        if name == "data_aggregate":
            return f"Calculating {args.get('value') or 'the numbers'}..."
        if name == "data_stats":
            return "Working out the statistics..."
        if name == "data_pivot":
            return "Building your pivot table..."
        if name == "data_trend":
            return "Looking at the trend..."
        if name == "data_relate":
            return "Checking how they relate..."
        if name == "data_compare":
            return "Comparing the two files..."
        if name == "data_cleanup":
            return "Checking the data for mess..."
        if name == "data_join":
            return "Joining the files..."
        if name == "reminder":
            return "Setting that reminder..."
        if name == "todo":
            return "Updating your list..."
        if name == "briefing":
            return "Pulling your day together..."
        if name == "make_chart":
            return "Drawing your chart..."
        if name == "make_dashboard":
            return "Building your dashboard..."
        if name == "build_powerbi_report":
            return "Designing your Power BI report..."
        if name == "export_powerbi":
            return "Getting your data ready for Power BI..."
        if name == "open_app":
            return f"Opening {args.get('app') or 'an app'}..."
        if name == "play_music":
            return f"Finding {args.get('query') or 'music'} in Spotify..."
        if name == "music_control":
            return f"Spotify: {args.get('action') or 'working'}..."
        if name == "remember":
            return "Saving that..."
        if name == "forget":
            return "Forgetting that..."
        if name == "recall":
            return "Thinking back..."
        if name == "web_search":
            return "Checking that online..."
        return "Working on it..."

    # ----------------------------------------------------------------- run
    def run(self, name: str, args: dict) -> str:
        args = args if isinstance(args, dict) else {}
        if name not in {s["name"] for s in self.SPECS}:
            return f"Error: there is no tool called '{name}'."
        started = time.monotonic()
        try:
            result = getattr(self, f"_tool_{name}")(args)
        except Exception as exc:  # never let a tool crash the chat
            atomlog.exception(f"tool {name}", exc)
            return f"Error: {type(exc).__name__}: {exc}"
        atomlog.tool_call(name, args, result, time.monotonic() - started)
        return result

    # --------------------------------------------------------------- helpers
    def _allowed(self, question: str) -> bool:
        if not config.CONFIRM_ACTIONS:
            return True
        if self.confirm is None:
            return False
        return bool(self.confirm(question))

    def _find(self, name: str) -> tuple[FileRecord | None, str]:
        """Find one added file by (part of) its name. Returns (record, error)."""
        needle = (name or "").strip().lower()
        records = self.store.all()
        matches = [r for r in records if r.name.lower() == needle]
        if not matches and needle:
            matches = [r for r in records if needle in r.name.lower()]
        if not matches:
            return None, f"No added file matches '{name}'. Use list_files to see what exists."
        if len(matches) > 1:
            names = ", ".join(r.name for r in matches[:8])
            return None, f"More than one file matches: {names}. Ask the user which one."
        return matches[0], ""

    # ----------------------------------------------------------------- tools
    def _tool_search_files(self, args: dict) -> str:
        folder = str(args.get("folder") or "").strip() or None
        hits = self.store.search(str(args.get("query", "")), limit=6, folder=folder)
        if not hits:
            return f"No matches in the folder '{folder}'." if folder else "No matches in the added files."
        parts, total = [], 0
        for hit in hits:
            block = f"--- {hit.name} (part {hit.chunk_index + 1}) ---\n{hit.text.strip()[:900]}"
            if total + len(block) > config.MAX_CONTEXT_CHARS * 2:
                break
            parts.append(block)
            total += len(block)
        return "\n".join(parts)

    def _tool_list_files(self, args: dict) -> str:
        return self.store.describe(str(args.get("folder") or "").strip() or None)

    def _tool_organize_files(self, args: dict) -> str:
        action = str(args.get("action") or "folders").strip().lower()
        folder = str(args.get("folder") or "").strip()
        store = self.store
        if action == "folders":
            counts = store.folder_counts()
            return "Folders:\n" + "\n".join(f"- {name}: {counts.get(name, 0)} file(s)" for name in store.folders())
        if action == "create":
            if not folder:
                return "Which name should the folder have?"
            return f"The folder '{store.create_folder(folder)}' is ready."
        if action == "delete":
            return store.delete_folder(folder)[1]
        if action == "move":
            names = args.get("files") or []
            names = [names] if isinstance(names, str) else list(names)
            if not folder or not names:
                return "Tell me which files and which folder."
            moved, problems = [], []
            for name in names:
                needle = str(name).strip().lower()
                records = store.all()
                found = [r for r in records if r.name.lower() == needle] or [r for r in records if needle and needle in r.name.lower()]
                if len(found) == 1:
                    store.set_folder([found[0].path], folder)
                    moved.append(found[0].name)
                elif found:
                    problems.append(f"'{name}' matches more than one file ({', '.join(r.name for r in found[:4])})")
                else:
                    problems.append(f"I have no file called '{name}'")
            target = store.create_folder(folder)
            text = f"Moved {', '.join(moved)} to {target}." if moved else "Nothing was moved."
            return text + ((" Problems: " + "; ".join(problems) + ".") if problems else "")
        return "I can show the folders, create one, move files into one, or delete an empty one."

    def _tool_read_file(self, args: dict) -> str:
        record, error = self._find(str(args.get("name", "")))
        if error:
            return error
        text = extract_text(Path(record.library_path)).strip()
        if not text:
            return f"{record.name} has no readable text."
        limit = config.MAX_READ_CHARS
        if len(text) > limit:
            return text[:limit] + f"\n[cut off: showing the first {limit} of {len(text)} characters]"
        return text

    def _tool_table_summary(self, args: dict) -> str:
        import reports

        record, error = self._find(str(args.get("name", "")))
        if error:
            return error
        try:
            return reports.summarize_table(Path(record.library_path))
        except ValueError as problem:
            return str(problem)

    def _analysis(self, args: dict, action):
        """Shared by the three analyst tools: find the file, run, explain problems."""
        import analysis

        record, error = self._find(str(args.get("name", "")))
        if error:
            return error
        options = {k: v for k, v in args.items() if k != "name"}
        try:
            return action(analysis, Path(record.library_path), options)
        except ValueError as problem:  # e.g. unknown column: the message says what to fix
            return f"Could not do that: {problem}"

    def _tool_data_aggregate(self, args: dict) -> str:
        return self._analysis(args, lambda m, path, o: m.run_aggregate(path, **o))

    def _tool_data_stats(self, args: dict) -> str:
        return self._analysis(args, lambda m, path, o: m.run_stats(path, **o))

    # ---- Step 11 daily helper (daily.py)
    def _daily(self):
        if self.daily is None:
            import daily
            self.daily = daily.Daily()
        return self.daily

    def _tool_reminder(self, args: dict) -> str:
        import timeparse

        book = self._daily()
        action = str(args.get("action") or "add").strip().lower()
        try:
            if action == "list":
                return book.reminders_text()
            if action == "snooze":
                now = datetime.now()
                span = str(args.get("when", "")).strip() or "10 minutes"
                target = timeparse.parse_when(span, now)
                minutes = max(1, round((target - now).total_seconds() / 60)) if target and target > now else 10
                item = book.snooze(str(args.get("text", "")), minutes, now)
                return f"Snoozed: '{item.text}' will ring again {timeparse.nice(item.due, now)}."
            if action in ("cancel", "delete", "remove", "done"):
                gone = book.cancel_reminder(str(args.get("text", "")))
                return f"Cancelled reminder #{gone.id}: {gone.text}"
            when_text, repeat = timeparse.split_repeat(str(args.get("when", "")))
            given = str(args.get("repeat") or "").strip().lower()
            repeat = given if given in ("daily", "weekdays", "weekly", "monthly") else repeat
            if not when_text.strip():
                return "Could not do that: I need a time. Ask the user when, like 'tomorrow 9am' or 'in 20 minutes'."
            now = datetime.now()
            due = timeparse.parse_when(when_text, now)
            if due is None:
                return (f"Could not do that: I couldn't understand the time '{args.get('when')}'. Ask the user for it "
                        "again, like 'tomorrow 9am', 'friday 3pm' or 'in 20 minutes'.")
            if due <= now:
                return f"Could not do that: {timeparse.nice(due, now)} has already passed (it is {now:%I:%M %p}). Ask for a later time."
            item = book.add_reminder(str(args.get("text", "")), due, repeat)
        except ValueError as problem:
            return f"Could not do that: {problem}"
        again = f", repeating {item.repeat}" if item.repeat else ""
        return (f"Reminder set (#{item.id}): '{item.text}' for {timeparse.nice(item.due, now)}{again}. "
                "Atom will speak up then if he is running.")

    def _tool_todo(self, args: dict) -> str:
        import timeparse

        book = self._daily()
        action = str(args.get("action") or "list").strip().lower()
        text = str(args.get("text", ""))
        try:
            if action == "list":
                return book.todos_text()
            if action == "add":
                due = None
                if str(args.get("due", "")).strip():
                    when = timeparse.parse_when(str(args["due"]), datetime.now())
                    if when is None:
                        return f"Could not do that: I couldn't understand the due date '{args['due']}'."
                    due = when.date()
                item, existed = book.add_todo(text, due)
                tail = f" (due {due:%a %d %b})" if due else ""
                return (f"That is already on the list (#{item.id})." if existed else f"Added to the list (#{item.id}): {item.text}{tail}.") \
                    + f" {len(book.todos())} open item(s) now."
            if action in ("done", "finish", "complete"):
                item = book.complete_todo(text)
                return f"Ticked off (#{item.id}): {item.text}. {len(book.todos())} open item(s) left."
            if action in ("remove", "delete"):
                item = book.remove_todo(text)
                return f"Removed (#{item.id}): {item.text}."
            if action == "clear_done":
                return f"Cleared {book.clear_done()} finished item(s)."
        except ValueError as problem:
            return f"Could not do that: {problem}"
        return "Could not do that: action must be add, list, done, remove or clear_done."

    # ------------------------------------------------------- step 13: screen, profile, calls
    def _tool_read_screen(self, args: dict) -> str:
        import screenreader

        result = (self.screen_reader or screenreader.read_screen)()
        if not result.ok:
            return f"Could not do that: {result.error}"
        focus = str(args.get("focus") or "").strip()
        head = "Text read from the screen" + (f" (looking for: {focus})" if focus else "") + \
               (" by an AI that sees the picture" if result.method == "vision" else " by OCR (may contain mistakes)") + ":\n"
        return head + result.text

    def _tool_profile(self, args: dict) -> str:
        book = self.profile
        if book is None:
            return "Could not do that: the skills profile is turned off (PROFILE = False in config.py)."
        action = str(args.get("action") or "show").strip().lower()
        text = str(args.get("text") or "")
        try:
            if action == "show":
                return book.overview()
            if action == "add":
                kind = str(args.get("kind") or "skill")
                added = book.add_many(text, kind)
                if not added:
                    return "Those are already in the profile."
                return f"Added to your profile ({kind}): " + "; ".join(added) + "."
            if action == "remove":
                count = book.remove(text)
                return f"Removed {count} item(s) from your profile." if count else f"Nothing in your profile matches '{text}'."
            if action in ("use_file", "pin", "add_file"):
                ok, message = book.pin(str(args.get("file") or text))
                return message if ok else f"Could not do that: {message}"
            if action in ("drop_file", "unpin"):
                ok, message = book.unpin(str(args.get("file") or text))
                return message if ok else f"Could not do that: {message}"
            if action == "learn":
                if not book.pinned():
                    return "Could not do that: no profile files yet. Use action use_file first."
                count = book.learn_from_files()
                return f"Read your profile files and saved {count} new fact(s).\n" + book.overview()
        except (ValueError, RuntimeError) as problem:
            return f"Could not do that: {problem}"
        return "Could not do that: action must be show, add, remove, use_file, drop_file or learn."

    def _tool_call_notes(self, args: dict) -> str:
        log = self.calls
        if log is None:
            return "Could not do that: the call helper is turned off (CALL_HELPER = False in config.py)."
        call_id = log.last_call_id()
        if call_id is None:
            return "There is no call on record yet. Open the call helper (Ctrl+Shift+C) and press Start before the call."
        action = str(args.get("action") or "tasks").strip().lower()
        if action == "tasks":
            return log.tasks_text(call_id)
        if action == "summary":
            call = log.call(call_id) or {}
            return call.get("summary") or "That call has no summary yet (it is written when the call ends)."
        if action == "transcript":
            lines = log.lines(call_id)
            text = "\n".join(f"{'Them' if who == 'them' else 'Me'}: {line}" for who, line in lines)
            return text[-4000:] or "Nothing was said on that call that I heard."
        if action == "done":
            task, error = log.find_task(call_id, str(args.get("which") or ""))
            if task is None:
                return f"Could not do that: {error}"
            log.set_done(task[0])
            return f"Ticked off: {task[1]}"
        if action == "add_todo":
            book = self._daily()
            open_tasks = log.tasks(call_id, include_done=False)
            if not open_tasks:
                return "There are no open tasks from that call."
            for _, text, _ in open_tasks:
                book.add_todo(text)
            return f"Added {len(open_tasks)} task(s) from the call to your to-do list."
        return "Could not do that: action must be tasks, summary, transcript, done or add_todo."

    def _tool_briefing(self, args: dict) -> str:
        return self._daily().briefing()

    # ---- Step 10 analyst tools (analyst.py)
    def _analyst(self, args: dict, action, second: bool = False):
        """Find one or two added files, run an analyst.py function, explain problems in plain words."""
        import analyst

        record, error = self._find(str(args.get("name", "")))
        if error:
            return error
        options = {k: v for k, v in args.items() if k not in ("name", "name2")}
        try:
            if second:
                other, error = self._find(str(args.get("name2", "")))
                if error:
                    return error
                return action(analyst, Path(record.library_path), Path(other.library_path), options)
            return action(analyst, Path(record.library_path), options)
        except ValueError as problem:
            return f"Could not do that: {problem}"

    def _keep_new_file(self, path: Path) -> str:
        """Open a file Atom just made and add it to the library so he can analyse it next."""
        try:
            _open_path(path)
            shown = "It is open on the user's screen."
        except Exception:
            shown = "I couldn't open it automatically."
        try:
            added, _ = self.store.add([path], folder=REPORTS_FOLDER)
            known = f" It is added to the file list (folder {REPORTS_FOLDER}) as {added[0].name}, so you can ask about it." if added else ""
        except Exception:
            known = ""
        return f"Saved {path.name} in {path.parent}. {shown}{known}"

    def _tool_data_pivot(self, args: dict) -> str:
        def run(m, path, o):
            text, saved = m.run_pivot(path, **o)
            if saved is None:
                return text
            try:
                _open_path(saved)
                shown = "It is open on the user's screen."
            except Exception:
                shown = "I couldn't open it automatically."
            return f"{text}\nSaved as {saved.name} in {saved.parent} (with an Excel chart). {shown}"

        return self._analyst(args, run)

    def _tool_data_trend(self, args: dict) -> str:
        return self._analyst(args, lambda m, path, o: m.run_trend(path, **o))

    def _tool_data_relate(self, args: dict) -> str:
        return self._analyst(args, lambda m, path, o: m.run_relate(path, **o))

    def _tool_data_compare(self, args: dict) -> str:
        return self._analyst(args, lambda m, a, b, o: m.run_compare(a, b, **o), second=True)

    def _tool_data_cleanup(self, args: dict) -> str:
        def run(m, path, o):
            text, saved = m.run_cleanup(path, **o)
            return text if saved is None else f"{text}\n{self._keep_new_file(saved)}"

        return self._analyst(args, run)

    def _tool_data_join(self, args: dict) -> str:
        def run(m, a, b, o):
            text, saved = m.run_join(a, b, **o)
            return f"{text}\n{self._keep_new_file(saved)}"

        return self._analyst(args, run, second=True)

    def _tool_make_chart(self, args: dict) -> str:
        def draw(m, path, options):
            png, summary = m.run_chart(path, **options)
            try:
                _open_path(png)
                shown = "It is open on the user's screen."
            except Exception:
                shown = "I couldn't open it automatically."
            return f"{summary}\nChart saved as {png.name} in {png.parent}. {shown}"

        return self._analysis(args, draw)

    def _tool_make_dashboard(self, args: dict) -> str:
        def build(m, path, options):
            png, text = m.run_dashboard(path, **options)
            try:
                _open_path(png)
                shown = "It is open on the user's screen."
            except Exception:
                shown = "I couldn't open it automatically."
            return f"{text}\nDashboard saved as {png.name} in {png.parent}. {shown}"

        return self._analysis(args, build)

    def _tool_build_powerbi_report(self, args: dict) -> str:
        def build(m, path, options):
            info = m.run_build_powerbi(path, **options)
            opened = ""
            try:
                _open_path(info["pbip"])
                opened = "Power BI Desktop is opening the report on the user's screen (it can take a minute)."
                import pbiauto

                if pbiauto.start_refresh(info["pbip"].stem) is not None:
                    opened += " I am pressing Power BI's Refresh button for them as soon as it opens, so the data loads by itself."
                else:
                    opened += (" Power BI needs one click on Refresh (Home tab) to load the data; to make Atom do that "
                               "himself the user can run: pip install pywinauto.")
            except Exception:
                try:
                    _open_path(info["folder"])
                    opened = "I couldn't start Power BI myself, so I opened the folder: double-click the .pbip file."
                except Exception:
                    opened = "I couldn't open it automatically."
            return (
                f"Built the Power BI report \"{info['title']}\" from {info['rows']:,} rows. It has: "
                + "; ".join(info["drawn"]) + f".\nFiles are in {info['folder']} (open {info['pbip'].name}). {opened} "
                "Tell the user in a sentence or two what it shows. If Power BI shows an error, ask them to read it "
                "out; the data is safe in the .csv file next to the report."
            )

        return self._analysis(args, build)

    def _tool_export_powerbi(self, args: dict) -> str:
        def export(m, path, options):
            info = m.run_export_powerbi(path, **options)
            try:
                _open_path(info["folder"])
                shown = "The folder is open on the user's screen."
            except Exception:
                shown = "I couldn't open the folder automatically."
            return (
                f"Saved {info['rows']:,} clean rows ({len(info['columns'])} columns) for Power BI.\n"
                f"Files in {info['folder']}:\n- {info['xlsx'].name} (load this in Power BI Desktop: Get data > Excel workbook)\n"
                f"- {info['howto'].name} (steps, suggested visuals and measures)\n- {info['theme'].name} "
                f"(dark theme: View > Themes > Browse for themes)\n{shown} "
                "Tell the user these three steps in a sentence or two; open_app can start Power BI Desktop."
            )

        return self._analysis(args, export)

    def _tool_save_report(self, args: dict) -> str:
        import reports

        content = str(args.get("content", "")).strip()
        if not content:
            return "Error: the report was empty."
        path = reports.write_report(str(args.get("title", "Report")), content)
        try:
            _open_path(path)
            opened = " and opened it"
        except Exception:  # e.g. Word is not installed
            opened = ", but I couldn't open it automatically"
        return f"Saved the report as {path.name}{opened}. It is in the folder {path.parent}."

    def _tool_open_file(self, args: dict) -> str:
        record, error = self._find(str(args.get("name", "")))
        if error:
            return error
        original = Path(record.path)
        target = original if original.is_file() else Path(record.library_path)
        if not target.is_file():
            return f"{record.name} is no longer on disk."
        if target.suffix.lower() in BLOCKED_SUFFIXES:
            return f"For safety I never open {target.suffix} files."
        if not self._allowed(f"Open the file \"{record.name}\"?"):
            return "The user said no, so nothing was opened."
        _open_path(target)
        return f"Opened {record.name}."

    def _tool_play_music(self, args: dict) -> str:
        import spotify  # imported here so Atom still starts if this file is missing

        query = " ".join(str(args.get("query", "")).split())[:100]
        if not query:
            return "Error: no song or artist was given."
        if spotify.connected():
            # you asked for music, so no Yes/No box (unless you turn it on in config.py)
            if config.CONFIRM_MUSIC and not self._allowed(f"Play \"{query}\" on Spotify?"):
                return "The user said no, so nothing was played."
            try:
                return spotify.play(
                    query,
                    str(args.get("kind", "track")),
                    launch=lambda: _launch_app("spotify"),
                    artist=str(args.get("artist", "")),
                    open_uri=_open_uri,
                )
            except spotify.SpotifyError as error:
                return f"Could not play: {error}"
        # not connected: fall back to opening Spotify's search page
        if not self._allowed(f"Open Spotify and search for \"{query}\"?"):
            return "The user said no, so nothing was opened."
        _open_uri("spotify:search:" + quote(query, safe=""))
        return (
            f"Spotify is open on the search results for '{query}', but I can't press play "
            "because Spotify is not connected. The user must press play, or connect "
            "Spotify in Settings so I can play music myself."
        )

    def _tool_music_control(self, args: dict) -> str:
        import spotify

        if not spotify.connected():
            return "Spotify is not connected. The user can connect it in Settings."
        try:
            return spotify.control(str(args.get("action", "")))
        except spotify.SpotifyError as error:
            return f"Could not do that: {error}"

    def _tool_remember(self, args: dict) -> str:
        if self.memory is None:
            return "Error: memory is turned off."
        note = str(args.get("note", "")).strip()
        if not note:
            return "Error: there was nothing to save."
        if memory_module.looks_secret(note):
            return "Not saved: I never keep passwords, PINs or card numbers."
        is_new, saved = self.memory.add_note(note, str(args.get("kind", "fact")))
        return f"Saved: {saved}" if is_new else f"Saved (I already knew that): {saved}"

    def _tool_forget(self, args: dict) -> str:
        if self.memory is None:
            return "Error: memory is turned off."
        what = str(args.get("what", "")).strip()
        if what.lower() in {"everything", "all", "all notes", "all of it", "everything you know"}:
            notes, chats = self.memory.clear_notes(), self.memory.clear_messages()
            return f"Forgot everything: {notes} notes and {chats} saved messages deleted."
        count = self.memory.forget(what)
        return f"Forgot {count} note{'s' if count != 1 else ''}." if count else "No saved note matches that."

    def _tool_web_search(self, args: dict) -> str:
        if not config.WEB_SEARCH:
            return "Web search is turned off, so say that you could not check it online."
        return websearch.search_text(str(args.get("query", "")), engine=self.web_engine)

    def _tool_recall(self, args: dict) -> str:
        if self.memory is None:
            return "Error: memory is turned off."
        return self.memory.recall(str(args.get("query", "")))

    def _tool_open_app(self, args: dict) -> str:
        key = resolve_app(str(args.get("app", "")))
        if key is None:
            names = ", ".join(all_apps())
            return f"I can only open these apps: {names}."
        label = all_apps()[key][0]
        if not self._allowed(f"Open {label}?"):
            return "The user said no, so nothing was opened."
        _launch_app(key)
        return f"Opened {label}."