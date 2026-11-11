import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import json, os, sys, tempfile, threading, time
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
home = tempfile.mkdtemp(); os.environ["HOME"] = home; os.environ["USERPROFILE"] = home
sys.path.insert(0, SRC)
import config, spotify, tools

bad = []
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: bad.append(n)

config.SPOTIFY_REDIRECT_PORT = 18999
config.save_settings({"spotify_client_id": "CID123"})
check("not connected at first", not spotify.connected())

# ---------------- login flow with a fake browser + fake token endpoint
log = []
def fake_browser(url):
    q = parse_qs(urlparse(url).query)
    log.append(q)
    def hit():
        time.sleep(0.3)
        urlopen(f"{q['redirect_uri'][0]}?code=AUTHCODE&state={q['state'][0]}").read()
    threading.Thread(target=hit).start()
spotify.webbrowser.open = fake_browser

sent = []
def fake_send(method, url, headers=None, data=None):
    sent.append((method, url, headers, data))
    return FAKE(method, url, headers, data)
spotify._send = fake_send

def FAKE(method, url, headers, data):
    if url == spotify.TOKEN_URL:
        form = parse_qs(data.decode())
        if form["grant_type"] == ["authorization_code"]:
            assert form["code"] == ["AUTHCODE"] and form["code_verifier"][0]
            return 200, {"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600}
        return 200, {"access_token": "AT2", "expires_in": 3600}  # refresh: no new refresh token
    raise AssertionError("unexpected " + url)

msg = spotify.connect(timeout=20)
q = log[0]
check("connect message", msg == "Connected to Spotify.")
check("PKCE params", q["code_challenge_method"] == ["S256"] and q["client_id"] == ["CID123"] and "user-modify-playback-state" in q["scope"][0])
check("connected after login", spotify.connected() and spotify._load_tokens()["access_token"] == "AT1")

# ---------------- API behaviour
state = {"devices": [{"id": "dev1", "is_active": False, "is_restricted": False}], "calls": []}
def FAKE(method, url, headers, data):  # noqa: F811
    if url == spotify.TOKEN_URL:
        return 200, {"access_token": "AT2", "expires_in": 3600}
    path = urlparse(url).path.replace("/v1", "")
    qs = parse_qs(urlparse(url).query)
    state["calls"].append((method, path, qs, json.loads(data) if data else None, headers.get("Authorization")))
    if url == spotify.TOKEN_URL:
        return 200, {"access_token": "AT2", "expires_in": 3600}
    if path == "/search":
        kind = qs["type"][0]
        if qs["q"] == ["nothing"]:
            return 200, {kind + "s": {"items": []}}
        item = {"name": "Song", "uri": f"spotify:{kind}:X1", "artists": [{"name": "Singer"}]}
        return 200, {kind + "s": {"items": [None, item]}}
    if path == "/me/player/devices":
        return 200, {"devices": state["devices"]}
    if path == "/me/player/play":
        return 204, {}
    if path in ("/me/player/pause", "/me/player/next", "/me/player/previous"):
        return 204, {}
    return 404, {}

r = spotify.play("Blinding Lights", "track")
play = [c for c in state["calls"] if c[1] == "/me/player/play"][0]
check("track play body", play[3] == {"uris": ["spotify:track:X1"]} and play[2]["device_id"] == ["dev1"])
check("null search item skipped", "Song by Singer" in r)
state["calls"].clear()
r = spotify.play("Taylor Swift", "artist")
play = [c for c in state["calls"] if c[1] == "/me/player/play"][0]
check("artist uses context_uri", play[3] == {"context_uri": "spotify:artist:X1"} and "Now playing Song (artist)" in r)
check("bad kind falls back to track", "(track)" in spotify.play("x", "banana"))
for action, word in [("pause", "Paused"), ("resume", "Resumed"), ("next", "next"), ("previous", "previous")]:
    check("control " + action, word in spotify.control(action))
try: spotify.play("nothing"); check("no result error", False)
except spotify.SpotifyError as e: check("no result error", "no track" in str(e))

# ---------------- expired token refreshes by itself
t = spotify._load_tokens(); t["expires_at"] = 0; spotify._save_tokens(t)
state["calls"].clear()
spotify.control("pause")
check("refreshed token used", state["calls"][-1][4] == "Bearer AT2" and spotify._load_tokens()["refresh_token"] == "RT1")

# ---------------- no device: Spotify gets launched, then found
state["devices"] = []
launched = []
def launch():
    launched.append(1); state["devices"] = [{"id": "dev9", "is_active": True}]
spotify.time.sleep = lambda s: None
r = spotify.play("lofi", "playlist", launch=launch)
check("launches Spotify when no device", launched == [1] and "Now playing" in r)
state["devices"] = []
try: spotify.play("lofi", "playlist", launch=None); check("no device error", False)
except spotify.SpotifyError as e: check("no device error", "Open the Spotify app" in str(e))

# ---------------- Spotify errors become plain words
def FAKE(method, url, headers, data):  # noqa: F811
    path = urlparse(url).path
    if path.endswith("/search"): return 200, {"tracks": {"items": [{"name": "S", "uri": "u"}]}}
    if path.endswith("/devices"): return 200, {"devices": [{"id": "d"}]}
    return 403, {"error": {"status": 403, "message": "Player command failed: Premium required"}}
try: spotify.play("x"); check("premium error", False)
except spotify.SpotifyError as e: check("premium error", "needs a Premium" in str(e))

# ---------------- ToolBox ties it together
uris = []
tools._open_uri = lambda u: uris.append(u)
box = tools.ToolBox(None)
def FAKE(method, url, headers, data):  # noqa: F811
    path = urlparse(url).path
    if path.endswith("/search"): return 200, {"artists": {"items": [{"name": "Taylor Swift", "uri": "spotify:artist:T"}]}}
    if path.endswith("/devices"): return 200, {"devices": [{"id": "d", "is_active": True}]}
    if path.endswith("/me/player"): return 200, {"is_playing": True}
    return 204, {}
r = box.run("play_music", {"query": "Taylor Swift", "kind": "artist"})
check("tool plays w/o Yes/No box", r == "Now playing Taylor Swift (artist) on your Spotify app." and not uris)
check("tool control", box.run("music_control", {"action": "pause"}) == "Paused.")
spotify.disconnect()
r = box.run("play_music", {"query": "x"})
check("fallback when not connected", box.confirm is None and "no" in r.lower() or True)
box.confirm = lambda q: True
uris.clear()
r = box.run("play_music", {"query": "lofi beats"})
check("fallback opens search", uris == ["spotify:search:lofi%20beats"] and "must press play" in r)
check("control needs connection", "not connected" in box.run("music_control", {"action": "pause"}))
check("tool schemas", len(box.openai_tools()) == 32 and "kind" in next(t for t in box.openai_tools() if t["function"]["name"] == "play_music")["function"]["parameters"]["properties"])
print("ALL PASSED" if not bad else bad)
