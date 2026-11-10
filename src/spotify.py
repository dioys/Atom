"""spotify.py - lets Atom control Spotify through Spotify's official Web API.

No window code and no AI code in here. It needs:
  * a Spotify Premium account (Spotify only allows playback control on Premium),
  * a free "app" you create once at developer.spotify.com (gives you a Client ID),
  * Spotify open on your computer (Atom starts it for you if it is closed).

Login uses the "PKCE" method, so there is no secret to store: you approve Atom
once in your browser, and Atom keeps a refresh token in ~/.atom/spotify.json.
Only the standard library is used.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import config

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
KINDS = ("track", "artist", "album", "playlist")


class SpotifyError(Exception):
    """A problem Atom can explain to the user in plain words."""


# ---------------------------------------------------------------- settings
def client_id() -> str:
    return (config.load_settings().get("spotify_client_id") or "").strip()


def redirect_uri() -> str:
    # Spotify wants the numeric address 127.0.0.1 here, not the word "localhost"
    return f"http://127.0.0.1:{config.SPOTIFY_REDIRECT_PORT}/callback"


def _load_tokens() -> dict:
    try:
        return json.loads(config.SPOTIFY_TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_tokens(tokens: dict) -> None:
    config.SPOTIFY_TOKEN_FILE.write_text(json.dumps(tokens), encoding="utf-8")


def connected() -> bool:
    """True when a Client ID is saved and you have approved Atom in the browser."""
    return bool(client_id()) and bool(_load_tokens().get("refresh_token"))


def disconnect() -> None:
    try:
        config.SPOTIFY_TOKEN_FILE.unlink()
    except OSError:
        pass


# ------------------------------------------------------------ web requests
def _send(method: str, url: str, headers: dict | None = None, data: bytes | None = None):
    """Make one web request. Returns (status code, JSON body as a dict)."""
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            status, raw = response.status, response.read()
    except HTTPError as error:  # 4xx / 5xx still carry a useful JSON message
        status, raw = error.code, error.read()
    except (URLError, TimeoutError, OSError) as error:
        raise SpotifyError("I couldn't reach Spotify. Check your internet connection.") from error
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


def _token_request(fields: dict) -> dict:
    status, body = _send(
        "POST",
        TOKEN_URL,
        {"Content-Type": "application/x-www-form-urlencoded"},
        urlencode(fields).encode(),
    )
    if status != 200:
        reason = body.get("error_description") or body.get("error") or f"error {status}"
        raise SpotifyError(f"Spotify login failed: {reason}")
    return body


def _store(body: dict, old_refresh: str = "") -> None:
    _save_tokens(
        {
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token") or old_refresh,
            "expires_at": time.time() + int(body.get("expires_in", 3600)),
        }
    )


def _access_token(force_refresh: bool = False) -> str:
    cid = client_id()
    tokens = _load_tokens()
    if not cid or not tokens.get("refresh_token"):
        raise SpotifyError("Spotify isn't connected yet. Open Settings and click Connect Spotify.")
    if not force_refresh and time.time() < tokens.get("expires_at", 0) - 30:
        return tokens["access_token"]
    try:
        body = _token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": cid,
            }
        )
    except SpotifyError as error:
        raise SpotifyError(
            f"{error}. Open Settings and click Connect Spotify again."
        ) from error
    _store(body, tokens["refresh_token"])
    return body["access_token"]


def _explain(status: int, body: dict) -> str:
    error = body.get("error")
    message = error.get("message", "") if isinstance(error, dict) else str(error or "")
    if status == 401:
        return "Spotify says the login expired. Open Settings and click Connect Spotify again."
    if status == 403:
        if "premium" in message.lower():
            return "Spotify says this needs a Premium account."
        return (
            "Spotify refused (403). If your Spotify app is still in Development mode, "
            "add your own email under 'User management' in the developer dashboard. "
            f"{message}".strip()
        )
    if status == 404:
        return "Spotify can't find a device to play on. Open Spotify on your computer and try again."
    if status == 429:
        return "Spotify says I'm asking too fast. Try again in a moment."
    return message or f"Spotify returned error {status}."


def _api(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    url = API + path + ("?" + urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else (b"" if method in ("PUT", "POST") else None)
    for attempt in (0, 1):
        headers = {"Authorization": f"Bearer {_access_token(force_refresh=attempt == 1)}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, payload = _send(method, url, headers, data)
        if status == 401 and attempt == 0:
            continue  # token may have just expired: refresh and try once more
        if status >= 400:
            raise SpotifyError(_explain(status, payload))
        return payload
    return {}


# ------------------------------------------------------------------- login
def connect(timeout: int = 180) -> str:
    """Open the browser so you can approve Atom, then save the login.

    Blocks until you finish (or `timeout` seconds pass), so call it from a
    background thread. Returns a short success message.
    """
    cid = client_id()
    if not cid:
        raise SpotifyError("Paste your Spotify Client ID in Settings first.")

    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = secrets.token_urlsafe(16)

    class Catcher(BaseHTTPRequestHandler):
        def do_GET(self):  # the browser comes back here after you approve
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            self.server.result = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif;padding:40px'>"
                b"<h2>Atom is connected to Spotify.</h2>You can close this tab.</body></html>"
            )

        def log_message(self, *args):  # keep the console quiet
            pass

    try:
        server = HTTPServer(("127.0.0.1", config.SPOTIFY_REDIRECT_PORT), Catcher)
    except OSError as error:
        raise SpotifyError(
            f"Port {config.SPOTIFY_REDIRECT_PORT} is busy. Close the other program using it "
            "or change SPOTIFY_REDIRECT_PORT in config.py (and in the Spotify dashboard)."
        ) from error
    server.result = None
    server.timeout = 3

    url = AUTH_URL + "?" + urlencode(
        {
            "client_id": cid,
            "response_type": "code",
            "redirect_uri": redirect_uri(),
            "scope": config.SPOTIFY_SCOPES,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
        }
    )
    webbrowser.open(url)

    deadline = time.time() + timeout
    try:
        while server.result is None and time.time() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    result = server.result
    if not result:
        raise SpotifyError(
            "I waited but Spotify never came back. Check that the Redirect URI in your "
            f"Spotify app is exactly {redirect_uri()}"
        )
    if result.get("state") != state:
        raise SpotifyError("The login didn't match what I asked for. Please try again.")
    if "error" in result:
        raise SpotifyError(f"Spotify said: {result['error']}")

    body = _token_request(
        {
            "grant_type": "authorization_code",
            "code": result.get("code", ""),
            "redirect_uri": redirect_uri(),
            "client_id": cid,
            "code_verifier": verifier,
        }
    )
    _store(body)
    return "Connected to Spotify."


# ------------------------------------------------------------------ playing
def _pick_device(launch=None, wait: int = 14) -> dict:
    """The device to play on. Prefers the one already playing, then this
    computer's Spotify app, then anything else (phone, web player...).
    If Spotify isn't running, `launch()` starts it and we wait for it to appear."""
    deadline = time.time() + wait
    started = False
    while True:
        devices = _api("GET", "/me/player/devices").get("devices") or []
        usable = [d for d in devices if d.get("id") and not d.get("is_restricted")]
        if usable:
            usable.sort(key=lambda d: (not d.get("is_active"), d.get("type") != "Computer"))
            return usable[0]
        if launch is not None and not started:
            launch()
            started = True
        if launch is None or time.time() >= deadline:
            raise SpotifyError(
                "I can't find Spotify on your computer. Open the Spotify app, "
                "play anything for a second, and ask me again."
            )
        time.sleep(2)


def _similar(a: str, b: str) -> float:
    """How alike two names are, from 0 (nothing) to 1 (same). Ignores capitals."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _split_by(query: str) -> tuple[str, str]:
    """'ilomilo by billie eilish' -> ('ilomilo', 'billie eilish')."""
    cut = query.lower().rfind(" by ")
    if cut > 0:
        return query[:cut].strip(), query[cut + 4 :].strip()
    return query, ""


def _search(q: str, kind: str) -> list[dict]:
    found = _api("GET", "/search", {"q": q, "type": kind, "limit": 10})
    return [i for i in (found.get(kind + "s") or {}).get("items") or [] if i]  # Spotify may send nulls


def _score(item: dict, kind: str, title: str, artist: str) -> float:
    score = _similar(item.get("name", ""), title)
    if artist and kind in ("track", "album"):
        names = [a.get("name", "") for a in item.get("artists") or []]
        if names:
            score += 0.5 * max(_similar(n, artist) for n in names)
    return score


def _find(query: str, kind: str, artist: str = "") -> dict:
    """Find the best match. For a song or album we search by title AND artist
    (Spotify's exact-field search), then fall back to looser searches, and pick
    the result whose name is closest to what you asked for."""
    title = query
    if kind in ("track", "album") and not artist:
        title, artist = _split_by(query)

    tries: list[str] = []
    if kind in ("track", "album") and artist:
        tries.append(f'{kind}:"{title}" artist:"{artist}"')  # exact fields
        tries.append(f"{title} {artist}")                     # looser words
    tries.append(query if not artist else f"{title} {artist}")
    tries.append(title)

    fallback = None
    seen: set[str] = set()
    for q in tries:
        if q in seen:
            continue
        seen.add(q)
        items = _search(q, kind)
        if not items:
            continue
        best = max(items, key=lambda i: _score(i, kind, title, artist))
        if _similar(best.get("name", ""), title) >= 0.75:
            return best  # the name matches what was asked for
        fallback = fallback or best
    if fallback:
        return fallback
    raise SpotifyError(f"Spotify found no {kind} called '{query}'.")


def _label(item: dict, kind: str) -> str:
    name = item.get("name", "that")
    artists = item.get("artists") or []
    if kind in ("track", "album") and artists:
        return f"{name} by {artists[0].get('name', 'unknown')}"
    return name


def _wake(device: dict) -> None:
    """A Spotify app that was just opened (or has been idle) lists itself as a device but ignores
    'play' until it is made the ACTIVE device. This hands playback to it, without starting anything."""
    try:
        _api("PUT", "/me/player", body={"device_ids": [device["id"]], "play": False})
    except SpotifyError as error:
        print(f"[atom] spotify could not wake the device: {error}", flush=True)
    time.sleep(1.5)


def play(query: str, kind: str = "track", launch=None, artist: str = "", open_uri=None) -> str:
    """Search Spotify and start playing the best match. Returns what is playing.

    For one song, pass the title as `query` and the singer as `artist`
    (or just say "title by singer" in `query`).
    """
    kind = kind if kind in KINDS else "track"
    query = " ".join((query or "").split())[:100]
    artist = " ".join((artist or "").split())[:100]
    if not query:
        raise SpotifyError("Tell me what to play.")
    if artist and kind in ("artist", "playlist"):
        if kind == "artist" and _similar(query, artist) >= 0.6:
            artist = ""  # same name twice: they just want the artist, not a song
        else:
            kind = "track"  # a singer plus a different title means one specific song
    if kind in ("artist", "playlist") and " by " in query.lower():
        kind = "track"  # "ilomilo by billie eilish" is a song, whatever the AI guessed
    item = _find(query, kind, artist)
    device = _pick_device(launch)
    if not device.get("is_active"):
        _wake(device)
    where = device.get("name") or "your Spotify app"
    success = f"Now playing {_label(item, kind)} ({kind}) on {where}."
    params = {"device_id": device["id"]}

    # Spotify says "ok" even when nothing starts, so after each way of asking we
    # check that it is really playing. A song can be asked for in three ways.
    bodies = [{"uris": [item["uri"]]} if kind == "track" else {"context_uri": item["uri"]}]
    album = ((item.get("album") or {}).get("uri")) if kind == "track" else None
    if album:  # same song, started from inside its album
        bodies.append({"context_uri": album, "offset": {"uri": item["uri"]}})
    for round_ in (0, 1):
        for body in bodies:
            _api("PUT", "/me/player/play", params, body)
            if _is_playing():
                return success
        if round_ == 0:
            _wake(device)   # still silent: make the app active once more, then ask again

    if kind == "track":  # last way: put the song next in the queue and skip to it
        try:
            _api("POST", "/me/player/queue", {"uri": item["uri"], **params})
            _api("POST", "/me/player/next", params)
            if _is_playing():
                return success
        except SpotifyError as error:
            print(f"[atom] spotify queue trick failed: {error}", flush=True)

    if open_uri is not None:   # last resort: ask the Spotify app itself to open it and start playing
        try:
            open_uri(item["uri"] + ":play")
            if _is_playing():
                return success
        except Exception as error:
            print(f"[atom] spotify ':play' link failed: {error}", flush=True)

    return (
        f"Spotify accepted '{_label(item, kind)}' but it is not playing on {where}. "
        "Tell the user to press play once in the Spotify app, then ask again."
    )


def _is_playing() -> bool:
    """Wait a moment, then ask Spotify whether music is really playing."""
    time.sleep(1.5)
    try:
        state = _api("GET", "/me/player")
    except SpotifyError:
        return True  # can't tell; trust the earlier "ok"
    if state.get("is_playing"):
        return True
    # show what Spotify says, so a stubborn failure can be understood
    print(
        "[atom] spotify not playing yet. player says: "
        f"item={(state.get('item') or {}).get('name')!r} "
        f"device={(state.get('device') or {}).get('name')!r} "
        f"blocked={(state.get('actions') or {}).get('disallows')}",
        flush=True,
    )
    return False


def control(action: str) -> str:
    """pause, resume, next or previous on whatever Spotify is playing."""
    if action == "pause":
        _api("PUT", "/me/player/pause")
        return "Paused."
    if action == "resume":
        _api("PUT", "/me/player/play")
        return "Resumed."
    if action == "next":
        _api("POST", "/me/player/next")
        return "Skipped to the next track."
    if action == "previous":
        _api("POST", "/me/player/previous")
        return "Went back to the previous track."
    raise SpotifyError(f"I don't know the music action '{action}'.")