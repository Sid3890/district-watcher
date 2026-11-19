import os
from pathlib import Path

# Paths
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
STATIC_DIR = PROJECT_DIR / "static"
DB_PATH = DATA_DIR / "watcher.db"
BROWSER_STATE_PATH = DATA_DIR / "browser_state.json"
DEBUG_SCREENSHOT_PATH = DATA_DIR / "debug_error.png"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Web & Server Settings
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# District URL
DISTRICT_BASE_URL = "https://www.district.in"
DISTRICT_MOVIES_URL = "https://www.district.in/movies/"

# Polling intervals
DEFAULT_POLL_INTERVAL_SECONDS = 45
MIN_POLL_INTERVAL_SECONDS = 25
POLL_JITTER_SECONDS = 10  # 45 +/- 10 -> [35, 55]
BACKOFF_DELAY_SECONDS = 300  # 5 minutes on rate limit (429/403)

# Playwright Browser Configuration
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")
VIEWPORT = {"width": 1366, "height": 768}
TIMEZONE = "Asia/Kolkata"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Blocked resource domains to accelerate scraping
BLOCKED_DOMAINS = [
    "google-analytics.com",
    "doubleclick.net",
    "googletagmanager.com",
    "facebook.net",
    "clarity.ms",
    "hotjar.com",
    "adroll.com",
    "criteo.net",
    "mixpanel.com",
    "segment.io",
]
