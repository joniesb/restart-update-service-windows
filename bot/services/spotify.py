import logging
from datetime import datetime, timedelta, timezone

import requests

from bot.utils.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from bot.utils.helpers import get_session

logger = logging.getLogger(__name__)

SPOTIFY_TOKEN = None
SPOTIFY_EXPIPIRES = datetime.now(timezone.utc)


def spotify_authenticate():
    global SPOTIFY_TOKEN, SPOTIFY_EXPIPIRES
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    if SPOTIFY_TOKEN and datetime.now(timezone.utc) < SPOTIFY_EXPIPIRES - timedelta(seconds=10):
        return SPOTIFY_TOKEN
    token_url = "https://accounts.spotify.com/api/token"
    try:
        r = requests.post(token_url, data={"grant_type": "client_credentials"},
                          auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET), timeout=10)
        r.raise_for_status()
        d = r.json()
        SPOTIFY_TOKEN = d.get("access_token")
        expires_in = int(d.get("expires_in", 3600))
        SPOTIFY_EXPIPIRES = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        return SPOTIFY_TOKEN
    except Exception as e:
        logger.warning(f"Spotify auth failed: {e}")
        return None


def spotify_get(url, params=None):
    token = spotify_authenticate()
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, params=params or {}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"Spotify GET failed: {e} URL={url}")
        return None


def spotify_search(query, type_="album,track", limit=5):
    base = "https://api.spotify.com/v1/search"
    params = {"q": query, "type": type_, "limit": limit}
    return spotify_get(base, params)


def spotify_get_album(album_id):
    url = f"https://api.spotify.com/v1/albums/{album_id}"
    data = spotify_get(url)
    if not data:
        return None
    try:
        track_objs = data.get("tracks", {}) or {}
        href = track_objs.get("href") or f"https://api.spotify.com/v1/albums/{album_id}/tracks"
        limit = 50
        offset = 0
        all_items = []
        while True:
            page = spotify_get(href, params={"limit": limit, "offset": offset})
            if not page:
                break
            items = page.get("items", [])
            all_items.extend(items)
            if not page.get("next"):
                break
            offset += limit
        if all_items:
            data["tracks"]["items"] = all_items
    except Exception as e:
        logger.warning(f"Error paginating album tracks: {e}")
    return data


def spotify_album_to_details(album_json):
    if not album_json:
        return None
    title = album_json.get("name", "")
    artists = album_json.get("artists", [])
    artist = ", ".join(a.get("name") for a in artists) if artists else ""
    release_date_raw = album_json.get("release_date", "")
    release_date = ".".join(release_date_raw.split("-")) if release_date_raw else ""
    images = album_json.get("images", []) or []
    cover_url = images[0].get("url") if images else None
    total_tracks = album_json.get("total_tracks") or len(album_json.get("tracks", {}).get("items", []))
    raw_items = album_json.get("tracks", {}).get("items", []) or []

    processed_tracks = []
    for t in raw_items:
        disc = t.get("disc_number", 1)
        track_no = t.get("track_number") or None
        name = t.get("name") or "نامشخص"
        duration_ms = t.get("duration_ms")
        duration = None
        if duration_ms:
            sec = int(duration_ms) // 1000
            duration = f"{sec // 60}:{str(sec % 60).zfill(2)}"
        processed_tracks.append({
            "disc": int(disc) if disc is not None else 1,
            "track_number": int(track_no) if track_no is not None else None,
            "name": name.strip(),
            "duration": duration
        })
    processed_tracks.sort(key=lambda x: (x["disc"], (x["track_number"] if x["track_number"] is not None else 9999)))
    discs = {}
    for t in processed_tracks:
        discs.setdefault(t["disc"], []).append(t)

    if len(discs) <= 1:
        disc_tracks = []
        for t in processed_tracks:
            if t["track_number"] is not None:
                line = f"{str(t['track_number']).zfill(2)}. {t['name']}"
                # include duration with hyphen if exists
                if t.get("duration"):
                    line += f" - {t['duration']}"
                disc_tracks.append(line)
            else:
                disc_tracks.append(t['name'])
        final_tracklist = disc_tracks
    else:
        final_tracklist = []
        for disc_num in sorted(discs.keys()):
            lines = []
            for t in discs[disc_num]:
                if t["track_number"] is not None:
                    line = f"{str(t['track_number']).zfill(2)}. {t['name']}"
                    if t.get("duration"):
                        line += f" - {t['duration']}"
                    lines.append(line)
                else:
                    lines.append(t['name'])
            final_tracklist.append(lines)

    return {
        "title": title,
        "artist": artist,
        "release_date": release_date,
        "tracklist": final_tracklist,
        "cover_url": cover_url,
        "url": album_json.get("external_urls", {}).get("spotify"),
        "is_album": True,
        "tracks_total": total_tracks,
        "spotify_id": album_json.get("id")
    }


def spotify_get_track(track_id):
    url = f"https://api.spotify.com/v1/tracks/{track_id}"
    return spotify_get(url)


def try_spotify_lookup(query):
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    res = spotify_search(query, type_="album", limit=4)
    albums = res.get("albums", {}).get("items", []) if res else []
    if albums:
        album = albums[0]
        album_full = spotify_get_album(album.get("id"))
        details = spotify_album_to_details(album_full)
        return details
    res2 = spotify_search(query, type_="track", limit=4)
    tracks = res2.get("tracks", {}).get("items", []) if res2 else []
    if tracks:
        t = tracks[0]
        artist = ", ".join(a.get("name") for a in t.get("artists", []))
        cover_url = t.get("album", {}).get("images", [{}])[0].get("url")
        return {
            "title": t.get("name"),
            "artist": artist,
            "release_date": t.get("album", {}).get("release_date") or "",
            "tracklist": [],
            "cover_url": cover_url,
            "url": t.get("external_urls", {}).get("spotify"),
            "is_album": False,
            "tracks_total": 1
        }
    return None