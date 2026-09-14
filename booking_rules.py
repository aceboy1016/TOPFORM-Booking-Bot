"""Shared business rules for LINE, bulk requests and availability API."""
import calendar
import re
from datetime import datetime, timedelta
import pytz
from config import ADVANCE_BOOKING_MONTHS, BUSINESS_HOURS, HOLIDAYS, FORCED_CLOSED_DAYS, SESSION_DURATION, URGENT_CONTACT_DEADLINE_HOURS, STORE_NAMES

JST = pytz.timezone('Asia/Tokyo')

def as_jst(value: datetime) -> datetime:
    return value.astimezone(JST) if value.tzinfo else JST.localize(value)

def booking_limit(now: datetime) -> datetime:
    now = as_jst(now)
    year, month0 = divmod(now.year * 12 + now.month - 1 + ADVANCE_BOOKING_MONTHS, 12)
    day = min(now.day, calendar.monthrange(year, month0 + 1)[1])
    return now.replace(year=year, month=month0 + 1, day=day, hour=23, minute=59, second=59, microsecond=999999)

def hours_for(day: datetime) -> dict:
    holiday = day.strftime('%Y-%m-%d') in HOLIDAYS.get(day.year, [])
    return BUSINESS_HOURS['weekend' if holiday or day.weekday() >= 5 else 'weekday']

def slot_error(slot: datetime, store: str, now: datetime | None = None) -> str | None:
    slot, now = as_jst(slot), as_jst(now or datetime.now(JST))
    if store not in STORE_NAMES: return 'invalid_store'
    if slot.minute not in (0, 30) or slot.second or slot.microsecond: return 'invalid_interval'
    if slot <= now + timedelta(hours=URGENT_CONTACT_DEADLINE_HOURS): return 'deadline'
    if slot > booking_limit(now): return 'too_far'
    if slot.strftime('%Y-%m-%d') in FORCED_CLOSED_DAYS: return 'day_off'
    hours = hours_for(slot)
    if slot < slot.replace(hour=hours['start'], minute=0) or slot + timedelta(minutes=SESSION_DURATION) > slot.replace(hour=hours['end'], minute=0): return 'outside_hours'
    return None

def parse_slot(day: str, time: str) -> datetime:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) or not re.fullmatch(r'\d{1,2}:\d{2}', time):
        raise ValueError('日時は YYYY-MM-DD と HH:MM で指定してください')
    return as_jst(datetime.strptime(f'{day} {time}', '%Y-%m-%d %H:%M'))

REASONS = {'invalid_store':'店舗を選び直してください。', 'invalid_interval':'開始時刻は00分または30分で指定してください。', 'deadline':'開始3時間前を過ぎています。', 'too_far':'予約は2か月先の同日までです。', 'day_off':'休業日です。', 'outside_hours':'営業時間外です。', 'store_full':'店舗が満席です。', 'trainer_busy':'担当者の予定が入っています。', 'travel_conflict':'店舗間の移動時間を確保できません。', 'room_unknown':'個室の割当を確認できません。'}
