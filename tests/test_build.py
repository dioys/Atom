import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, SRC); sys.path.insert(0, SCRIPTS)
import build_exe as b
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)
d = tempfile.mkdtemp(); ico = Path(d) / "a.ico"; ico.write_bytes(b"x")
c = b.build_command(False, ico, ["src;dst"])
check("onedir windowed named Atom", "--onedir" in c and "--windowed" in c and c[c.index("--name") + 1] == "Atom")
check("entry point last", c[-1].endswith("main.py"))
check("icon passed", c[c.index("--icon") + 1] == str(ico))
check("extra data passed", c[c.index("--add-data") + 1] == "src;dst")
check("hidden imports include voice parts", "PySide6.QtTextToSpeech" in c and "speech_recognition" in c and "watchdog.observers" in c)
check("excludes present", "tkinter" in c and "PySide6.QtWebEngineCore" in c)
check("onefile option", "--onefile" in b.build_command(True) and "--onedir" not in b.build_command(True))
check("missing icon skipped", "--icon" not in b.build_command(False, Path(d) / "none.ico"))
check("no PySide6 here -> no plugin data, no crash", b.qt_plugin_data() == [])
# every module Atom imports at top level is covered by pip requirements or hidden imports
import re
mods = set()
for f in Path(SRC).glob("*.py"):
    for m in re.findall(r"^\s*(?:import|from)\s+([a-zA-Z_][\w]*)", f.read_text(), re.M):
        mods.add(m)
local = {p.stem for p in Path(SRC).glob("*.py")}
third = sorted(m for m in mods - local if m not in sys.stdlib_module_names and m != "__future__")
print("third-party imports:", third)
req = Path(ROOT_DIR + "/requirements.txt").read_text().lower()
known = {"PySide6": "pyside6", "anthropic": "anthropic", "openai": "openai", "openpyxl": "openpyxl", "docx": "python-docx", "pypdf": "pypdf",
         "pptx": "python-pptx", "PIL": "pillow", "speech_recognition": "speechrecognition", "pandas": "pandas", "matplotlib": "matplotlib",
         "watchdog": "watchdog", "numpy": "numpy", "ddgs": "ddgs", "kokoro_onnx": "kokoro-onnx", "scipy": None, "PyInstaller": None, "pytesseract": "pytesseract", "soundcard": "soundcard", "pywinauto": "pywinauto", "winreg": None, "wintypes": None}
unknown = [m for m in third if m not in known]
check("no unexpected third-party imports", not unknown)
if unknown: print("UNKNOWN:", unknown)
missing = [m for m in third if known.get(m) and known[m] not in req]
check("all in requirements.txt", not missing)
if missing: print("MISSING:", missing)
print("ALL PASSED" if not bad else bad)
