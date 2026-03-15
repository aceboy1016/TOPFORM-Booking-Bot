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

    async def initialize(self):
        """Initialize the Google Calendar API client."""
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
        
        # Build is technically blocking but happens only once at startup
        self._service = build("calendar", "v3", credentials=credentials)

    def _fetch_events(
        self, calendar_id: str, time_min: str, time_max: str
    ) -> list[dict]:
        """Fetch events from a single calendar."""
        if not self._service:
            return []
        try:
            result = (
                self._service.events()
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
            # Assumed caller awaited initialize() already.
            pass

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
            # Note: We must run initialize manually if needed in async context, 
            # but since fetch_user_past_bookings is sync, we assume caller did it.
            # Alternatively use a sync wrapper or initialization flag.
            pass

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


    # ... create_calendar_event ...

# ...

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
    # Filter overlapping bookings (excluding internal holds)
    overlapping = []
    
    # Combine store bookings and relevant Ishihara bookings?
    # Logic: Store calendar is the source of truth for rooms.
    # Ishihara calendar duplicates store bookings usually.
    # We should rely on 'bookings' (store calendar) for capacity check.
    
    for b in bookings:
        if max(slot_time, b.start_dt) < min(slot_end, b.end_dt):
             # Ignore if it's just a hold without details? No, trust store calendar.
             if any(k in b.title for k in BLOCKING_KEYWORDS):
                 return {"is_available": False, "reason": "Blocked", "rooms_available": []}
             overlapping.append(b)

    # 3. Analyze Rooms (Ebisu)
    rooms_available = []
    if store == "ebisu":
        taken_rooms = set()
        unknown_count = 0
        for b in overlapping:
            if b.room:
                taken_rooms.add(b.room)
            else:
                unknown_count += 1
        
        # Determine availability
        if "A" not in taken_rooms:
            rooms_available.append("A")
        if "B" not in taken_rooms:
            rooms_available.append("B")
            
        # If unknown bookings exist, they reduce the count of available rooms, 
        # but we don't know WHICH one.
        # But logically, if unknown_count > 0, we can't promise specific rooms easily.
        # However, for the sake of "Suggestion", we list them but flag conflicts.
        
        conflict_count = len(overlapping)
        
        # If totally full
        if conflict_count >= max_cap:
             return {
                 "is_available": False, 
                 "reason": "Full", 
                 "rooms_available": [],
                 "conflict_count": conflict_count
             }
             
        # If A is taken, remove A from available
        if "A" in taken_rooms:
            if "A" in rooms_available: rooms_available.remove("A")
        if "B" in taken_rooms:
            if "B" in rooms_available: rooms_available.remove("B")
            
        # If UNKNOWN exists, it consumes a slot.
        # If 1 unknown exists, we have 1 slot left.
        # rooms_available might say ["A", "B"]. 
        # But we only have 1 physical room left.
        # We return both, but user logic should handle "if conflict_count == 1, only 1 room left".
    
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


def check_availability(
    slot_time: datetime,
    store: str,
    all_bookings: BookingData,
    duration_min: int = 60,
) -> dict:
    # Use the detailed logic
    status = get_slot_status(slot_time, store, all_bookings, duration_min)
    
    # Additional checks (Business Rules, Trainer Busy, etc.)
    # ... (Keep existing logic for business hours, trainer busy, etc.) ...
    
    # Re-implement basic checks for safety
    # (Assuming existing logic is good, just wrapping it)
    
    # Reuse previous logic for strict availability
    # ...
    
    return status  # For now return the detailed status directly

    def create_calendar_event(
        self,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        store: str,
        description: str = "",
    ) -> Optional[str]:
        """Create a new event in the specified calendar."""
        if not self._service:
            self.initialize()

        # Always add provisional booking to Ishihara's work calendar
        calendar_id = CALENDAR_IDS["ishihara_work"]
        
        if not calendar_id:
            print(f"❌ Unknown store: {store}")
            return None

        event = {
            "summary": title,
            "description": description,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "Asia/Tokyo",
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "Asia/Tokyo",
            },
        }

        try:
            created_event = (
                self._service.events()
                .insert(calendarId=calendar_id, body=event)
                .execute()
            )
            print(f"✅ Created event: {created_event.get('htmlLink')}")
            return created_event.get("id")
        except Exception as e:
            print(f"❌ Failed to create event: {e}")
            return None


# ============================================================
# TOPFORM Hold Detection (from booking-logic.ts)
# ============================================================
def is_topform_ishihara_booking(title: str) -> bool:
    """Check if a booking title indicates a TOPFORM Ishihara hold."""
    if not title:
        return False
    for pattern in TOPFORM_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return True
    return False


# ============================================================
# Availability Logic (from booking-logic.ts)
# ============================================================
def is_holiday(date: datetime) -> bool:
    """Check if a date is a Japanese holiday."""
    year = date.year
    date_str = date.strftime("%Y-%m-%d")
    return date_str in HOLIDAYS.get(year, [])


def _has_all_day_event(slot_time: datetime, ishihara_bookings: list[Booking]) -> bool:
    """Check if there's a blocking all-day event."""
    slot_date = slot_time.strftime("%Y-%m-%d")
    for b in ishihara_bookings:
        start = b.start_dt
        end = b.end_dt
        start_date = start.strftime("%Y-%m-%d")
        if start.hour == 0 and start.minute == 0 and end.hour >= 23:
            if start_date == slot_date:
                title = b.title or ""
                if any(kw in title for kw in BLOCKING_KEYWORDS):
                    return True
    return False


def _has_unavailable_block(slot_time: datetime, ishihara_bookings: list[Booking]) -> bool:
    """Check if there's a 予約不可 block."""
    slot_end = slot_time + timedelta(minutes=SESSION_DURATION)
    for b in ishihara_bookings:
        if b.title and UNAVAILABLE_KEYWORD in b.title:
            if slot_time < b.end_dt and slot_end > b.start_dt:
                return True
    return False


def _is_topform_hold_without_work(
    booking: Booking, slot_time: datetime, all_bookings: BookingData
) -> bool:
    """Check if a TOPFORM hold has no corresponding real work booking."""
    title = booking.title or ""
    if not is_topform_ishihara_booking(title):
        return False

    slot_end = slot_time + timedelta(minutes=SESSION_DURATION)
    work_bookings = [b for b in all_bookings.ishihara if b.source == "work"]
    has_real = any(
        slot_time < wb.end_dt and slot_end > wb.start_dt
        for wb in work_bookings
    )
    return not has_real


def _filter_ishihara_bookings(bookings: list[Booking]) -> list[Booking]:
    """Filter ishihara bookings for availability check."""
    filtered = []
    for b in bookings:
        start = b.start_dt
        end = b.end_dt
        is_all_day = start.hour == 0 and start.minute == 0 and end.hour >= 23
        if is_all_day:
            title = b.title or ""
            if not any(kw in title for kw in BLOCKING_KEYWORDS):
                continue  # Skip non-blocking all-day events
        filtered.append(b)
    return filtered


def _is_trainer_busy(
    slot_time: datetime,
    ishihara_bookings: list[Booking],
    all_bookings: BookingData,
) -> bool:
    """Check if the trainer is busy at slot_time."""
    slot_end = slot_time + timedelta(minutes=SESSION_DURATION)
    for b in ishihara_bookings:
        if slot_time < b.end_dt and slot_end > b.start_dt:
            # TOPFORM hold without real work → ignore
            if _is_topform_hold_without_work(b, slot_time, all_bookings):
                continue
            return True
    return False


def _has_travel_conflict(
    slot_time: datetime,
    store: str,
    ishihara_bookings: list[Booking],
    all_bookings: BookingData,
) -> bool:
    """Check for travel time conflicts between stores."""
    travel_start = slot_time - timedelta(minutes=TRAVEL_TIME)
    travel_end = slot_time + timedelta(minutes=SESSION_DURATION + TRAVEL_TIME)

    for b in ishihara_bookings:
        if not b.store:
            continue
        if b.store == store:
            continue
        if b.start_dt < travel_end and b.end_dt > travel_start:
            if _is_topform_hold_without_work(b, slot_time, all_bookings):
                continue
            return True
    return False


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
                if _is_topform_hold_without_work(b, slot_time, all_bookings):
                    continue
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
            
        is_full = len(options := set(["A", "B"]) - taken_rooms) == 0
        
        # If conflict count >= 2, force full even if room logic is fuzzy
        if len(overlapping) >= 2:
             is_full = True
             rooms_avail = []

        return {"is_full": is_full, "rooms_available": rooms_avail}

    else:  # hanzoomon
        overlapping = []
        for b in all_bookings.hanzoomon:
            if max(slot_time, b.start_dt) < min(slot_end, b.end_dt):
                overlapping.append(b)
        
        is_full = len(overlapping) >= 3
        rooms_avail = ["Any"] * (3 - len(overlapping)) if not is_full else []
        return {"is_full": is_full, "rooms_available": rooms_avail}


def check_availability(
    slot_time: datetime,
    store: str,
    all_bookings: BookingData,
) -> dict:
    """
    Main availability check function.
    Returns: {"is_available": bool, "reason": Optional[str]}
    """
    now = datetime.now(JST)

    # 3-hour booking deadline
    if slot_time <= now + timedelta(hours=BOOKING_DEADLINE_HOURS):
        return {"is_available": False, "reason": "deadline"}

    # 2-month advance booking rule
    two_months_before = slot_time.replace(day=1)
    two_months_before = two_months_before - timedelta(days=1)
    two_months_before = two_months_before.replace(day=1)
    # Simplified: subtract 2 months
    month = slot_time.month - ADVANCE_BOOKING_MONTHS
    year = slot_time.year
    if month <= 0:
        month += 12
        year -= 1
    try:
        limit_date = slot_time.replace(year=year, month=month)
    except ValueError:
        limit_date = slot_time.replace(year=year, month=month, day=28)

    if now.date() < limit_date.date():
        return {"is_available": False, "reason": "too_far_ahead"}

    # Forced closed days
    slot_date_str = slot_time.strftime("%Y-%m-%d")
    if slot_date_str in FORCED_CLOSED_DAYS:
        return {"is_available": False, "reason": "forced_closed"}

    # Business hours
    hour = slot_time.hour
    day_of_week = slot_time.weekday()  # 0=Mon ... 6=Sun
    is_weekend = day_of_week >= 5
    is_hol = is_holiday(slot_time)

    if hour < BUSINESS_HOURS["weekday"]["start"]:
        return {"is_available": False, "reason": "outside_hours"}

    if is_weekend or is_hol:
        last_slot = BUSINESS_HOURS["weekend"]["end"] - 1  # 19:00
        if hour > last_slot:
            return {"is_available": False, "reason": "outside_hours"}
    else:
        last_slot = BUSINESS_HOURS["weekday"]["end"] - 1  # 21:00
        if hour > last_slot:
            return {"is_available": False, "reason": "outside_hours"}

    # All-day event check
    if _has_all_day_event(slot_time, all_bookings.ishihara):
        return {"is_available": False, "reason": "day_off"}

    # Unavailable block check
    if _has_unavailable_block(slot_time, all_bookings.ishihara):
        return {"is_available": False, "reason": "unavailable"}

    # Filter ishihara bookings
    filtered = _filter_ishihara_bookings(all_bookings.ishihara)

    if _is_trainer_busy(slot_time, filtered, all_bookings):
        return {"is_available": False, "reason": "trainer_busy"}

    if _has_travel_conflict(slot_time, store, filtered, all_bookings):
        return {"is_available": False, "reason": "travel_conflict"}

    # Store capacity check
    store_status = _get_detailed_store_status(slot_time, store, all_bookings)
    if store_status["is_full"]:
        return {"is_available": False, "reason": "store_full"}

    return {
        "is_available": True,
        "rooms_available": store_status["rooms_available"]
    }


def get_available_slots(
    target_date: datetime,
    store: str,
    all_bookings: BookingData,
) -> list[datetime]:
    """
    Get all available time slots for a given date and store.

    Args:
        target_date: The date to check
        store: 'ebisu' or 'hanzoomon'
        all_bookings: All calendar data

    Returns:
        List of available datetime slots
    """
    day_of_week = target_date.weekday()
    is_weekend = day_of_week >= 5
    is_hol = is_holiday(target_date)

    if is_weekend or is_hol:
        start_hour = BUSINESS_HOURS["weekend"]["start"]
        end_hour = BUSINESS_HOURS["weekend"]["end"]
    else:
        start_hour = BUSINESS_HOURS["weekday"]["start"]
        end_hour = BUSINESS_HOURS["weekday"]["end"]

    available = []
    for hour in range(start_hour, end_hour):
        slot = target_date.replace(hour=hour, minute=0, second=0, microsecond=0)
        if not slot.tzinfo:
            slot = JST.localize(slot)
        result = check_availability(slot, store, all_bookings)
        if result["is_available"]:
            available.append(slot)

    return available


def find_user_bookings(
    user_name: str, all_bookings: BookingData
) -> list[Booking]:
    """
    Find bookings that match a user's name.
    Searches across all store calendars.
    """
    matches = []
    # 「石原仕事用」カレンダーの予約のみを検索対象にする
    # (店舗カレンダーやプライベートカレンダーからは検索しない)
    for b in all_bookings.ishihara:
        if b.source != "work": # プライベート予定は除外
            continue
            
        title = b.title or ""
        if user_name in title:
            matches.append(b)

    # Sort by start time
    matches.sort(key=lambda b: b.start_dt)
    return matches


# Singleton instance
calendar_service = CalendarService()
