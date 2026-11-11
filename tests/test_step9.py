import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, json, sqlite3, tempfile, zipfile, shutil, threading
from pathlib import Path
sys.path.insert(0, SRC)
tmp = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(tmp)
import config
config.DATA_DIR = tmp / ".atom"; config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.SETTINGS_FILE = config.DATA_DIR / "settings.json"
import atomlog, backup, checkup, make_manifest, version

# ---- log
atomlog.use_file(config.DATA_DIR / "atom.log")
atomlog.log("hello"); atomlog.error("bad thing"); atomlog.tool_call("search_files", {"query": "x"*100}, "Error: boom", 1.234)
try: 1/0
except Exception as e: atomlog.exception("test", e)
t = atomlog.tail(50)
assert "hello" in t and "ERROR bad thing" in t and "ZeroDivisionError" in t and "WARN  tool search_files" in t, t
big = config.DATA_DIR / "atom.log"
big.write_text("x\n" * 300_000); atomlog.log("after"); assert (config.DATA_DIR / "atom.log.1").exists() and "after" in atomlog.tail(3)
# tee
import io
real = io.StringIO(); tee = atomlog._Tee(real, "info"); tee.write("[atom] couldn't save\nother noise\n"); assert "[atom] couldn't save" in atomlog.tail(5) and "other noise" not in atomlog.tail(5) and "other noise" in real.getvalue()
tee2 = atomlog._Tee(None, "info"); tee2.write("x\n"); tee2.flush()   # pythonw: no real stdout
# crash hook & thread hook
atomlog._installed = False
old_out, old_err, old_hook, old_thook = sys.stdout, sys.stderr, sys.excepthook, threading.excepthook
atomlog.install()
def boom(): raise RuntimeError("thread died")
th = threading.Thread(target=boom, name="worker"); th.start(); th.join()
assert "thread worker" in atomlog.tail(30) and "thread died" in atomlog.tail(30)
sys.stdout, sys.stderr, sys.excepthook, threading.excepthook = old_out, old_err, old_hook, old_thook

# ---- manifest + file check
folder = tmp / "app"; folder.mkdir()
for n, body in {"a.py": "x=1\n", "b.py": "y=2\n", "config.py": "z=3\n", "test_q.py": "t\n", "loopback_test.py": "m\n"}.items():
    (folder / n).write_bytes(body.encode())
data = make_manifest.write(folder)
assert set(data["files"]) == {"a.py", "b.py"} and set(data["optional"]) == {"loopback_test.py"}, data
assert checkup.file_problems(folder) == ([], [], version.VERSION)
(folder / "a.py").write_bytes(b"x=1\r\n")                    # CRLF only: must still match
assert checkup.file_problems(folder)[1] == []
(folder / "a.py").write_text("x=99\n"); (folder / "b.py").unlink(); (folder / "loopback_test.py").unlink()
miss, diff, ver = checkup.file_problems(folder)
assert miss == ["b.py"] and diff == ["a.py"], (miss, diff)
c = checkup.check_files(folder); assert c.status == "bad" and "b.py" in c.detail and "a.py" in c.detail
(folder / "manifest.json").unlink(); assert checkup.check_files(folder).status == "warn"
(folder / "manifest.json").write_text("{bad"); assert checkup.check_files(folder).status == "warn"
# the real folder's manifest matches itself
real_dir = Path(SRC); make_manifest.write(real_dir)
assert checkup.file_problems(real_dir)[:2] == ([], []), checkup.file_problems(real_dir)
assert checkup.check_files().status == "ok"

# ---- checks
config.save_settings({})
os.environ.pop("GROQ_API_KEY", None); os.environ.pop("GEMINI_API_KEY", None)
assert checkup.check_ai().status == "bad"
config.save_settings({"provider": "groq", "keys": {"groq": "gsk_x"}}); assert checkup.check_ai().status == "ok"
res = checkup.run_all()
assert len(res) == len(checkup.ALL) and all(r.status in ("ok", "warn", "bad") for r in res)
rep = checkup.report(res); assert version.VERSION in rep and "Atom's files" in rep
assert checkup.startup_note([]) == ""
n = checkup.startup_note([checkup.Check("AI key", "bad", "no key", "paste one"), checkup.Check("X", "bad", "y")]); assert "AI key" in n and "1 more" in n
orig = checkup.check_voice
checkup.ALL = tuple(f if f is not checkup.check_voice else (lambda: 1/0) for f in checkup.ALL)
assert any("couldn't check" in r.detail for r in checkup.run_all())

# ---- backup
root = config.DATA_DIR
(root / "settings.json").write_text('{"k":1}')
db = sqlite3.connect(root / "memory.db"); db.execute("create table t(a)"); db.execute("insert into t values (7)"); db.commit()   # left open, like Atom
(root / "library").mkdir(exist_ok=True); (root / "library" / "doc.txt").write_text("my doc")
(root / "charts").mkdir(exist_ok=True); (root / "charts" / "c.png").write_text("png")
made = backup.create()
names = zipfile.ZipFile(made).namelist()
assert "settings.json" in names and "memory.db" in names and "library/doc.txt" in names and "BACKUP-INFO.txt" in names, names
assert not any(n.startswith(("charts", "backups")) or n.startswith("atom.log") for n in names), names
assert backup.is_backup(made) and not backup.is_backup(root / "settings.json")
for i in range(7):
    z = made.with_name(f"atom-backup-2020010{i}-000000.zip"); shutil.copy(made, z)
backup.create(); assert len(backup.list_backups()) == backup.KEEP
# restore: change things, stage, apply
(root / "settings.json").write_text('{"k":2}'); db.execute("update t set a=8"); db.commit(); db.close()
(root / "library" / "doc.txt").write_text("changed")
n = backup.stage_restore(backup.latest()); assert n >= 3 and backup.pending().is_dir()
assert (root / "settings.json").read_text() == '{"k":2}'     # nothing touched until restart
msg = backup.apply_pending(); assert msg.startswith("Restored"), msg
assert (root / "settings.json").read_text() == '{"k":1}'
assert (root / "library" / "doc.txt").read_text() == "my doc"
assert sqlite3.connect(root / "memory.db").execute("select a from t").fetchone() == (7,)
assert any(p.name.startswith("atom-backup") for p in backup.list_backups())   # the safety copy
assert not backup.pending().exists() and backup.apply_pending() == ""

# traversal guard
evil = root / "evil.zip"
with zipfile.ZipFile(evil, "w") as z: z.writestr("BACKUP-INFO.txt", "x"); z.writestr("../../escaped.txt", "bad"); z.writestr("ok.txt", "fine")
backup.stage_restore(evil); assert not (root.parent / "escaped.txt").exists() and not (root / "escaped.txt").exists() and (backup.pending() / "ok.txt").exists()
shutil.rmtree(backup.pending())
try: backup.stage_restore(root / "settings.json"); raise SystemExit("should fail")
except ValueError: pass
