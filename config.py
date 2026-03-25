"""
TOPFORM LINE Bot - Configuration
公式LINE Bot 設定管理モジュール
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


class Settings:
    """Application settings loaded from environment variables."""

    # LINE Messaging API
    LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")
    ADMIN_USER_ID: str = os.getenv("ADMIN_USER_ID", "")

    # Google Calendar API
    GOOGLE_CREDENTIALS_JSON: str = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Timezone
    TIMEZONE: str = "Asia/Tokyo"

    # 石原早見表 Web URL (既存の ishihara-booking Vercelサイト)
    HAYAMIHYO_URL: str = os.getenv("HAYAMIHYO_URL", "https://ishihara-booking.vercel.app")

    # Database (予約履歴用)
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./topform_line.db")

    # Google Sheets (顧客マスタ)
    GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID", "17jOb7Jh8xIlsmG9RJjdc0GUKykBVxEVkxpyw92sWkjk")

    # Business rules (also exported as module-level constants below)
    BOOKING_DEADLINE_HOURS = 12
    URGENT_CONTACT_DEADLINE_HOURS = 3

    @classmethod
    def validate(cls) -> list[str]:
        """Validate required settings and return list of missing ones."""
        missing = []
        if not cls.LINE_CHANNEL_ACCESS_TOKEN:
            missing.append("LINE_CHANNEL_ACCESS_TOKEN")
        if not cls.LINE_CHANNEL_SECRET:
            missing.append("LINE_CHANNEL_SECRET")
        if not cls.GOOGLE_CREDENTIALS_JSON:
            missing.append("GOOGLE_CREDENTIALS_JSON")
        return missing


# Singleton instance
settings = Settings()


# ============================================================
# Google Calendar IDs (from ishihara-booking)
# ============================================================
CALENDAR_IDS = {
    "ishihara_work": "j.ishihara@topform.jp",
    "ishihara_private": "junnya1995@gmail.com",
    "ebisu": "ebisu@topform.jp",
    "hanzoomon": "light@topform.jp",
}

# ============================================================
# Business rules (module-level constants for import compatibility)
# ============================================================
SESSION_DURATION = 60  # minutes
TRAVEL_TIME = 60  # minutes (恵比寿⇔半蔵門の移動時間)
BOOKING_DEADLINE_HOURS = 12  # 予約変更・キャンセル締切（1回消化）：12時間前
URGENT_CONTACT_DEADLINE_HOURS = 3  # 直前連絡デッドライン（管理者通知）：3時間前
ADVANCE_BOOKING_MONTHS = 2  # 2ヶ月先まで予約可

# 営業時間
BUSINESS_HOURS = {
    "weekday": {"start": 8, "end": 23},  # 最終枠 22:00
    "weekend": {"start": 9, "end": 20},  # 最終枠 19:00
}

# 恵比寿店：Room A, Room B (2部屋)
# 半蔵門店：最大3名同時
STORE_CAPACITY = {
    "ebisu": {"type": "rooms", "rooms": ["A", "B"]},
    "hanzoomon": {"type": "max", "max": 3},
}

# 祝日リスト
HOLIDAYS = {
    2025: [
        "2025-01-01", "2025-01-13", "2025-02-11", "2025-02-23", "2025-02-24",
        "2025-03-20", "2025-04-29", "2025-05-03", "2025-05-04", "2025-05-05",
        "2025-05-06", "2025-07-21", "2025-08-11", "2025-09-15", "2025-09-23",
        "2025-10-13", "2025-11-03", "2025-11-23", "2025-11-24",
    ],
    2026: [
        "2026-01-01", "2026-01-12", "2026-02-11", "2026-02-23", "2026-02-24",
        "2026-03-20", "2026-04-29", "2026-05-03", "2026-05-04", "2026-05-05",
        "2026-05-06", "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22",
        "2026-09-23", "2026-10-12", "2026-11-03", "2026-11-23",
    ],
}

# 強制休業日
FORCED_CLOSED_DAYS = ["2026-02-24"]

# ============================================================
# TOPFORM detection patterns (from booking-logic.ts)
# ============================================================
TOPFORM_PATTERNS = [
    r"topform.*石原.*淳哉",
    r"topform.*石原\s*淳哉",
    r"topform.*石原.*淳哉.*hallel",
    r"topform.*石原.*淳",
]

# ============================================================
# 休日判定キーワード (終日イベント)
# ============================================================
BLOCKING_KEYWORDS = ["休日", "休み", "OFF", "off", "祝日"]
UNAVAILABLE_KEYWORD = "予約不可"

# ============================================================
# Bot persona
# ============================================================
BOT_NAME = "TOPFORM予約Bot"
STORE_NAMES = {
    "ebisu": "恵比寿店",
    "hanzoomon": "半蔵門店",
}

