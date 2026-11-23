"""Put a provisional booking on the calendar as soon as it is accepted.

Availability is read from the calendar alone, so until a booking appears there
the same slot keeps being offered to the next member. Writing the hold at
acceptance closes that window.

Nothing here may raise or stay silent: the booking is already stored by the
time this runs, so a failure must neither break the reply to the member nor
pass unnoticed by the administrator.
"""
import hashlib
import logging
from async_services import google_call
from booking_rules import as_jst
from calendar_service import calendar_service
from config import settings, STORE_NAMES
from database import db

logger = logging.getLogger(__name__)


def event_id(line_user_id, store, slot):
    """A stable id for this booking's hold.

    Derived from the booking itself rather than read back from storage, so a
    retry re-sends the same event and no lookup can fail on the way.
    """
    seed = '\x00'.join((line_user_id, store, as_jst(slot).isoformat()))
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


async def hold(line_user_id, name, store, slot):
    """Hold the slot on the calendar. Returns the event id, or None on failure."""
    try:
        slot = as_jst(slot)
        return await google_call(calendar_service.hold_slot,
                                 event_id(line_user_id, store, slot),
                                 line_user_id, name, store, slot)
    except Exception:
        logger.exception('Calendar hold failed for %s %s %s', line_user_id, store, slot)
        await _warn_admin(name, store, slot)
        return None


async def _warn_admin(name, store, slot):
    """The slot is still being offered to others until someone enters it."""
    if not settings.ADMIN_USER_ID: return
    try:
        slot = as_jst(slot)
        await db.enqueue(
            'hold-failed:' + event_id(settings.ADMIN_USER_ID, store, slot),
            settings.ADMIN_USER_ID,
            '⚠️ カレンダーへの自動登録に失敗しました。\n\n'
            '👤 ' + str(name or 'お客様') + ' 様\n'
            '📅 ' + slot.strftime('%m/%d') + '（' + '月火水木金土日'[slot.weekday()] + '）'
            + slot.strftime('%H:%M') + '\n'
            '📍 ' + STORE_NAMES.get(store, store) + '\n\n'
            'この枠は他のお客様にも空きとして案内され続けます。\n'
            '手動でカレンダーに登録してください。')
    except Exception:
        logger.exception('Could not warn the administrator about %s %s', store, slot)
