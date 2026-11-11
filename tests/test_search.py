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

def t(name, artist, uri):
    return {"name": name, "uri": uri, "artists": [{"name": artist}]}

queries, played = [], []
CATALOG = {
    'track:"ilomilo" artist:"billie eilish"': [t("ilomilo - Remix", "Someone", "u:remix"), t("ilomilo", "Billie Eilish", "u:right")],
    "ilomilo billie eiling": [t("Ilomilo", "Billie Eilish", "u:right"), t("Other", "Billie Eilish", "u:other")],
    "weird song": [t("Totally Different", "X", "u:first"), t("Another", "Y", "u:second")],
}
def fake_send(method, url, headers=None, data=None):
    p = urlparse(url); qs = parse_qs(p.query)
    if p.path.endswith("/search"):
        q = qs["q"][0]; queries.append(q)
        return 200, {"tracks": {"items": CATALOG.get(q, [])}, "artists": {"items": [{"name": "Billie Eilish", "uri": "u:artist"}]}, "playlists": {"items": [None, {"name": "lofi beats", "uri": "u:pl"}]}}
    if p.path.endswith("/devices"): return 200, {"devices": [{"id": "d", "is_active": True}]}
    if p.path.endswith("/play"): played.append(json.loads(data)); return 204, {}
    return 404, {}
spotify._send = fake_send

r = spotify.play("ilomilo by billie eilish", "artist")      # AI guessed the wrong kind
check("'X by Y' treated as a song", played[-1] == {"uris": ["u:right"]} and "ilomilo by Billie Eilish" in r)
check("exact-field search tried first", queries[0] == 'track:"ilomilo" artist:"billie eilish"')

queries.clear()
r = spotify.play("ilomilo", "track", artist="billie eiling")  # misspelled artist
check("misspelled artist still finds it", played[-1] == {"uris": ["u:right"]})
check("falls back to looser search", queries[0].startswith("track:") and "ilomilo billie eiling" in queries)

r = spotify.play("weird song", "track")
check("no close match -> best available", played[-1] == {"uris": ["u:first"]})

r = spotify.play("billie eilish", "artist")
check("plain artist still plays artist", played[-1] == {"context_uri": "u:artist"})
print("ALL PASSED" if not bad else bad)

# the bug seen on the real PC: AI sent query and artist both "Taylor Swift", kind artist
r = spotify.play("Taylor Swift", "artist", artist="Taylor Swift")
check("artist request with repeated name stays an artist", played[-1] == {"context_uri": "u:artist"} and "(artist)" in r)
r = spotify.play("lofi beats", "playlist", artist="")
check("playlist unaffected", "(playlist)" in r)
print("ALL PASSED 2" if not bad else bad)
