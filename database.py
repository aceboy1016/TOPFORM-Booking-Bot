"""
TOPFORM LINE Bot - Database
予約履歴とユーザー情報を管理するSQLiteデータベース
"""

import aiosqlite
from datetime import datetime
from typing import Optional
import pytz

JST = pytz.timezone("Asia/Tokyo")

DATABASE_PATH = "./topform_line.db"


class Database:
    """SQLite database for user and booking management."""

    def __init__(self):
        self._db_path = DATABASE_PATH

    async def init_db(self):
        """Initialize database tables."""
        async with aiosqlite.connect(self._db_path) as db:
            # Users table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_user_id TEXT UNIQUE NOT NULL,
                    display_name TEXT,
                    preferred_store TEXT DEFAULT 'ebisu',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Bookings table (予約リクエスト履歴)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_user_id TEXT NOT NULL,
                    store TEXT NOT NULL,
                    slot_datetime TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at TIMESTAMP,
                    cancelled_at TIMESTAMP,
                    FOREIGN KEY (line_user_id) REFERENCES users(line_user_id)
                )
            """)

            # User sessions table (会話フローの状態管理)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_user_id TEXT UNIQUE NOT NULL,
                    flow_type TEXT,
                    flow_state TEXT,
                    flow_data TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (line_user_id) REFERENCES users(line_user_id)
                )
            """)

            # Check if metadata column exists in bookings
            cursor = await db.execute("PRAGMA table_info(bookings)")
            columns = [col[1] for col in await cursor.fetchall()]
            if "metadata" not in columns:
                await db.execute("ALTER TABLE bookings ADD COLUMN metadata TEXT")
                print("✅ Added metadata column to bookings table")

            await db.commit()
            print("✅ Database initialized")

    async def get_or_create_user(
        self, line_user_id: str, display_name: Optional[str] = None
    ) -> dict:
        """Get or create a user record."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE line_user_id = ?", (line_user_id,)
            )
            row = await cursor.fetchone()

            if row:
                user = dict(row)
                # Update display name if provided and different
                if display_name and display_name != user.get("display_name"):
                    await db.execute(
                        "UPDATE users SET display_name = ?, updated_at = ? WHERE line_user_id = ?",
                        (display_name, datetime.now(JST).isoformat(), line_user_id),
                    )
                    await db.commit()
                    user["display_name"] = display_name
                return user
            else:
                await db.execute(
                    "INSERT INTO users (line_user_id, display_name) VALUES (?, ?)",
                    (line_user_id, display_name or "Unknown"),
                )
                await db.commit()
                cursor = await db.execute(
                    "SELECT * FROM users WHERE line_user_id = ?", (line_user_id,)
                )
                row = await cursor.fetchone()
                return dict(row)

    async def save_booking(
        self,
        line_user_id: str,
        store: str,
        slot_datetime: str,
        status: str = "confirmed",
        metadata: Optional[dict] = None,
    ) -> int:
        """Save a booking record."""
        import json
        metadata_json = json.dumps(metadata) if metadata else None

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO bookings (line_user_id, store, slot_datetime, status, confirmed_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    line_user_id,
                    store,
                    slot_datetime,
                    status,
                    datetime.now(JST).isoformat() if status == "confirmed" else None,
                    metadata_json,
                ),
            )
            await db.commit()
            return cursor.lastrowid

    async def get_user_bookings(
        self, line_user_id: str, include_past: bool = False
    ) -> list[dict]:
        """Get bookings for a specific user."""
        import json
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            now = datetime.now(JST).isoformat()

            if include_past:
                cursor = await db.execute(
                    """SELECT * FROM bookings 
                       WHERE line_user_id = ? AND status != 'cancelled'
                       ORDER BY slot_datetime DESC LIMIT 20""",
                    (line_user_id,),
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM bookings 
                       WHERE line_user_id = ? AND status != 'cancelled' AND slot_datetime >= ?
                       ORDER BY slot_datetime ASC""",
                    (line_user_id, now),
                )

            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                # Parse metadata JSON
                if "metadata" in d.keys() and d["metadata"]:
                    try:
                        d["metadata"] = json.loads(d["metadata"])
                    except:
                        d["metadata"] = {}
                else:
                    d["metadata"] = {}
                results.append(d)
            return results
            return [dict(row) for row in rows]

    async def cancel_booking(self, booking_id: int, line_user_id: str) -> bool:
        """Cancel a booking."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """UPDATE bookings SET status = 'cancelled', cancelled_at = ?
                   WHERE id = ? AND line_user_id = ?""",
                (datetime.now(JST).isoformat(), booking_id, line_user_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    # Session management
    async def get_session(self, line_user_id: str) -> Optional[dict]:
        """Get the current session for a user."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM sessions WHERE line_user_id = ?", (line_user_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def set_session(
        self,
        line_user_id: str,
        flow_type: str,
        flow_state: str,
        flow_data: str = "{}",
    ):
        """Set or update the current session for a user."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO sessions (line_user_id, flow_type, flow_state, flow_data, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(line_user_id)
                   DO UPDATE SET flow_type = ?, flow_state = ?, flow_data = ?, updated_at = ?""",
                (
                    line_user_id,
                    flow_type,
                    flow_state,
                    flow_data,
                    datetime.now(JST).isoformat(),
                    flow_type,
                    flow_state,
                    flow_data,
                    datetime.now(JST).isoformat(),
                ),
            )
            await db.commit()

    async def clear_session(self, line_user_id: str):
        """Clear the current session for a user."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM sessions WHERE line_user_id = ?", (line_user_id,)
            )
            await db.commit()


# Singleton instance
db = Database()
