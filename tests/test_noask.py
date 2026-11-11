import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, tools
opened = []
tools._launch_app = lambda k: opened.append(k)
box = tools.ToolBox(None)   # no confirm function at all, default settings
r = box.run("open_app", {"app": "Spotify"})
print("PASS default: opens without asking" if config.CONFIRM_ACTIONS is False and r == "Opened Spotify." and opened == ["spotify"] else "FAIL default")
print("PASS always on top default" if config.ALWAYS_ON_TOP is True else "FAIL on top")
