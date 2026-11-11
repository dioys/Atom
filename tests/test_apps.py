import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import os, sys, tempfile, subprocess
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, tools
config.CONFIRM_ACTIONS = True  # these tests cover the Yes/No box
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)

check("spotify built in", tools.resolve_app("Spotify") == "spotify")
check("custom app absent at first", tools.resolve_app("figma") is None)
config.save_settings({"apps": {"Figma": "figma:", "bad": 5, "": "x"}})
check("custom app from settings", tools.resolve_app("figma") == "figma" and tools.all_apps()["figma"][0] == "Figma")
check("bad entries ignored", "bad" not in tools.all_apps())

calls = []
tools.subprocess.Popen = lambda cmd, **kw: calls.append(cmd)
real = sys.platform
try:
    sys.platform = "win32"
    tools._launch_app("spotify"); tools._launch_app("figma")
    sys.platform = "darwin"
    tools._launch_app("spotify")
finally:
    sys.platform = real
check("windows spotify cmd", calls[0] == ["cmd", "/c", "start", "", "spotify:"])
check("windows custom cmd", calls[1] == ["cmd", "/c", "start", "", "figma:"])
check("mac spotify cmd", calls[2] == ["open", "-a", "Spotify"])

box = tools.ToolBox(None, confirm=lambda q: True)
enum = next(t for t in box.openai_tools() if t["function"]["name"] == "open_app")["function"]["parameters"]["properties"]["app"]["enum"]
check("enum has spotify + figma", "spotify" in enum and "figma" in enum)
tools._launch_app = lambda k: calls.append(("app", k))
check("open_app spotify", box.run("open_app", {"app": "spotify"}) == "Opened Spotify.")
print("ALL PASSED" if not bad else bad)

# --- play_music
uris = []
tools._open_uri = lambda u: uris.append(u)
box = tools.ToolBox(None, confirm=lambda q: True)
r = box.run("play_music", {"query": "  lofi   beats & chill "})
check("music uri", uris == ["spotify:search:lofi%20beats%20%26%20chill"])
check("music says press play", "press play" in r)
box.confirm = lambda q: False
uris.clear()
check("music declined", not uris and "said no" in box.run("play_music", {"query": "x"}))
check("music empty query", box.run("play_music", {"query": "  "}).startswith("Error"))
print("MUSIC DONE" if not bad else bad)
