import logging
import os
import time
from io import BytesIO

from PIL import Image, ImageOps

from bot.utils.config import COVER_CACHE_DIR
from bot.utils.helpers import get_session

logger = logging.getLogger(__name__)


def deezer_get_hq_cover_by_query(title, artist=None):
    try:
        s = get_session()
        q = title
        if artist:
            q = f"{title} {artist}"
        params = {"q": q, "limit": 6}
        r = s.get("https://api.deezer.com/search", params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        if not data or not data.get("data"):
            return None
        for item in data.get("data", []):
            album = item.get("album")
            if album:
                cover = album.get("cover_xl") or album.get("cover_big") or album.get("cover")
                if cover:
                    return cover
        first = data.get("data")[0]
        album = first.get("album")
        if album:
            return album.get("cover_xl") or album.get("cover_big") or album.get("cover")
    except Exception as e:
        logger.warning(f"Deezer cover fetch failed: {e}")
    return None


def improve_cover_url(url):
    if not url:
        return None
    try:
        u = url.replace("1000x1000", "3000x3000").replace("640x640", "2000x2000")
        return u
    except Exception:
        return url


def download_and_ensure_min_size(url, min_size=1000, save_dir=COVER_CACHE_DIR, prefer_hq=False, title=None,
                                 artist=None):
    os.makedirs(save_dir, exist_ok=True)
    session = get_session()

    # Step 1: Always and only search for a cover on Deezer if a title is provided.
    deezer_cover_url = None
    if title:
        try:
            deezer_cover_url = deezer_get_hq_cover_by_query(title, artist)
        except Exception as e:
            logger.warning(f"An exception occurred during Deezer search: {e}")

    # Step 2: If no cover is found on Deezer, return None immediately.
    if not deezer_cover_url:
        logger.info(f"No cover found on Deezer for '{title}'. Skipping cover processing.")
        return None

    # Step 3: Process the image found exclusively from Deezer.
    u = improve_cover_url(deezer_cover_url)
    try:
        r = session.get(u, stream=True, timeout=15)
        r.raise_for_status()
        img_bytes = r.content
        if not img_bytes or len(img_bytes) < 1024:
            raise ValueError("image content too small")
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        logger.warning(f"Failed to download or open image from {u}: {e}")
        return None

    try:
        resample = getattr(Image, "LANCZOS", Image.BICUBIC)
        if img.width < min_size or img.height < min_size:
            img = ImageOps.fit(img, (min_size, min_size), resample)
        else:
            target = max(min_size, min(img.width, img.height))
            img = ImageOps.fit(img, (target, target), resample)
            if img.width < min_size or img.height < min_size:
                img = ImageOps.fit(img, (min_size, min_size), resample)
        filename = os.path.join(save_dir, f"cover_{int(time.time() * 1000)}.jpg")
        img.save(filename, format="JPEG", quality=92)
        return filename
    except Exception as e:
        logger.warning(f"Image processing failed for {u}: {e}")
        return None