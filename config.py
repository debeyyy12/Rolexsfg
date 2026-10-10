"""
Configuration & Environment Variables
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ========== BOT CONFIG ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8390444092:AAF11Znyxs1ayPuDG7DlCcsSQFVnmpGErus")
OWNER_ID = int(os.environ.get("OWNER_ID", "8128821116"))
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "8128821116").split(",") if x.strip()]

# ========== WELCOME ==========
WELCOME_IMAGE = os.environ.get(
    "WELCOME_IMAGE",
    "https://kommodo.ai/i/wqVc4u68cErtebyE6okA"
)

# ========== WEB SERVER ==========
PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
USE_WEBHOOK = os.environ.get("USE_WEBHOOK", "false").lower() == "true"

# ========== DATABASE ==========
DATABASE_URL = os.environ.get("DATABASE_URL", "")
# Convert Heroku-style postgres:// to postgresql:// for asyncpg
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

SQLITE_DB_PATH = os.environ.get(
    "SQLITE_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bomber.db")
)

# ========== PLANS ==========
PLANS = {
    "standard": {
        "name": "Standard",
        "price": 149,
        "days": 30,
        "concurrent": 2,
        "max_duration": 300,
    },
    "premium": {
        "name": "Premium",
        "price": 249,
        "days": 30,
        "concurrent": 5,
        "max_duration": 720,
    },
    "ultimate": {
        "name": "Ultimate",
        "price": 349,
        "days": 30,
        "concurrent": 10,
        "max_duration": 720,
    },
}
