"""
spotify_agent.py — Spotify integration for Vyra
================================================
Handles OAuth 2.0 PKCE authentication, token lifecycle,
playback control, playlist management, and device switching.
All API calls are async via httpx (already in requirements.txt).
"""
import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

# Let dotenv find the nearest .env file (stops at workspace root)
load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

# Loaded from backend/.env  ──  SPOTIFY_CLIENT_ID=<your id>
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI",
                         "http://127.0.0.1:8000/spotify/callback")


SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-library-read",
    "user-top-read",
])

# Token storage: encrypted file next to this module's directory
_BACKEND_DIR = Path(__file__).parent
TOKEN_PATH = _BACKEND_DIR / "storage" / "spotify_tokens.enc"


# ── Exceptions ─────────────────────────────────────────────────────────────────
class SpotifyError(Exception):
    pass


class TokenRevokedError(SpotifyError):
    pass


class SpotifyPremiumRequired(SpotifyError):
    pass


class SpotifyNoActiveDevice(SpotifyError):
    pass


class SpotifyRateLimited(SpotifyError):
    def __init__(self, retry_after=1):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


# ── Connection State ───────────────────────────────────────────────────────────
@dataclass
class SpotifyConnectionState:
    connected: bool = False
    access_token: str = ""
    expires_at: float = 0.0
    user_id: str = ""
    display_name: str = ""
    active_device_id: str = ""
    active_device_name: str = ""
    current_track_uri: str = ""
    current_track_name: str = ""
    current_artist: str = ""
    current_album_art: str = ""
    progress_ms: int = 0
    duration_ms: int = 0
    is_playing: bool = False
    current_mood: str = "neutral"
    mood_sync_active: bool = False


# ── Encryption Helpers ─────────────────────────────────────────────────────────
def _get_fernet_key() -> bytes:
    """Derive a Fernet key from the machine's MAC address (stable across reboots)."""
    import uuid
    machine_id = str(uuid.getnode()).encode()
    key_bytes = hashlib.sha256(machine_id).digest()
    return base64.urlsafe_b64encode(key_bytes)


def _save_tokens(tokens: dict):
    """Encrypt and persist tokens to disk."""
    try:
        from cryptography.fernet import Fernet
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        f = Fernet(_get_fernet_key())
        encrypted = f.encrypt(json.dumps(tokens).encode())
        TOKEN_PATH.write_bytes(encrypted)
        print("[SpotifyAgent] Tokens saved securely.")
    except ImportError:
        # Fallback: store as plain JSON (dev mode only)
        print(
            "[SpotifyAgent] WARNING: cryptography not installed, storing tokens unencrypted!")
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.with_suffix(".json").write_text(json.dumps(tokens))
    except Exception as e:
        print(f"[SpotifyAgent] Error saving tokens: {e}")


def _load_tokens() -> Optional[dict]:
    """Decrypt and load tokens from disk."""
    try:
        if TOKEN_PATH.exists():
            from cryptography.fernet import Fernet
            f = Fernet(_get_fernet_key())
            raw = TOKEN_PATH.read_bytes()
            return json.loads(f.decrypt(raw))
        # Fallback for unencrypted dev tokens
        fallback = TOKEN_PATH.with_suffix(".json")
        if fallback.exists():
            return json.loads(fallback.read_text())
        return None
    except Exception as e:
        print(f"[SpotifyAgent] Error loading tokens: {e}")
        return None


def _clear_tokens():
    """Remove stored tokens (disconnect)."""
    for p in [TOKEN_PATH, TOKEN_PATH.with_suffix(".json")]:
        if p.exists():
            p.unlink(missing_ok=True)


# ── PKCE Helpers ───────────────────────────────────────────────────────────────
def generate_pkce() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(challenge: str, state: str = "") -> str:
    """Build Spotify OAuth authorization URL."""
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if state:
        params["state"] = state
    return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"


# ── Main Agent Class ───────────────────────────────────────────────────────────
class SpotifyAgent:
    """
    Async Spotify integration agent for Vyra.
    Mirrors the pattern of KasaAgent (no __init__ heavy I/O, methods are async).
    """

    def __init__(self):
        self.state = SpotifyConnectionState()
        # Stored between auth start and callback
        self._pkce_verifier: Optional[str] = None
        self._settings_path = _BACKEND_DIR / "settings.json"

    # ── Auth ───────────────────────────────────────────────────────────────────

    def start_auth(self) -> str:
        """Generate PKCE pair, store verifier, return auth URL."""
        verifier, challenge = generate_pkce()
        self._pkce_verifier = verifier
        url = build_auth_url(challenge)
        print(
            f"[SpotifyAgent] Auth URL generated. Client ID: {SPOTIFY_CLIENT_ID[:8]}...")
        return url

    async def finish_auth(self, code: str) -> dict:
        """Exchange OAuth code for tokens. Returns token dict."""
        if not self._pkce_verifier:
            raise SpotifyError(
                "No PKCE verifier found. Call start_auth() first.")
        tokens = await self._exchange_code(code, self._pkce_verifier)
        self._pkce_verifier = None
        tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
        _save_tokens(tokens)

        # Fetch profile
        profile = await self._api_get("/me", tokens["access_token"])
        self.state.connected = True
        self.state.access_token = tokens["access_token"]
        self.state.expires_at = tokens["expires_at"]
        self.state.user_id = profile.get("id", "")
        self.state.display_name = profile.get("display_name", "Spotify User")
        print(f"[SpotifyAgent] Connected as: {self.state.display_name}")
        return {"user_id": self.state.user_id, "display_name": self.state.display_name}

    async def restore_session(self) -> bool:
        """Try to restore from saved tokens on startup."""
        tokens = _load_tokens()
        if not tokens:
            return False
        try:
            token = await self._get_valid_token(tokens)
            profile = await self._api_get("/me", token)
            self.state.connected = True
            self.state.access_token = token
            self.state.user_id = profile.get("id", "")
            self.state.display_name = profile.get(
                "display_name", "Spotify User")
            print(
                f"[SpotifyAgent] Session restored for: {self.state.display_name}")
            return True
        except Exception as e:
            print(f"[SpotifyAgent] Could not restore session: {e}")
            return False

    def disconnect(self):
        """Clear state and stored tokens."""
        self.state = SpotifyConnectionState()
        _clear_tokens()
        print("[SpotifyAgent] Disconnected.")

    # ── Token Management ───────────────────────────────────────────────────────

    async def get_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        tokens = _load_tokens()
        if not tokens:
            raise SpotifyError("Not authenticated. Connect Spotify first.")
        return await self._get_valid_token(tokens)

    async def _get_valid_token(self, tokens: dict) -> str:
        if time.time() >= tokens.get("expires_at", 0) - 60:
            tokens = await self._refresh_token(tokens["refresh_token"])
            tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
            _save_tokens(tokens)
        self.state.access_token = tokens["access_token"]
        self.state.expires_at = tokens["expires_at"]
        return tokens["access_token"]

    async def _exchange_code(self, code: str, verifier: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(SPOTIFY_TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": SPOTIFY_CLIENT_ID,
                "code_verifier": verifier,
            })
            r.raise_for_status()
            return r.json()

    async def _refresh_token(self, refresh_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(SPOTIFY_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": SPOTIFY_CLIENT_ID,
            })
            if r.status_code == 400:
                raise TokenRevokedError(
                    "Refresh token invalid — re-authentication required.")
            r.raise_for_status()
            data = r.json()
            # Spotify may or may not return a new refresh_token; preserve old one if missing
            if "refresh_token" not in data:
                data["refresh_token"] = refresh_token
            return data

    # ── Internal API Helper ────────────────────────────────────────────────────

    async def _api_request(self, method: str, path: str, **kwargs) -> Optional[dict]:
        token = await self.get_token()
        headers = {"Authorization": f"Bearer {token}",
                   "Content-Type": "application/json"}
        url = f"{SPOTIFY_API_BASE}{path}"
        async with httpx.AsyncClient() as client:
            r = await client.request(method, url, headers=headers, **kwargs)

            if r.status_code == 204:
                return None   # Success, no body (e.g. play, pause, skip)
            if r.status_code == 401:
                raise SpotifyError("Unauthorized — token may be invalid.")
            if r.status_code == 403:
                # 403 can be Premium required OR insufficient scope — read the body
                try:
                    body = r.json()
                    err_msg = body.get('error', {}).get('message', '')
                except Exception:
                    err_msg = ''
                if 'premium' in err_msg.lower():
                    raise SpotifyPremiumRequired(
                        "Spotify Premium required for this action.")
                raise SpotifyError(
                    f"Permission denied: {err_msg or 'Insufficient scope or forbidden action.'} You may need to reconnect Spotify to grant new permissions.")
            if r.status_code == 404:
                raise SpotifyNoActiveDevice("No active Spotify device found.")
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 1))
                raise SpotifyRateLimited(retry_after)
            r.raise_for_status()
            return r.json() if r.content else None

    async def _api_get(self, path: str, token: str = None, params: dict = None) -> dict:
        if token is None:
            token = await self.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SPOTIFY_API_BASE}{path}"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params or {})
            if r.status_code == 403:
                raise SpotifyError(
                    f"Access denied (403). This playlist may be private or require reconnecting Spotify to grant new permissions.")
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 1))
                raise SpotifyRateLimited(retry_after)
            r.raise_for_status()
            return r.json() if r.content else {}

    # ── Playback Control ───────────────────────────────────────────────────────

    async def get_playback(self) -> Optional[dict]:
        """Return current playback state or None if nothing is playing."""
        try:
            return await self._api_request("GET", "/me/player")
        except SpotifyNoActiveDevice:
            return None

    async def play(self, context_uri: str = None, uris: list = None, device_id: str = None):
        """Start/resume playback. Pass context_uri for playlist/album, uris for track list."""
        body = {}
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris
        params = {}
        if device_id:
            params["device_id"] = device_id
        await self._api_request("PUT", "/me/player/play", json=body, params=params)

    async def pause(self):
        await self._api_request("PUT", "/me/player/pause")

    async def next_track(self):
        await self._api_request("POST", "/me/player/next")

    async def prev_track(self):
        await self._api_request("POST", "/me/player/previous")

    async def set_shuffle(self, state: bool):
        await self._api_request("PUT", "/me/player/shuffle", params={"state": str(state).lower()})

    async def set_repeat(self, mode: str):
        """mode: 'track' | 'context' | 'off'"""
        if mode not in ("track", "context", "off"):
            mode = "off"
        await self._api_request("PUT", "/me/player/repeat", params={"state": mode})

    async def set_volume(self, volume_percent: int):
        volume_percent = max(0, min(100, volume_percent))
        await self._api_request("PUT", "/me/player/volume", params={"volume_percent": volume_percent})

    async def add_to_queue(self, track_uri: str):
        await self._api_request("POST", "/me/player/queue", params={"uri": track_uri})

    # ── Devices ───────────────────────────────────────────────────────────────

    async def get_devices(self) -> list[dict]:
        result = await self._api_request("GET", "/me/player/devices")
        return result.get("devices", []) if result else []

    async def transfer_playback(self, device_id: str, play: bool = True):
        """Transfer active playback to a different device."""
        await self._api_request("PUT", "/me/player", json={
            "device_ids": [device_id],
            "play": play,
        })
        self.state.active_device_id = device_id

    # ── Search ────────────────────────────────────────────────────────────────

    async def search(self, q: str, search_type: str = "playlist", limit: int = 5) -> dict:
        return await self._api_request("GET", "/search", params={
            "q": q,
            "type": search_type,
            "limit": limit,
        }) or {}

    # ── Playlists ─────────────────────────────────────────────────────────────

    async def get_playlists(self, limit: int = 50) -> list[dict]:
        result = await self._api_request("GET", "/me/playlists", params={"limit": limit})
        return result.get("items", []) if result else []

    async def get_playlist_tracks(self, playlist_id: str, limit: int = 100) -> list[dict]:
        """Fetch tracks for a specific playlist using the standard API."""
        try:
            result = await self._api_get(f"/playlists/{playlist_id}/tracks", params={"limit": limit})
            return result.get("items", []) if result else []
        except Exception as e:
            print(
                f"[SpotifyAgent] get_playlist_tracks error for {playlist_id}: {e}")
            return []

    async def create_playlist(self, name: str, description: str = "", public: bool = False) -> dict:
        if not self.state.user_id:
            raise SpotifyError("Not connected.")
        return await self._api_request(
            "POST", f"/users/{self.state.user_id}/playlists",
            json={"name": name, "description": description, "public": public}
        ) or {}

    async def rename_playlist(self, playlist_id: str, name: str, description: str = None):
        body = {"name": name}
        if description is not None:
            body["description"] = description
        await self._api_request("PUT", f"/playlists/{playlist_id}", json=body)

    async def delete_playlist(self, playlist_id: str):
        """Unfollow (delete) a playlist."""
        await self._api_request("DELETE", f"/playlists/{playlist_id}/followers")

    async def add_tracks(self, playlist_id: str, uris: list[str]):
        await self._api_request("POST", f"/playlists/{playlist_id}/tracks", json={"uris": uris})

    async def remove_tracks(self, playlist_id: str, uris: list[str]):
        await self._api_request("DELETE", f"/playlists/{playlist_id}/tracks",
                                json={"tracks": [{"uri": u} for u in uris]})

    async def reorder_tracks(self, playlist_id: str, range_start: int, insert_before: int):
        await self._api_request("PUT", f"/playlists/{playlist_id}/tracks",
                                json={"range_start": range_start, "insert_before": insert_before})

    # ── Now Playing Poller ────────────────────────────────────────────────────

    async def poll_now_playing(self, on_update_callback=None):
        """
        Long-running background task that polls every 5s and calls on_update_callback
        with track metadata whenever the track changes.
        """
        while self.state.connected:
            try:
                playback = await self.get_playback()
                if playback and playback.get("item"):
                    item = playback["item"]
                    new_uri = item.get("uri", "")

                    self.state.current_track_uri = new_uri
                    self.state.current_track_name = item.get("name", "")
                    artists = item.get("artists", [])
                    self.state.current_artist = ", ".join(
                        a["name"] for a in artists)
                    images = item.get("album", {}).get("images", [])
                    self.state.current_album_art = images[0]["url"] if images else ""
                    self.state.is_playing = playback.get("is_playing", False)
                    self.state.progress_ms = playback.get("progress_ms", 0)
                    self.state.duration_ms = item.get("duration_ms", 0)
                    device = playback.get("device", {})
                    self.state.active_device_id = device.get("id", "")
                    self.state.active_device_name = device.get("name", "")

                    if on_update_callback:
                        on_update_callback({
                            "track": self.state.current_track_name,
                            "artist": self.state.current_artist,
                            "album_art": self.state.current_album_art,
                            "is_playing": self.state.is_playing,
                            "progress_ms": self.state.progress_ms,
                            "duration_ms": self.state.duration_ms,
                            "device": self.state.active_device_name,
                            "uri": new_uri,
                        })
            except (SpotifyNoActiveDevice, SpotifyError):
                pass
            except Exception as e:
                print(f"[SpotifyAgent] Poll error: {e}")

            await asyncio.sleep(5)

    # ── Settings Integration ───────────────────────────────────────────────────

    def get_spotify_settings(self) -> dict:
        """Read spotify block from settings.json."""
        try:
            if self._settings_path.exists():
                with open(self._settings_path, "r") as f:
                    return json.load(f).get("spotify", {})
        except Exception:
            pass
        return {}

    def _save_spotify_setting(self, key: str, value):
        """Persist a single spotify setting key."""
        try:
            settings = {}
            if self._settings_path.exists():
                with open(self._settings_path, "r") as f:
                    settings = json.load(f)
            if "spotify" not in settings:
                settings["spotify"] = {}
            settings["spotify"][key] = value
            with open(self._settings_path, "w") as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"[SpotifyAgent] Error saving setting '{key}': {e}")

    def save_preferred_device(self, device_id: str):
        self._save_spotify_setting("preferred_device_id", device_id)
