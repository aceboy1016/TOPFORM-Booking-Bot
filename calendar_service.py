"""
TOPFORM LINE Bot - Google Calendar Service
Google Calendar APIと連携して予約状況を取得・判定するサービス
既存の ishihara-booking (TypeScript) のロジックをPythonに移植
"""

import re
from datetime import datetime, timedelta
from typing import Optional, List
from dataclasses import dataclass
import base64
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import (
    settings,
    CALENDAR_IDS,
    SESSION_DURATION,
    TRAVEL_TIME,
    BOOKING_DEADLINE_HOURS,
    ADVANCE_BOOKING_MONTHS,
    BUSINESS_HOURS,
    STORE_CAPACITY,
    HOLIDAYS,
    FORCED_CLOSED_DAYS,
    TOPFORM_PATTERNS,
    BLOCKING_KEYWORDS,
    UNAVAILABLE_KEYWORD,
    STORE_NAMES,
)

import pytz

JST = pytz.timezone("Asia/Tokyo")


# ============================================================
# Data Models
# ============================================================
@dataclass
class Booking:
    id: str  # Add ID field for identification
    start_dt: datetime
    end_dt: datetime
    store: str  # 'ebisu' or 'hanzoomon'
    title: str
    description: str = ""
    room: Optional[str] = None  # 'A', 'B', or None (unknown)
    source: Optional[str] = None  # 'work', 'private', 'ebisu', 'hanzoomon'


@dataclass
class BookingData:
    ebisu: list[Booking]
    hanzoomon: list[Booking]
    ishihara: list[Booking]
    last_update: str = ""


class CalendarService:
    """Google Calendar API Service."""

    def __init__(self):
        self._service = None
        self._credentials = None

    async def initialize(self):
        """Async wrapper for initialization."""
        self.initialize_sync()

    def initialize_sync(self):
        """Initialize the Google Calendar API client synchronously."""
        if self._service:
            return  # Already initialized

        creds_json = settings.GOOGLE_CREDENTIALS_JSON
        if not creds_json:
            print("⚠️ GOOGLE_CREDENTIALS_JSON is not set, skipping Calendar init")
            return

        # Handle base64 encoded credentials if necessary
        if not creds_json.startswith("{"):
            import base64
            try:
                creds_json = base64.b64decode(creds_json).decode("utf-8")
            except Exception:
                pass

        try:
            creds_data = json.loads(creds_json)
        except json.JSONDecodeError as e:
            print(f"❌ JSON Decode Error: {e}")
            return

        credentials = service_account.Credentials.from_service_account_info(
            creds_data,
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        )
        self._credentials = credentials
        # Build is technically blocking but happens only once at startup
        self._service = build("calendar", "v3", credentials=credentials)

    def _fetch_events(
        self, calendar_id: str, time_min: str, time_max: str
    ) -> list[dict]:
        """Fetch events from a single calendar."""
        if not self._credentials:
            return []
        try:
            # 毎回新しいHTTP接続を生成して長期接続による切断を防ぐ
            import httplib2
            http = self._credentials.authorize(httplib2.Http())
            from googleapiclient.discovery import build
            service = build("calendar", "v3", http=http)
            result = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=2500,
                )
                .execute()
            )
            return result.get("items", [])
        except Exception as e:
            print(f"❌ Failed to fetch events from {calendar_id}: {e}")
            return []

    def _transform_event(self, event: dict, store: str, source: str = "work") -> Optional[Booking]:
        """Convert Google Calendar event to Booking object."""
        start = event.get("start", {})
        end = event.get("end", {})
        title = event.get("summary", "No Title")
        desc = event.get("description", "")
        evt_id = event.get("id", "")

        # Handle start/end time parsing
        try:
            if start.get("dateTime"):
                 start_dt = datetime.fromisoformat(start["dateTime"])
            elif start.get("date"):
                # All-day event logic
                if any(k in title for k in BLOCKING_KEYWORDS):
                    start_dt = datetime.strptime(start["date"], "%Y-%m-%d").replace(tzinfo=JST)
                else:
                    return None # Ignore non-blocking all-day
            else:
                return None

            if end.get("dateTime"):
                end_dt = datetime.fromisoformat(end["dateTime"])
            elif end.get("date"):
                end_dt = datetime.strptime(end["date"], "%Y-%m-%d").replace(tzinfo=JST)
                if not any(k in title for k in BLOCKING_KEYWORDS):
                     return None # Ignore non-blocking

            # Parse Room (Ebisu only)
            room = None
            if store == "ebisu":
                if "個室A" in title or "Room A" in title or "個室A" in desc:
                    room = "A"
                elif "個室B" in title or "Room B" in title or "個室B" in desc:
                    room = "B"

            return Booking(
                id=evt_id,
                start_dt=start_dt,
                end_dt=end_dt,
                store=store,
                title=title,
                description=desc,
                room=room,
                source=source
            )
        except (ValueError, TypeError):
            return None

    def fetch_all_bookings(self) -> BookingData:
        """Fetch all bookings from all calendars."""
        if not self._service:
            # Assumed caller awaited initialize() already, or fallback to sync
            self.initialize_sync()
            if not self._service:
                return BookingData(ebisu=[], hanzoomon=[], ishihara=[])

        now = datetime.now(JST)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        time_min = today.isoformat()
        time_max = (today + timedelta(days=ADVANCE_BOOKING_MONTHS * 30)).isoformat()

        # Fetch raw events
        ebisu_events = self._fetch_events(CALENDAR_IDS["ebisu"], time_min, time_max)
        hanzomon_events = self._fetch_events(CALENDAR_IDS["hanzoomon"], time_min, time_max)
        work_events = self._fetch_events(CALENDAR_IDS["ishihara_work"], time_min, time_max)
        private_events = self._fetch_events(CALENDAR_IDS["ishihara_private"], time_min, time_max)

        # Transform
        ebisu_bookings = []
        for ev in ebisu_events:
            b = self._transform_event(ev, "ebisu", "ebisu")
            if b: ebisu_bookings.append(b)

        hanzomon_bookings = []
        for ev in hanzomon_events:
            b = self._transform_event(ev, "hanzoomon", "hanzoomon")
            if b: hanzomon_bookings.append(b)
            
        ishihara_bookings = []
        for ev in work_events:
            # Detect store from title
            store = "unknown"
            title = ev.get("summary", "")
            if "(半)" in title or "（半）" in title: store = "hanzoomon"
            elif "(恵)" in title or "（恵）" in title: store = "ebisu"
            
            b = self._transform_event(ev, store, "work")
            if b: ishihara_bookings.append(b)
            
        for ev in private_events:
            b = self._transform_event(ev, "unknown", "private")
            if b: ishihara_bookings.append(b)

        return BookingData(
            ebisu=ebisu_bookings,
            hanzoomon=hanzomon_bookings,
            ishihara=ishihara_bookings,
            last_update=datetime.now(JST).isoformat()
        )

    def fetch_user_past_bookings_this_month(self, user_name: str) -> list:
        """
        今月1日〜昨日までの、指定ユーザーの予約をカレンダーから取得する。
        今月の利用回数カウント用。
        Returns a list of Booking objects.
        """
        if not self._service:
            self.initialize_sync()
            if not self._service:
                return []

        now = datetime.now(JST)
        # 今月1日の0時
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # 今日の0時（過去分のみ）
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # 今日が月初なら過去分は0件
        if month_start >= today_start:
            return []

        time_min = month_start.isoformat()
        time_max = today_start.isoformat()

        work_events = self._fetch_events(CALENDAR_IDS["ishihara_work"], time_min, time_max)

        matches = []
        normalized_user_name = user_name.replace(" ", "").replace("　", "")
        
        for ev in work_events:
            title = ev.get("summary", "")
            if normalized_user_name not in title.replace(" ", "").replace("　", ""):
                continue
            store = "unknown"
            if "(半)" in title or "（半）" in title:
                store = "hanzoomon"
            elif "(恵)" in title or "（恵）" in title:
                store = "ebisu"
            b = self._transform_event(ev, store, "work")
            if b:
                matches.append(b)

        matches.sort(key=lambda b: b.start_dt)
        return matches


# Singleton instance
calendar_service = CalendarService()

def get_slot_status(
    slot_time: datetime,
    store: str,
    all_bookings: BookingData,
    duration_min: int = 60
) -> dict:
    """
    Get detailed status of a slot.
    Returns:
        {
            "is_available": bool,
            "reason": str,
            "rooms_available": ["A", "B"], 
            "conflict_count": int
        }
    """
    slot_end = slot_time + timedelta(minutes=duration_min)
    
    # 1. Check Capacity
    if store == "ebisu":
        bookings = all_bookings.ebisu
        max_cap = 2
    elif store == "hanzoomon":
        bookings = all_bookings.hanzoomon
        max_cap = 3
    else:
        return {"is_available": False, "reason": "Unknown Store", "rooms_available": []}
        
    # 2. Check Overlap
    overlapping = []
    for b in bookings:
        if max(slot_time, b.start_dt) < min(slot_end, b.end_dt):
             if any(k in b.title for k in BLOCKING_KEYWORDS):
                 return {"is_available": False, "reason": "Blocked", "rooms_available": []}
             overlapping.append(b)

    # 3. Analyze Rooms (Ebisu)
    rooms_available = []
    if store == "ebisu":
        taken_rooms = set()
        for b in overlapping:
            if b.room:
                taken_rooms.add(b.room)
        
        if "A" not in taken_rooms:
            rooms_available.append("A")
        if "B" not in taken_rooms:
            rooms_available.append("B")
            
        conflict_count = len(overlapping)
        if conflict_count >= max_cap:
             return {"is_available": False, "reason": "Full", "rooms_available": [], "conflict_count": conflict_count}
             
    else: # Hanzoomon
        conflict_count = len(overlapping)
        if conflict_count >= max_cap:
             return {"is_available": False, "reason": "Full", "rooms_available": []}
        rooms_available = ["Any"] * (max_cap - conflict_count)

    return {
        "is_available": True,
        "reason": "OK",
        "rooms_available": rooms_available,
        "conflict_count": len(overlapping)
    }

def _get_detailed_store_status(
    slot_time: datetime,
    store: str,
    all_bookings: BookingData,
) -> dict:
    """Get detailed availability status including room info."""
    slot_end = slot_time + timedelta(minutes=60)
    
    if store == "ebisu":
        overlapping = []
        for b in all_bookings.ebisu:
            if max(slot_time, b.start_dt) < min(slot_end, b.end_dt):
                overlapping.append(b)
        
        taken_rooms = set()
        for b in overlapping:
            if b.room:
                taken_rooms.add(b.room)
        
        rooms_avail = []
        if "A" not in taken_rooms:
            rooms_avail.append("A")
        if "B" not in taken_rooms:
            rooms_avail.append("B")
            
        is_full = len(overlapping) >= 2
        return {"is_full": is_full, "rooms_available": rooms_avail}
    else:
        overlapping = []
        for b in all_bookings.hanzoomon:
            if max(slot_time, b.start_dt) < min(slot_end, b.end_dt):
                overlapping.append(b)
        is_full = len(overlapping) >= 3
        rooms_avail = ["Any"] * (3 - len(overlapping)) if not is_full else []
        return {"is_full": is_full, "rooms_available": rooms_avail}

def is_topform_ishihara_booking(title: str) -> bool:
    """Detect if an event is a TOPFORM-related hold."""
    if not title: return False
    normalized = re.sub(r"\s+", " ", title).lower()
    for pattern in TOPFORM_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
    return False

def is_trainer_busy(
    slot_time: datetime,
    ishihara_bookings: list[Booking],
    all_bookings: BookingData,
) -> bool:
    """Check if the trainer has a conflicting booking."""
    slot_end = slot_time + timedelta(minutes=SESSION_DURATION)
    
    for b in ishihara_bookings:
        # Overlap check
        if max(slot_time, b.start_dt) < min(slot_end, b.end_dt):
            # Ignore if it's a TOPFORM hold without real work content
            if is_topform_ishihara_booking(b.title):
                # Search for any real work booking (source='work' or other) in the same time
                has_real_work = False
                for wb in all_bookings.ishihara:
                    if wb.id != b.id and max(b.start_dt, wb.start_dt) < min(b.end_dt, wb.end_dt):
                        if not is_topform_ishihara_booking(wb.title):
                            has_real_work = True
                            break
                if not has_real_work:
                    continue # Ignore this hold
            
            # If not a TOPFORM hold, or has real work content -> Busy
            return True
    return False

def has_travel_conflict(
    slot_time: datetime,
    store: str,
    ishihara_bookings: list[Booking],
    all_bookings: BookingData,
) -> bool:
    """Check for travel time conflicts between stores (requires 1 hour travel)."""
    travel_window_start = slot_time - timedelta(minutes=TRAVEL_TIME)
    travel_window_end = slot_time + timedelta(minutes=SESSION_DURATION + TRAVEL_TIME)
    
    for b in ishihara_bookings:
        # If no store info, ignore for travel conflict
        if not b.store or b.store == "unknown":
            continue
            
        # Same store -> no travel needed
        if b.store == store:
            continue
            
        # Overlap with travel window
        if max(travel_window_start, b.start_dt) < min(travel_window_end, b.end_dt):
            # Check if this is a TOPFORM hold to ignore
            if is_topform_ishihara_booking(b.title):
                continue
            return True
    return False

def check_availability(
    slot_time: datetime,
    store: str,
    all_bookings: BookingData,
) -> dict:
    """
    Main availability check (Synced with TypeScript logic).
    """
    now = datetime.now(JST)
    # Check 3-hour deadline
    if slot_time <= now + timedelta(hours=3):
        return {"is_available": False, "reason": "deadline"}
    
    # Check 2-month rule (rough check)
    if slot_time > now + timedelta(days=62):
         return {"is_available": False, "reason": "too_far"}

    # Business hours (Frontend handles this primarily, but backend validates it)
    is_weekend = slot_time.weekday() >= 5 or _is_holiday(slot_time)
    hours = BUSINESS_HOURS["weekend"] if is_weekend else BUSINESS_HOURS["weekday"]
    if slot_time.hour < hours["start"] or slot_time.hour >= hours["end"]:
        return {"is_available": False, "reason": "outside_hours"}

    # 1. Day off check
    if _has_all_day_event(slot_time, all_bookings.ishihara):
        return {"is_available": False, "reason": "day_off"}

    # 2. Store Capacity check
    store_status = _get_detailed_store_status(slot_time, store, all_bookings)
    if store_status["is_full"]:
        return {"is_available": False, "reason": "store_full"}

    # 3. Trainer Busy check
    if is_trainer_busy(slot_time, all_bookings.ishihara, all_bookings):
        return {"is_available": False, "reason": "trainer_busy"}

    # 4. Travel Conflict check
    if has_travel_conflict(slot_time, store, all_bookings.ishihara, all_bookings):
        return {"is_available": False, "reason": "travel_conflict"}

    return {"is_available": True, "rooms_available": store_status["rooms_available"]}

def _is_holiday(date: datetime) -> bool:
    date_str = date.strftime("%Y-%m-%d")
    return date_str in HOLIDAYS.get(date.year, [])

def _has_all_day_event(slot_time: datetime, ishihara_bookings: list[Booking]) -> bool:
    slot_date = slot_time.strftime("%Y-%m-%d")
    for b in ishihara_bookings:
        if b.start_dt.hour == 0 and b.start_dt.minute == 0:
            if b.start_dt.strftime("%Y-%m-%d") == slot_date:
                if any(kw in b.title for kw in BLOCKING_KEYWORDS):
                    return True
    return False

def get_available_slots(
    target_date: datetime,
    store: str,
    all_bookings: BookingData,
) -> list[datetime]:
    is_weekend = target_date.weekday() >= 5 or _is_holiday(target_date)
    hours = BUSINESS_HOURS["weekend"] if is_weekend else BUSINESS_HOURS["weekday"]
    
    available = []
    for hour in range(hours["start"], hours["end"]):
        slot = target_date.replace(hour=hour, minute=0, second=0, microsecond=0)
        if not slot.tzinfo: slot = JST.localize(slot)
        if check_availability(slot, store, all_bookings)["is_available"]:
            available.append(slot)
    return available


def find_user_bookings(user_name: str, all_bookings: BookingData) -> list[Booking]:
    matches = []
    for b in all_bookings.ishihara:
        if b.source != "work": # プライベート予定は除外
            continue
        title = b.title or ""
        normalized_name = user_name.replace(" ", "").replace("　", "")
        if normalized_name in title.replace(" ", "").replace("　", ""):
            matches.append(b)
    return sorted(matches, key=lambda b: b.start_dt)
