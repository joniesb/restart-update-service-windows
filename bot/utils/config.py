import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID", "")
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@FlyonSpace")

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN required in .env")
if not ADMIN_ID_STR:
    raise ValueError("ADMIN_ID required in .env")
if not GENIUS_TOKEN:
    raise ValueError("GENIUS_TOKEN required in .env")

ADMINS = [int(x.strip()) for x in ADMIN_ID_STR.split(",") if x.strip().isdigit()]

LOG_USER_REQUESTS = os.path.join("logs", "user_requests.log")
DATA_FILE = "music_data.json"
STATE_FILE = "bot_state.json"
COVER_CACHE_DIR = "cover_cache"
