"""
TOPFORM LINE Bot - Google Calendar Service
Google Calendar APIと連携して予約状況を取得・判定するサービス
既存の ishihara-booking (TypeScript) のロジックをPythonに移植
"""

import re
from datetime import datetime, timedelta
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
import json

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
class Booking:
    """予約データモデル"""

    def __init__(
        self,
        id: str,
        start: str,
        end: str,
        title: Optional[str] = None,
        store: Optional[str] = None,
        room: Optional[str] = None,
        source: Optional[str] = None,
    ):
        self.id = id
        self.start = start
        self.end = end
        self.title = title
        self.store = store
        self.room = room
        self.source = source

    @property
    def start_dt(self) -> datetime:
        return datetime.fromisoformat(self.start)

    @property
    def end_dt(self) -> datetime:
        return datetime.fromisoformat(self.end)


class BookingData:
    """全カレンダーの予約データ"""

    def __init__(self):
        self.ishihara: list[Booking] = []
        self.ebisu: list[Booking] = []
        self.hanzoomon: list[Booking] = []
        self.last_update: str = ""


# ============================================================
# Google Calendar Client
# ============================================================
class CalendarService:
    """Google Calendar API サービス"""

    def __init__(self):
        self._service = None

    def initialize(self):
        """Initialize the Google Calendar API client."""
        creds_json = settings.GOOGLE_CREDENTIALS_JSON
        if not creds_json:
            raise ValueError("GOOGLE_CREDENTIALS_JSON is not set")

        # Decode base64 if needed
        if not creds_json.startswith("{"):
            import base64
            creds_json = base64.b64decode(creds_json).decode("utf-8")

        creds_data = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_data,
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        )
        self._service = build("calendar", "v3", credentials=credentials)
        print("✅ Google Calendar Service initialized")

    def _fetch_events(
        self, calendar_id: str, time_min: str, time_max: str
    ) -> list[dict]:
        """Fetch events from a single calendar."""
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
            events = result.get("items", [])
            print(f"✅ Fetched {len(events)} events from {calendar_id}")
            return events
        except Exception as e:
            print(f"❌ Failed to fetch events from {calendar_id}: {e}")
            return []

    def _transform_event(
        self, event: dict, source: str = "work"
    ) -> Booking:
        """Transform a Google Calendar event to our Booking model."""
        start = event.get("start", {})
        end = event.get("end", {})

        if start.get("dateTime"):
            start_str = start["dateTime"]
        elif start.get("date"):
            start_str = start["date"] + "T00:00:00+09:00"
        else:
            start_str = ""

        if end.get("dateTime"):
            end_str = end["dateTime"]
        elif end.get("date"):
            # All-day event: Google uses exclusive end date
            from datetime import date as date_type

            end_date = datetime.strptime(end["date"], "%Y-%m-%d").date()
            end_date -= timedelta(days=1)
            end_str = end_date.isoformat() + "T23:59:59+09:00"
        else:
            end_str = ""

        return Booking(
            id=event.get("id", ""),
            start=start_str,
            end=end_str,
            title=event.get("summary"),
            source=source,
        )

    def fetch_all_bookings(self) -> BookingData:
        """Fetch all bookings from all calendars."""
        now = datetime.now(JST)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        time_min = today.isoformat()
        time_max = (today + timedelta(days=61)).isoformat()

        # Fetch from all calendars
        work_events = self._fetch_events(CALENDAR_IDS["ishihara_work"], time_min, time_max)
        private_events = self._fetch_events(CALENDAR_IDS["ishihara_private"], time_min, time_max)
        ebisu_events = self._fetch_events(CALENDAR_IDS["ebisu"], time_min, time_max)
        hanzomon_events = self._fetch_events(CALENDAR_IDS["hanzoomon"], time_min, time_max)

        data = BookingData()

        # Transform ishihara bookings (work + private)
        ishihara_bookings = []
        for ev in work_events:
            ishihara_bookings.append(self._transform_event(ev, "work"))
        for ev in private_events:
            ishihara_bookings.append(self._transform_event(ev, "private"))

        # Add store info to ishihara bookings
        for b in ishihara_bookings:
            title = b.title or ""
            if "(半)" in title or "（半）" in title or title.startswith("半 "):
                b.store = "hanzoomon"
            elif "(恵)" in title or "（恵）" in title or title.startswith("恵 "):
                b.store = "ebisu"

        data.ishihara = ishihara_bookings

        # Transform store bookings
        ebisu_bookings = [self._transform_event(ev, "ebisu") for ev in ebisu_events]
        hanzomon_bookings = [self._transform_event(ev, "hanzoomon") for ev in hanzomon_events]

        # Add store-specific ishihara bookings to store lists
        for b in ishihara_bookings:
            if b.store == "ebisu":
                if not any(existing.id == b.id for existing in ebisu_bookings):
                    ebisu_bookings.append(Booking(
                        id=b.id, start=b.start, end=b.end,
                        title=b.title, store="ebisu", room=b.room, source="ebisu"
                    ))
            elif b.store == "hanzoomon":
                if not any(existing.id == b.id for existing in hanzomon_bookings):
                    hanzomon_bookings.append(Booking(
                        id=b.id, start=b.start, end=b.end,
                        title=b.title, store="hanzoomon", room=b.room, source="hanzoomon"
                    ))

        # Set store and room info
        for b in ebisu_bookings:
            b.store = "ebisu"
            title = b.title or ""
            if "A" in title:
                b.room = "A"
            if "B" in title:
                b.room = "B"

        for b in hanzomon_bookings:
            b.store = "hanzoomon"

        data.ebisu = ebisu_bookings
        data.hanzoomon = hanzomon_bookings
        data.last_update = datetime.now(JST).isoformat()

        return data

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


def _is_store_full(
    slot_time: datetime,
    store: str,
    all_bookings: BookingData,
) -> bool:
    """Check if the store is at capacity."""
    slot_end = slot_time + timedelta(minutes=SESSION_DURATION)

    if store == "ebisu":
        overlapping = [
            b for b in all_bookings.ebisu
            if slot_time < b.end_dt and slot_end > b.start_dt
            and not _is_topform_hold_without_work(b, slot_time, all_bookings)
        ]
        room_a = any(b.room == "A" for b in overlapping)
        room_b = any(b.room == "B" for b in overlapping)
        return room_a and room_b
    else:  # hanzoomon
        overlapping = [
            b for b in all_bookings.hanzoomon
            if slot_time < b.end_dt and slot_end > b.start_dt
            and not _is_topform_hold_without_work(b, slot_time, all_bookings)
        ]
        return len(overlapping) >= 3


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

    if _is_store_full(slot_time, store, all_bookings):
        return {"is_available": False, "reason": "store_full"}

    return {"is_available": True}


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
    all_store_bookings = all_bookings.ebisu + all_bookings.hanzoomon

    for b in all_store_bookings:
        title = b.title or ""
        if user_name in title:
            matches.append(b)

    # Sort by start time
    matches.sort(key=lambda b: b.start)
    return matches


# Singleton instance
calendar_service = CalendarService()
