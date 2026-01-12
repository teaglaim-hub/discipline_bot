import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")

DB_PATH = os.getenv("DB_PATH", "discipline.db")

ACHIEVEMENT_LEVELS = {
    1: "🙂",
    2: "😌",
    3: "😎",
    4: "🤩",
    5: "🔥",
    6: "👑",
}

ACHIEVEMENT_THRESHOLDS = [3, 7, 14, 30, 60, 100]