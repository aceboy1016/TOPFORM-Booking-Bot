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

from booking_rules import as_jst, booking_limit, slot_error, hours_for

class CalendarUnavailable(RuntimeError):
    """A complete, current calendar snapshot could not be obtained."""

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
    GOOGLE_API_TIMEOUT,
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
    all_day: bool = False
    customer_id: str = ""
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
        self._consecutive_errors = 0  # 連続エラー回数
        self.last_success = None
        self._error_notified = False  # 通知済みフラグ（連続エラー中の重複通知防止）

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
            raise CalendarUnavailable("Calendar credentials are unavailable")
        try:
            # 毎回新しいHTTPセッションを生成して長期接続による切断を防ぐ
            # timeout必須: 未指定だと応答が無い場合に無限待機し、ワーカー1個のCloud Runでは
            # インスタンス全体が停止してLINEのWebhookも受けられなくなる
            import google_auth_httplib2, httplib2
            http = google_auth_httplib2.AuthorizedHttp(
                self._credentials, http=httplib2.Http(timeout=GOOGLE_API_TIMEOUT)
            )
            service = build("calendar", "v3", http=http)
            events, page_token = [], None
            while True:
                result = service.events().list(
                    calendarId=calendar_id, timeMin=time_min, timeMax=time_max,
                    singleEvents=True, orderBy="startTime", maxResults=2500,
                    pageToken=page_token,
                ).execute()
                events.extend(result.get("items", []))
                page_token = result.get("nextPageToken")
                if not page_token: return events
        except Exception as exc:
            raise CalendarUnavailable("Calendar snapshot is incomplete") from exc

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
                 start_dt = as_jst(datetime.fromisoformat(start["dateTime"]))
            elif start.get("date"):
                # All-day event logic
                if any(k in title for k in BLOCKING_KEYWORDS + [UNAVAILABLE_KEYWORD]):
                    start_dt = JST.localize(datetime.strptime(start["date"], "%Y-%m-%d"))
                else:
                    return None # Ignore non-blocking all-day
            else:
                return None

            if end.get("dateTime"):
                end_dt = as_jst(datetime.fromisoformat(end["dateTime"]))
            elif end.get("date"):
                end_dt = JST.localize(datetime.strptime(end["date"], "%Y-%m-%d"))
                if not any(k in title for k in BLOCKING_KEYWORDS + [UNAVAILABLE_KEYWORD]):
                     return None # Ignore non-blocking

            if end_dt <= start_dt:
                raise ValueError("Invalid event interval")
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
                all_day=bool(start.get("date")),
                customer_id=event.get("extendedProperties", {}).get("private", {}).get("line_user_id", ""),
                source=source
            )
        except (ValueError, TypeError, UnboundLocalError) as exc:
            raise CalendarUnavailable("Invalid calendar event dates") from exc

    def fetch_all_bookings(self) -> BookingData:
        """Fetch all bookings from all calendars."""
        if not self._service:
            # Assumed caller awaited initialize() already, or fallback to sync
            self.initialize_sync()
            if not self._service:
                raise CalendarUnavailable("Calendar is not initialized")

        now = datetime.now(JST)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        time_min = today.isoformat()
        time_max = (booking_limit(now) + timedelta(minutes=SESSION_DURATION + TRAVEL_TIME)).isoformat()

        try:
            ebisu_events = self._fetch_events(CALENDAR_IDS["ebisu"], time_min, time_max)
            hanzomon_events = self._fetch_events(CALENDAR_IDS["hanzoomon"], time_min, time_max)
            work_events = self._fetch_events(CALENDAR_IDS["ishihara_work"], time_min, time_max)
            private_events = self._fetch_events(CALENDAR_IDS["ishihara_private"], time_min, time_max)
        except CalendarUnavailable:
            self._consecutive_errors += 1
            # Health exposes the failure; notification delivery is handled by the outbox.
            raise
        self._consecutive_errors = 0
        self.last_success = datetime.now(JST)

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
            title = " ".join(str(ev.get(k, "")) for k in ("summary", "location", "description"))
            if any(x in title for x in ("(半)", "（半）", "半蔵門")): store = "hanzoomon"
            elif any(x in title for x in ("(恵)", "（恵）", "恵比寿")): store = "ebisu"
            
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

    def fetch_user_past_bookings_this_month(self, user_name: str, user_id: str = "", allow_legacy: bool = True) -> list:
        """
        今月1日〜昨日までの、指定ユーザーの予約をカレンダーから取得する。
        今月の利用回数カウント用。
        Returns a list of Booking objects.
        """
        if not self._service:
            self.initialize_sync()
            if not self._service:
                raise CalendarUnavailable("Calendar is not initialized")

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
            customer_id = ev.get("extendedProperties", {}).get("private", {}).get("line_user_id", "")
            if not (customer_id == user_id if customer_id else allow_legacy and name_matches(user_name, title)):
                continue
            store = "unknown"
            title = " ".join(str(ev.get(k, "")) for k in ("summary", "location", "description"))
            if any(x in title for x in ("(半)", "（半）", "半蔵門")):
                store = "hanzoomon"
            elif any(x in title for x in ("(恵)", "（恵）", "恵比寿")):
                store = "ebisu"
            b = self._transform_event(ev, store, "work")
            if b:
                matches.append(b)

        matches.sort(key=lambda b: b.start_dt)
        return matches


# Singleton instance
calendar_service = CalendarService()

def get_slot_status(slot_time, store, all_bookings, duration_min=60):
    """Compatibility wrapper using the same rules as final confirmation."""
    if duration_min != SESSION_DURATION:
        return {'is_available': False, 'reason': 'invalid_duration', 'rooms_available': []}
    return check_availability(slot_time, store, all_bookings)


def _get_detailed_store_status(slot_time, store, all_bookings):
    slot_end = slot_time + timedelta(minutes=SESSION_DURATION)
    entries = all_bookings.ebisu if store == "ebisu" else all_bookings.hanzoomon
    overlapping = [b for b in entries if max(slot_time,b.start_dt)<min(slot_end,b.end_dt)]
    if any(any(k in b.title for k in BLOCKING_KEYWORDS + [UNAVAILABLE_KEYWORD]) for b in overlapping):
        return {"is_full": True, "rooms_available": []}
    if store == "ebisu":
        # Unknown room: do not promise a specific room until it is assigned.
        if any(b.room not in STORE_CAPACITY['ebisu']['rooms'] for b in overlapping):
            return {"is_full": True, "rooms_available": [], "reason": "room_unknown"}
        taken = {b.room for b in overlapping}
        rooms = [r for r in STORE_CAPACITY['ebisu']['rooms'] if r not in taken]
        return {"is_full": not rooms, "rooms_available": rooms}
    points = []
    for b in overlapping:
        points.extend([(max(slot_time,b.start_dt),1),(min(slot_end,b.end_dt),-1)])
    active = peak = 0
    for _,delta in sorted(points):
        active += delta; peak = max(peak,active)
    remaining = max(0,STORE_CAPACITY['hanzoomon']['max']-peak)
    return {"is_full": remaining == 0, "rooms_available": ["Any"]*remaining}

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
            if is_topform_ishihara_booking(b.title):
                continue
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
            if is_topform_ishihara_booking(b.title):
                continue
            if max(travel_window_start,b.start_dt)<min(travel_window_end,b.end_dt):
                return True
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
    slot_time = as_jst(slot_time)
    error = slot_error(slot_time, store, datetime.now(JST))
    if error:
        return {"is_available": False, "reason": error}

    # 1. Day off check
    if _has_all_day_event(slot_time, all_bookings.ishihara):
        return {"is_available": False, "reason": "day_off"}

    # 2. Store Capacity check
    store_status = _get_detailed_store_status(slot_time, store, all_bookings)
    if store_status["is_full"]:
        return {"is_available": False, "reason": store_status.get("reason", "store_full")}

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

def _has_all_day_event(slot_time, ishihara_bookings):
    end = slot_time + timedelta(minutes=SESSION_DURATION)
    return any(b.all_day and max(slot_time,b.start_dt)<min(end,b.end_dt)
               and any(k in b.title for k in BLOCKING_KEYWORDS + [UNAVAILABLE_KEYWORD]) for b in ishihara_bookings)

def get_available_slots(target_date, store, all_bookings):
    target_date = as_jst(target_date)
    hours = hours_for(target_date)
    slots = [target_date.replace(hour=h,minute=m,second=0,microsecond=0)
             for h in range(hours['start'],hours['end']) for m in (0,30)]
    return [s for s in slots if check_availability(s,store,all_bookings)['is_available']]

def name_matches(name, title):
    normalized = re.sub(r"[\s　]+", "", name or "")
    if len(normalized)<3: return False
    # Legacy fallback only: require explicit token boundaries, never substring matching.
    text = re.sub(r"[\s　]+", "", title or "")
    return bool(re.search(r"(?<![\w一-龯ぁ-んァ-ヶ])" + re.escape(normalized) + r"(?:様|さん)?(?![\w一-龯ぁ-んァ-ヶ])",text))

def find_user_bookings(user_name: str, all_bookings: BookingData, user_id: str = "", allow_legacy: bool = True) -> list[Booking]:
    matches = []
    for b in all_bookings.ishihara:
        if b.source != "work": # プライベート予定は除外
            continue
        title = b.title or ""
        normalized_name = user_name.replace(" ", "").replace("　", "")
        if (b.customer_id == user_id if b.customer_id else allow_legacy and name_matches(user_name,title)):
            matches.append(b)
    return sorted(matches, key=lambda b: b.start_dt)
