import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, types
sys.path.insert(0, SRC)
import config
tmp = tempfile.mkdtemp()
config.DATA_DIR = type(config.DATA_DIR)(tmp); config.LIBRARY_DIR = config.DATA_DIR / "library"; config.FILES_DB = config.DATA_DIR / "atom.db"
config.PROFILE_DB = config.DATA_DIR / "profile.db"
import tools, userprofile
store = tools.FileStore(config.FILES_DB)
cv = os.path.join(tmp, "my_cv.txt")
open(cv, "w").write("Maria Santos. Computer engineer.\nSkills: Python, SQL, Power BI, Excel dashboards.\nExperience: 2 years building reports for a logistics company.\nProject: Atom, a personal AI desktop assistant.\nEducation: BS Computer Engineering.")
other = os.path.join(tmp, "elsewhere"); os.makedirs(other)
notes = os.path.join(other, "recipes.txt"); open(notes, "w").write("pancakes and eggs")
store.add([cv, notes])
p = userprofile.Profile(store)
assert p.is_empty()
assert p.add_many("Python, SQL and Power BI", "skill") == ["Python", "SQL", "Power BI"]
assert p.add_many("Python", "skill") == []                          # no duplicates
p.add("3 years as a data analyst at Acme", "experience")
p.add("Atom: a desktop assistant I built with PySide6 and Groq", "project")
p.add("fast learner", "strength")
assert len(p.items()) == 6 and len(p.items("skill")) == 3
ok, msg = p.pin("my_cv"); assert ok, msg
ok, msg = p.pin(os.path.join(other, "new_cert.txt")); assert not ok
newfile = os.path.join(other, "cert.txt"); open(newfile, "w").write("Certificate: Google Data Analytics, 2025.")
ok, msg = p.pin(newfile); assert ok, msg                            # a file in a different folder: read first, then pinned
assert {r.name for r in p.pinned()} == {"my_cv.txt", "cert.txt"}
assert not p.is_empty()
# questions
ctx = p.context("What are your skills?"); assert "Python" in ctx and "SQL" in ctx
ctx = p.context("Tell me about yourself"); assert "Python" in ctx and "data analyst" in ctx and "my_cv.txt" in ctx
ctx = p.context("Do you know power bi"); assert "Power BI" in ctx
ctx = p.context("tell me about your google certificate"); assert "Google Data Analytics" in ctx
assert "pancakes" not in p.context("what eggs do you like")        # un-pinned files never leak into the profile
fp = p.first_person("What are your main skills?"); assert fp.startswith("My main skills are Python, SQL and Power BI"), fp
assert "data analyst" in p.first_person("What experience do you have?")
assert p.first_person("Do you know Power BI?") == "Yes, Power BI is one of my skills.", p.first_person("Do you know Power BI?")
assert p.first_person("what is the weather") == ""
assert p.relevant("what's the weather") == ""
assert "Python" in p.relevant("what skills do you have")
kw = p.keywords(); assert "Power BI" in kw and "Python" in kw
assert p.remove("fast learner") == 1 and p.remove("#1") == 1
ok, msg = p.unpin("cert"); assert ok
assert [r.name for r in p.pinned()] == ["my_cv.txt"]
# learn from files with a fake AI
p.ask = lambda system, user: "skill: Excel dashboards\nexperience: 2 years building reports for a logistics company\nproject: Atom\nrandom line\n- education: BS Computer Engineering"
before = len(p.items()); n = p.learn_from_files(); assert n >= 3 and len(p.items()) == before + n, (n, before)
p.ask = None
try: p.learn_from_files(); raise SystemExit("should fail")
except RuntimeError: pass
assert "Skills:" in p.overview()
p.close()
print("USERPROFILE OK")
