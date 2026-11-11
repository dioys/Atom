import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import json, os, sys, tempfile
from urllib.parse import parse_qs, urlparse
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, spotify
bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)
config.save_settings({"spotify_client_id": "C"})
spotify._save_tokens({"access_token": "A", "refresh_token": "R", "expires_at": 9e12})
spotify.time.sleep = lambda s: None

st = {"devices": [], "playing": [True], "plays": [], "bodies": [], "queued": [], "nexts": []}
def fake_send(method, url, headers=None, data=None):
    p = urlparse(url); qs = parse_qs(p.query)
    if p.path.endswith("/search"):
        return 200, {"tracks": {"items": [{"name": "Dare", "uri": "u:dare", "album": {"uri": "u:album"}, "artists": [{"name": "Gorillaz"}]}]}, "artists": {"items": [{"name": "Gorillaz", "uri": "u:art"}]}}
    if p.path.endswith("/devices"): return 200, {"devices": st["devices"]}
    if p.path.endswith("/play"): st["plays"].append(qs["device_id"][0]); st["bodies"].append(json.loads(data)); return 204, {}
    if p.path.endswith("/queue"): st["queued"].append(qs["uri"][0]); return 204, {}
    if p.path.endswith("/next"): st["nexts"].append(1); return 204, {}
    if p.path.endswith("/me/player"): return 200, {"is_playing": st["playing"].pop(0) if len(st["playing"]) > 1 else st["playing"][0]}
    return 404, {}
spotify._send = fake_send

st["devices"] = [
    {"id": "phone", "name": "Redmi", "type": "Smartphone", "is_active": False},
    {"id": "pc", "name": "DELRO-PC", "type": "Computer", "is_active": False},
    {"id": "web", "name": "Web Player", "type": "Computer", "is_active": False},
]
r = spotify.play("Dare", "track", artist="Gorillaz")
check("prefers a Computer over a phone", st["plays"][-1] in ("pc", "web") and st["plays"][-1] != "phone" and "on DELRO-PC" in r)
st["devices"][0]["is_active"] = True
st["plays"].clear()
r = spotify.play("Dare", "track", artist="Gorillaz")
check("active device wins", st["plays"][-1] == "phone" and "on Redmi" in r)

st["devices"] = [{"id": "pc", "name": "DELRO-PC", "type": "Computer", "is_active": True}]
st["playing"] = [False, True]; st["plays"].clear()
r = spotify.play("Dare", "track", artist="Gorillaz")
check("retries once when not playing, then ok", len(st["plays"]) == 2 and r.startswith("Now playing"))
st["playing"] = [False]; st["plays"].clear()
r = spotify.play("Dare", "track", artist="Gorillaz")
check("honest when it never starts", len(st["plays"]) == 2 and "not playing on DELRO-PC" in r and not r.startswith("Now playing"))

# song: first way fails, second way (album + offset) works
st["playing"] = [False, True]; st["plays"].clear(); st["bodies"].clear(); st["queued"].clear()
r = spotify.play("Dare", "track", artist="Gorillaz")
check("tries uris first, then album+offset", st["bodies"] == [{"uris": ["u:dare"]}, {"context_uri": "u:album", "offset": {"uri": "u:dare"}}] and r.startswith("Now playing") and not st["queued"])

# both play bodies fail, queue + next works
st["playing"] = [False, False, True]; st["bodies"].clear(); st["queued"].clear(); st["nexts"].clear()
r = spotify.play("Dare", "track", artist="Gorillaz")
check("queue + next as last way", st["queued"] == ["u:dare"] and st["nexts"] == [1] and r.startswith("Now playing"))

# artist: only one try, no queue trick
st["playing"] = [False]; st["bodies"].clear(); st["queued"].clear()
r = spotify.play("Gorillaz", "artist")
check("artist never uses queue trick", not st["queued"] and not r.startswith("Now playing"))
print("ALL PASSED" if not bad else bad)
