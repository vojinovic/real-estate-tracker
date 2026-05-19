"""Konfiguracija za real-estate-tracker."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "tracker.db"

# Email config (Gmail App Password)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# Scraper config
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

REQUEST_TIMEOUT = 20
MIN_DELAY_SECONDS = 3
MAX_DELAY_SECONDS = 8

# Posle koliko uzastopnih grešaka oglas se markira kao "nestao"
ERROR_THRESHOLD_FOR_UNAVAILABLE = 3

# Da li koristimo Playwright kao fallback kad requests pukne
USE_PLAYWRIGHT_FALLBACK = True
