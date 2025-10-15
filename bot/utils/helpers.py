import json
import logging
import os
import random
from collections import OrderedDict
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from bot.utils.config import LOG_USER_REQUESTS, STATE_FILE, DATA_FILE

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.3 Safari/605.1.15',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:99.0) Gecko/20100101 Firefox/99.0',
]

_SHARED_SESSION = None


def _build_shared_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
        "Connection": "keep-alive"
    })
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=40)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def get_session():
    global _SHARED_SESSION
    if _SHARED_SESSION is None:
        _SHARED_SESSION = _build_shared_session()
    return _SHARED_SESSION


def load_json_safe(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_safe(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_state = load_json_safe(STATE_FILE, {})
user_data = {int(k): v for k, v in _state.get("user_data", {}).items()} if _state.get("user_data") else {}
preview_messages = {int(k): v for k, v in _state.get("preview_messages", {}).items()} if _state.get(
    "preview_messages") else {}
custom_buttons = _state.get("custom_buttons", {}) or {}  # title -> url


def save_state():
    ud = {str(k): v for k, v in user_data.items()}
    pm = {str(k): v for k, v in preview_messages.items()}
    save_json_safe(STATE_FILE, {"user_data": ud, "preview_messages": pm, "custom_buttons": custom_buttons})


def log_user_request(user, qtype, query):
    os.makedirs(os.path.dirname(LOG_USER_REQUESTS), exist_ok=True)
    try:
        with open(LOG_USER_REQUESTS, "a", encoding="utf-8") as f:
            f.write(
                f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d | %H:%M:%S')}] User: @{user} | Type: {qtype} | Query: {query}\n")
    except Exception:
        pass


def add_to_stats(title, artist, uploader):
    data = load_json_safe(DATA_FILE, [])
    data.append({
        "title": title,
        "artist": artist,
        "uploader": uploader,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    })
    save_json_safe(DATA_FILE, data)


def glass_button(text, callback_data=None, url=None):
    from telegram import InlineKeyboardButton
    if url:
        return InlineKeyboardButton(f"🔹 {text}", url=url)
    return InlineKeyboardButton(f"🔹 {text}", callback_data=callback_data)


async def find_channel_id(bot, channel_link):
    from bot.utils.config import CHANNEL_USERNAME
    candidates = [channel_link, CHANNEL_USERNAME, CHANNEL_USERNAME.replace("@", "")]
    for c in candidates:
        try:
            chat = await bot.get_chat(c)
            return chat.id
        except Exception:
            continue
    return None


async def check_channel_access(bot):
    from bot.utils.config import CHANNEL_USERNAME
    import logging
    try:
        chat = await bot.get_chat(CHANNEL_USERNAME)
        admins = await bot.get_chat_administrators(CHANNEL_USERNAME)
        bot_user = await bot.get_me()
        bot_is_admin = any(admin.user.id == bot_user.id for admin in admins)
        logging.info(f"Channel ok: {chat.title} | Bot is admin: {bot_is_admin}")
        return True, chat, bot_is_admin
    except Exception as e:
        logging.warning(f"Channel access failed: {e}")
        return False, None, False


# small LRU cache for Genius best-link lookups
_GENIUS_LINK_CACHE: "OrderedDict[str, str]" = OrderedDict()
_GENIUS_LINK_CACHE_CAPACITY = 256


def _cache_get(cache: OrderedDict, key):
    val = cache.get(key)
    if val is not None:
        cache.move_to_end(key)
    return val


def _cache_set(cache: OrderedDict, key, value, capacity: int):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > capacity:
        cache.popitem(last=False)