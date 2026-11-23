"""Tell the administrator when a day a member waited for opens up.

The member is never written to: they were already answered that nothing was
free. This only puts the opening in front of the administrator, who decides
whether to offer it and to whom.

Watches are recorded only when the member said they would wait, so an ordinary
"is the 25th free?" leaves nothing behind.
"""
import hashlib
import json
import logging
import re
from datetime import datetime
from async_services import google_call
from booking_rules import JST, as_jst
from calendar_service import get_available_slots
from config import settings, STORE_NAMES
from database import db

logger = logging.getLogger(__name__)

# "空きが出ましたらご連絡ください" / "空いたら教えて" / "キャンセル待ち".
# Merely asking whether a day is free is not waiting, so 「空いてますか」 and
# 「空き状況」 must not match.
WANTS_TO_WAIT = re.compile(r'キャンセル待ち|空(?:き|い)[^。、\n]{0,6}(?:たら|ましたら|れば|次第)')
WEEKDAY = '月火水木金土日'
MAX_WATCHES = 100


def wants_to_wait(text):
    return bool(WANTS_TO_WAIT.search(text or ''))


def watch_id(line_user_id, date, store):
    seed = '\x00'.join((line_user_id, date, store))
    return 'watch:' + hashlib.sha256(seed.encode()).hexdigest()[:24]


async def remember(line_user_id, name, missed):
    """Record the days this member will wait for. `missed` is [(date, store)]."""
    recorded = 0
    for date, store in missed[:MAX_WATCHES]:
        try:
            if await db.add_slot_watch(watch_id(line_user_id, date, store), line_user_id,
                                       {'date': date, 'store': store, 'name': name or ''}):
                recorded += 1
        except Exception:
            logger.exception('Could not record a slot watch for %s %s', date, store)
    return recorded


async def check(service, now=None):
    """Report every watched day that now has an opening. Never raises."""
    try:
        watches = await db.open_slot_watches(MAX_WATCHES)
    except Exception:
        logger.exception('Could not read slot watches')
        return 0
    if not watches: return 0
    now = as_jst(now or datetime.now(JST))
    reported = 0
    snapshot = None
    for row in watches:
        try:
            payload = row.get('payload') or {}
            if isinstance(payload, str): payload = json.loads(payload)
            day = JST.localize(datetime.strptime(payload['date'], '%Y-%m-%d'))
            store = payload['store']
            # A day that has gone by is closed without a word.
            if day.date() < now.date():
                await db.close_slot_watch(row['id'])
                continue
            if snapshot is None:
                snapshot = await service._get_bookings(force=True)
            slots = await google_call(get_available_slots, day, store, snapshot)
            if not slots: continue
            if await db.close_slot_watch(row['id']):
                await _tell_admin(row['id'], row['line_user_id'], payload, day, store, slots)
                reported += 1
                # One notice per member per day: the other store on the same day
                # tells the administrator nothing they are not already acting on.
                for other in watches:
                    if other['id'] == row['id'] or other['line_user_id'] != row['line_user_id']:
                        continue
                    same = other.get('payload') or {}
                    if isinstance(same, str): same = json.loads(same)
                    if same.get('date') == payload['date']:
                        await db.close_slot_watch(other['id'])
        except Exception:
            logger.exception('Slot watch %s could not be checked', row.get('id'))
    return reported


async def _member_name(line_user_id, payload):
    """Named at notification time: the register is current, the record may not be."""
    if payload.get('name'): return payload['name']
    try:
        from sheets_service import sheets_service
        customer = await google_call(sheets_service.get_customer_by_line_id, line_user_id)
        return (customer or {}).get('name') or ''
    except Exception:
        logger.exception('Could not name the member waiting for %s', payload.get('date'))
        return ''


async def _tell_admin(ident, line_user_id, payload, day, store, slots):
    if not settings.ADMIN_USER_ID: return
    name = await _member_name(line_user_id, payload)
    times = '、'.join(s.strftime('%H:%M') for s in slots[:8])
    if len(slots) > 8: times += ' ほか'
    await db.enqueue(
        'slot-open:' + ident, settings.ADMIN_USER_ID,
        '🔔 空きが出ました\n\n'
        '📅 ' + day.strftime('%m/%d') + '（' + WEEKDAY[day.weekday()] + '）\n'
        '📍 ' + STORE_NAMES.get(store, store) + '\n'
        '🕐 ' + times + '\n\n'
        '👤 ' + (name or 'お客様') + ' 様がこの日をお待ちでした。\n\n'
        '※ お客様には通知していません。ご連絡はこちらからお願いします。')
