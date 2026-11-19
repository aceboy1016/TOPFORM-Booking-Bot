"""Put a provisional booking on the calendar as soon as it is accepted.

Availability is read from the calendar alone, so until a booking appears there
the same slot keeps being offered to the next member. Writing the hold at
acceptance closes that window.

A failed write never loses the booking: the row is already stored, and the
administrator is told so the slot can be entered by hand.
"""
import logging
from datetime import datetime
from async_services import google_call
from booking_rules import as_jst
from calendar_service import calendar_service
from config import settings, STORE_NAMES
from database import db

logger = logging.getLogger(__name__)


async def hold(booking_id, line_user_id, name, store, slot):
    """Hold the slot on the calendar. Returns the event id, or None on failure."""
    row = await db.get_booking(booking_id, line_user_id)
    if not row:
        logger.warning('Cannot hold slot: booking %s not found', booking_id)
        return None
    try:
        event_id = await google_call(calendar_service.hold_slot, row['public_id'],
                                     line_user_id, name, store, as_jst(slot))
    except Exception:
        logger.exception('Calendar hold failed for booking %s', row['public_id'])
        await _warn_admin(row['public_id'], name, store, slot)
        return None
    return event_id


async def _warn_admin(public_id, name, store, slot):
    """The slot is still being offered to others until someone enters it."""
    if not settings.ADMIN_USER_ID: return
    slot = as_jst(slot)
    try:
        await db.enqueue(
            'hold-failed:' + public_id, settings.ADMIN_USER_ID,
            '⚠️ カレンダーへの自動登録に失敗しました。\n\n'
            '👤 ' + str(name or 'お客様') + ' 様\n'
            '📅 ' + slot.strftime('%m/%d') + '（' + '月火水木金土日'[slot.weekday()] + '）'
            + slot.strftime('%H:%M') + '\n'
            '📍 ' + STORE_NAMES.get(store, store) + '\n\n'
            'この枠は他のお客様にも空きとして案内され続けます。\n'
            '手動でカレンダーに登録してください。')
    except Exception:
        logger.exception('Could not warn the administrator about %s', public_id)
