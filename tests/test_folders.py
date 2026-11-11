import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, sqlite3
sys.path.insert(0, SRC)
import config
tmp = tempfile.mkdtemp()
config.DATA_DIR = type(config.DATA_DIR)(tmp); config.LIBRARY_DIR = config.DATA_DIR / "library"; config.FILES_DB = config.DATA_DIR / "atom.db"
config.PROFILE_DB = config.DATA_DIR / "profile.db"
import tools, userprofile
bad = []
def check(n, c, *info):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append((n, info))

def mk(name, text):
    p = os.path.join(tmp, name); open(p, "w").write(text); return p

store = tools.FileStore(config.FILES_DB)
a = mk("sales_q3.txt", "Q3 sales report totals revenue 5000")
b = mk("cv_maria.txt", "Maria Santos skills Python SQL revenue dashboards")
c = mk("notes.txt", "meeting notes about revenue")
added, _ = store.add([a, c])
check("default folder is Work", all(r.folder == "Work" for r in added))
added, _ = store.add([b], folder="About me")
check("add into a folder", added[0].folder == "About me")
check("folders: built-ins first", store.folders()[:3] == ["Work", "Reports", "About me"])
check("create keeps proper name", store.create_folder("clients") == "clients" and store.create_folder("CLIENTS") == "clients")
check("custom folder listed", "clients" in store.folders())
try:
    store.create_folder("   "); check("empty name rejected", False)
except ValueError:
    check("empty name rejected", True)
check("move to a folder", store.set_folder([c], "Clients") == 1 and store.in_folder("clients")[0].name == "notes.txt")
check("counts", store.folder_counts()["Work"] == 1 and store.folder_counts()["About me"] == 1 and store.folder_counts()["clients"] == 1)
# search by folder
all_hits = {h.name for h in store.search("revenue")}
check("search everywhere finds all", all_hits == {"sales_q3.txt", "cv_maria.txt", "notes.txt"}, all_hits)
check("search one folder", {h.name for h in store.search("revenue", folder="Work")} == {"sales_q3.txt"})
check("search folder, case-insensitive", {h.name for h in store.search("revenue", folder="about ME")} == {"cv_maria.txt"})
check("describe groups by folder", "Work:" in store.describe() and "About me:" in store.describe())
check("describe one folder", store.describe("clients").startswith("Files in the folder 'clients'") and "notes.txt" in store.describe("clients") and "sales_q3" not in store.describe("clients"))
check("describe empty folder", "no files" in store.describe("Reports"))
ok, msg = store.delete_folder("Work"); check("built-in folder stays", not ok)
ok, msg = store.delete_folder("clients"); check("non-empty folder stays", not ok)
store.set_folder([c], "Work")
ok, msg = store.delete_folder("clients"); check("empty custom folder deleted", ok and "clients" not in store.folders(), store.folders())

# reports made by Atom go to Reports
box = tools.ToolBox(store)
tools._open_path = lambda p: None
report = tools.Path(tmp) / "made_report.txt"; report.write_text("status report revenue")
check("new report filed in Reports", "Reports" in box._keep_new_file(report) and store.in_folder("Reports")[0].name == "made_report.txt")

# tool: organize_files
check("tool folders", "- Work:" in box.run("organize_files", {"action": "folders"}) and "- Reports: 1" in box.run("organize_files", {"action": "folders"}))
r = box.run("organize_files", {"action": "move", "folder": "Invoices", "files": ["sales_q3", "nothing_here"]})
check("tool move", "Moved sales_q3.txt to Invoices" in r and "nothing_here" in r and store.in_folder("Invoices"), r)
check("tool create", "ready" in box.run("organize_files", {"action": "create", "folder": "Taxes"}))
check("tool delete", "Removed" in box.run("organize_files", {"action": "delete", "folder": "Taxes"}))
check("tool move needs both", "which files" in box.run("organize_files", {"action": "move", "folder": "X"}).lower())
check("tool search by folder", "sales_q3" in box.run("search_files", {"query": "revenue", "folder": "Invoices"}) and "No matches in the folder 'Work'" in box.run("search_files", {"query": "sales", "folder": "Work"}))
check("tool list by folder", "cv_maria" in box.run("list_files", {"folder": "About me"}))
check("tool pick: folder words", "organize_files" in box.pick("move my report to a new folder"))

# profile uses the About me folder
prof = userprofile.Profile(store)
check("profile = About me folder", [r.name for r in prof.pinned()] == ["cv_maria.txt"])
ok, _ = prof.pin("notes"); check("pin moves the file into About me", ok and store.in_folder("About me") and {r.name for r in store.in_folder("About me")} == {"cv_maria.txt", "notes.txt"})
ok, _ = prof.unpin("notes"); check("unpin moves it back to Work", ok and "notes.txt" in {r.name for r in store.in_folder("Work")})
prof.close()

# an old database (before folders) and an old pinned list are carried over
old = os.path.join(tmp, "old.db")
conn = sqlite3.connect(old)
conn.executescript("""CREATE TABLE files (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, library_path TEXT NOT NULL, name TEXT NOT NULL,
 size INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'File', added TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ready', error TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL DEFAULT '');
 INSERT INTO files (path, library_path, name, added) VALUES ('/x/cv.txt', '/x/cv.txt', 'cv.txt', '2026-01-01T00:00:00');""")
conn.commit(); conn.close()
s2 = tools.FileStore(old)
check("old library: files default to Work", [r.folder for r in s2.all()] == ["Work"])
pdb = os.path.join(tmp, "oldprofile.db")
c2 = sqlite3.connect(pdb); c2.executescript("CREATE TABLE pinned (path TEXT PRIMARY KEY, ts REAL NOT NULL); INSERT INTO pinned VALUES ('/x/cv.txt', 1.0);"); c2.commit(); c2.close()
p2 = userprofile.Profile(s2, tools.Path(pdb))
check("old pinned list adopted into About me", [r.name for r in p2.pinned()] == ["cv.txt"] and s2.all()[0].folder == "About me")
p2.close()

print("\n%d failed" % len(bad))
for n, i in bad: print(" -", n, i)
sys.exit(1 if bad else 0)
