import json
import logging
import random
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from bot.utils.config import GENIUS_TOKEN
from bot.utils.helpers import get_session, _cache_get, _cache_set, _GENIUS_LINK_CACHE, _GENIUS_LINK_CACHE_CAPACITY

logger = logging.getLogger(__name__)

GENIUS_API_BASE = "https://api.genius.com"


def genius_search(query, max_results=7):
    headers = {"Authorization": f"Bearer {GENIUS_TOKEN}"}
    params = {"q": query}
    try:
        r = requests.get(urljoin(GENIUS_API_BASE, "/search"), headers=headers, params=params, timeout=10)
        r.raise_for_status()
        hits = r.json().get("response", {}).get("hits", [])
    except Exception as e:
        logger.warning(f"Genius search failed: {e}")
        return []
    results = []
    for hit in hits[:max_results]:
        res = hit.get("result", {})
        results.append({
            "id": res.get("id"),
            "full_title": res.get("full_title"),
            "title": res.get("title"),
            "artist": res.get("primary_artist", {}).get("name"),
            "url": res.get("url"),
            "cover": res.get("song_art_image_url"),
            "type": res.get("type", "song")
        })
    return results


def find_best_genius_link(title, artist):
    if not title:
        return None
    q = f"{title} {artist or ''}".strip()
    cache_key = (q or title).lower()
    cached = _cache_get(_GENIUS_LINK_CACHE, cache_key)
    if cached is not None:
        return cached or None
    try:
        hits = genius_search(q, max_results=6)
        if not hits:
            hits = genius_search(title, max_results=6)
        title_l = (title or "").lower()
        artist_l = (artist or "").lower()
        best = None
        best_score = -1
        for h in hits:
            score = 0
            if title_l and (title_l in (h.get("full_title") or "").lower() or title_l in (h.get("title") or "").lower()):
                score += 2
            if artist_l and artist_l in (h.get("artist") or "").lower():
                score += 2
            if title_l and artist_l and (
                    title_l in (h.get("full_title") or "").lower()) and (
                    artist_l in (h.get("full_title") or "").lower()):
                score += 1
            if score > best_score:
                best_score = score
                best = h
        if best:
            best_url = best.get("url")
            _cache_set(_GENIUS_LINK_CACHE, cache_key, best_url, _GENIUS_LINK_CACHE_CAPACITY)
            return best_url
    except Exception as e:
        logger.warning(f"Genius best link error: {e}")
    _cache_set(_GENIUS_LINK_CACHE, cache_key, None, _GENIUS_LINK_CACHE_CAPACITY)
    return None


def scrape_song_details_from_url(song_url):
    time.sleep(random.uniform(1.0, 2.0))
    s = get_session()
    try:
        r = s.get(song_url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        json_ld_tag = soup.find('script', type='application/ld+json')
        if not json_ld_tag or not json_ld_tag.string:
            return None
        data = json.loads(json_ld_tag.string)
    except Exception as e:
        logger.warning(f"Genius scrape failed: {e}")
        return None

    title = data.get('name', '').replace(' Lyrics', '').strip() if data.get('name') else None
    cover_url = data.get('image')
    release_date = data.get('datePublished')
    artist = "نامشخص"
    if data.get('byArtist'):
        artist_info = data['byArtist'][0] if isinstance(data['byArtist'], list) else data['byArtist']
        artist = artist_info.get('name')
    elif data.get('creator'):
        artist = data['creator'].get('name')
    if cover_url:
        cover_url = re.sub(r'\.\d+x\d+x\d+\.png', '.1000x1000x1.png', cover_url)
    is_album = data.get('@type') in ['MusicAlbum', 'Album', 'EP']
    tracks = []
    formatted_date = ""
    if release_date:
        from datetime import datetime
        try:
            dt_obj = datetime.strptime(release_date, '%Y-%m-%d')
            formatted_date = dt_obj.strftime('%Y.%m.%d')
        except Exception:
            formatted_date = release_date
    return {
        "title": title,
        "artist": artist,
        "url": song_url,
        "cover_url": cover_url,
        "type": data.get('@type', "Song"),
        "release_date": formatted_date,
        "tracklist": tracks,
        "is_album": is_album
    }