"""
mood_music_mapper.py — Maps Vyra's emotion tags to Spotify playback behaviour
==============================================================================
Called by vyra.py whenever the AI emits an [EMOTION:tag] token.
Also wired to PerceptionManager music-detection events in server.py.
"""
import asyncio
import random
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from spotify_agent import SpotifyAgent  # type: ignore

# ── Mood → Music Config ────────────────────────────────────────────────────────
# Each entry defines:
#   keywords   : Spotify search strings (one chosen randomly)
#   shuffle    : bool — shuffle state
#   repeat     : 'track' | 'context' | 'off'
#   volume_delta : integer — adjust current volume by this amount (-100 to 100)

MOOD_MUSIC_MAP: dict[str, dict] = {
    "happy": {
        "keywords": ["happy hits", "feel good pop", "upbeat vibes", "good mood playlist"],
        "shuffle": True,
        "repeat": "context",
        "volume_delta": 0,
    },
    "playful": {
        "keywords": ["fun pop hits", "dance party", "good vibes only", "happy indie"],
        "shuffle": True,
        "repeat": "context",
        "volume_delta": 5,
    },
    "sad": {
        "keywords": ["sad songs", "acoustic heartbreak", "emotional songs", "sad indie"],
        "shuffle": False,
        "repeat": "track",
        "volume_delta": 0,
    },
    "cry": {
        "keywords": ["crying songs", "sad acoustic", "heartbreak ballads"],
        "shuffle": False,
        "repeat": "track",
        "volume_delta": -5,
    },
    "loving": {
        "keywords": ["love songs playlist", "romantic vibes", "couple songs"],
        "shuffle": False,
        "repeat": "context",
        "volume_delta": -10,
    },
    "love": {
        "keywords": ["romantic playlist", "love songs", "sweet love music"],
        "shuffle": False,
        "repeat": "context",
        "volume_delta": -10,
    },
    "shy": {
        "keywords": ["soft indie", "lo-fi chill", "cozy playlist"],
        "shuffle": False,
        "repeat": "context",
        "volume_delta": -15,
    },
    "caring": {
        "keywords": ["warm acoustic", "feel warm playlist", "soft pop"],
        "shuffle": False,
        "repeat": "context",
        "volume_delta": -5,
    },
    "angry": {
        "keywords": ["hype beats", "angry metal", "intense playlist", "workout rage"],
        "shuffle": True,
        "repeat": "context",
        "volume_delta": 10,
    },
    "surprised": {
        "keywords": ["energetic pop", "upbeat discoveries", "feel alive playlist"],
        "shuffle": True,
        "repeat": "context",
        "volume_delta": 0,
    },
    "scared": {
        "keywords": ["calm anxiety relief", "peaceful ambient", "soothing music"],
        "shuffle": False,
        "repeat": "context",
        "volume_delta": -15,
    },
    "protective": {
        "keywords": ["powerful anthems", "empowerment songs", "strong vibes"],
        "shuffle": True,
        "repeat": "context",
        "volume_delta": 5,
    },
    "jealous": {
        "keywords": ["drama playlist", "intense pop", "emotional beats"],
        "shuffle": True,
        "repeat": "context",
        "volume_delta": 0,
    },
    "sleepy": {
        "keywords": ["sleep music", "ambient relaxation", "night lo-fi", "calm sleep playlist"],
        "shuffle": False,
        "repeat": "context",
        "volume_delta": -30,
    },
    "serious": {
        "keywords": ["focus music", "deep work instrumental", "concentration playlist"],
        "shuffle": False,
        "repeat": "context",
        "volume_delta": -10,
    },
    "thinking": {
        "keywords": ["lo-fi study beats", "focus instrumental", "deep thinking playlist"],
        "shuffle": False,
        "repeat": "context",
        "volume_delta": -10,
    },
    "disgusted": {
        "keywords": ["venting playlist", "alternative rock", "cathartic music"],
        "shuffle": True,
        "repeat": "context",
        "volume_delta": 0,
    },
    "neutral": {
        "keywords": ["chill vibes", "lo-fi hip hop", "easy listening"],
        "shuffle": True,
        "repeat": "context",
        "volume_delta": 0,
    },
}

# Per personality-mode overrides (applied on top of mood config)
PER_MODE_DEFAULTS: dict[str, dict] = {
    "girlfriend":   {"shuffle": True,  "repeat": "context", "volume_delta": 0},
    "bestfriend":   {"shuffle": True,  "repeat": "off",     "volume_delta": 5},
    "professional": {"shuffle": False, "repeat": "context", "volume_delta": -10},
}


def get_mood_config(emotion: str) -> dict:
    """Return the mood config for an emotion, falling back to 'neutral'."""
    return MOOD_MUSIC_MAP.get(emotion.lower(), MOOD_MUSIC_MAP["neutral"])


async def mood_sync(agent: "SpotifyAgent", emotion: str, personality_mode: str = "professional"):
    """
    Orchestrate a full mood-sync action:
      1. Search for a matching playlist
      2. Start playback on that playlist
      3. Set shuffle + repeat
      4. Adjust volume (if enabled in settings)
    Returns a dict describing what was done, for broadcasting to the frontend.
    """
    if not agent.state.connected:
        return {"skipped": True, "reason": "Spotify not connected"}

    settings = agent.get_spotify_settings()
    if not settings.get("mood_sync_enabled", True):
        return {"skipped": True, "reason": "Mood sync disabled"}

    config = get_mood_config(emotion)
    mode_defaults = PER_MODE_DEFAULTS.get(
        personality_mode, PER_MODE_DEFAULTS["professional"])

    # Choose a random search keyword
    keyword = random.choice(config["keywords"])
    print(f"[MoodSync] Emotion={emotion}, searching Spotify for: '{keyword}'")

    try:
        # 1. Search for playlist
        results = await agent.search(keyword, search_type="playlist", limit=5)
        playlists = results.get("playlists", {}).get("items", [])
        playlists = [p for p in playlists if p]  # Filter out None items

        if not playlists:
            print(f"[MoodSync] No playlists found for '{keyword}'")
            return {"skipped": True, "reason": "No playlists found"}

        playlist = playlists[0]
        playlist_uri = playlist["uri"]
        playlist_name = playlist["name"]

        # 2. Start playback (use preferred device if set)
        preferred_device = settings.get("preferred_device_id") or None
        await agent.play(context_uri=playlist_uri, device_id=preferred_device)

        # 3. Apply shuffle & repeat
        shuffle = config.get("shuffle", mode_defaults["shuffle"])
        repeat = config.get("repeat", mode_defaults["repeat"])
        await asyncio.gather(
            agent.set_shuffle(shuffle),
            agent.set_repeat(repeat),
        )

        # 4. Volume adjust
        volume_delta = config.get("volume_delta", 0)
        if settings.get("volume_mood_adjust", True) and volume_delta != 0:
            try:
                playback = await agent.get_playback()
                if playback and "device" in playback:
                    current_vol = playback["device"].get("volume_percent", 50)
                    new_vol = max(0, min(100, current_vol + volume_delta))
                    await agent.set_volume(new_vol)
            except Exception as ve:
                print(f"[MoodSync] Volume adjust failed: {ve}")

        agent.state.current_mood = emotion
        agent.state.mood_sync_active = True

        print(
            f"[MoodSync] Applied: playlist='{playlist_name}', shuffle={shuffle}, repeat={repeat}")
        return {
            "applied": True,
            "mood": emotion,
            "playlist": playlist_name,
            "playlist_uri": playlist_uri,
            "shuffle": shuffle,
            "repeat": repeat,
        }

    except Exception as e:
        print(f"[MoodSync] Error during mood sync: {e}")
        return {"skipped": True, "reason": str(e)}


async def create_vyra_mood_playlist(agent: "SpotifyAgent", emotion: str) -> Optional[str]:
    """
    Create a VYRA-curated playlist for a mood and populate it with 20 tracks.
    Returns the playlist ID or None on failure.
    """
    try:
        config = get_mood_config(emotion)
        keyword = config["keywords"][0]
        playlist_name = f"VYRA – {emotion.title()}"

        # Create the playlist
        playlist = await agent.create_playlist(
            name=playlist_name,
            description=f"Auto-created by VYRA for {emotion} mood 🎵",
            public=False,
        )
        playlist_id = playlist.get("id")
        if not playlist_id:
            return None

        # Search for tracks
        results = await agent.search(keyword, search_type="track", limit=20)
        tracks = results.get("tracks", {}).get("items", [])
        uris = [t["uri"] for t in tracks if t]

        if uris:
            await agent.add_tracks(playlist_id, uris)

        print(
            f"[MoodSync] Created playlist '{playlist_name}' with {len(uris)} tracks")
        return playlist_id

    except Exception as e:
        print(f"[MoodSync] Failed to create mood playlist: {e}")
        return None
