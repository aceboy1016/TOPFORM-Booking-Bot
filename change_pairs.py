"""Answer several "AをBに変更" requests stated in one message.

``split_change`` resolves a single source and destination, so a message naming
two changes collapses into one source plus a destination blob. Here each pair is
kept intact, checked against the calendar, and answered with its own card: the
member learns straight away whether each requested slot is free, and gets nearby
alternatives when it is not.
"""
import json
import re
from datetime import timedelta
from calendar_service import check_availability, get_available_slots
from config import STORE_NAMES
from database import db
from schedule_conversation import date_mentions, original_matches

# "21日を25日17時" / "11/21→11/25" / "21日から25日に"
CONNECTOR = re.compile(r'^[\s　]*(?:を|から|→|⇒|➡|↓|->|=>)[\s　]*(?:の)?[\s　]*$')
MAX_PAIRS = 5
NEARBY_DAYS = (1, -1, 2, -2, 3, -3)
WEEKDAY = '月火水木金土日'


def pairs(text):
    """Return [(source, destination), ...] for every "AをB" stated in text."""
    mentions = date_mentions(text)
    found = []
    index = 0
    while index + 1 < len(mentions):
        source, destination = mentions[index], mentions[index + 1]
        if not CONNECTOR.fullmatch(text[source.end():destination.start()]):
            index += 1
            continue
        # The destination keeps its trailing time until the next pair starts.
        end = mentions[index + 2].start() if index + 2 < len(mentions) else len(text)
        found.append((text[source.start():destination.start()], text[destination.start():end]))
        index += 2
    return found


def resolve_source(service, entries, source):
    """Pick the booking a source phrase names, without guessing between months."""
    matched = [b for b in entries if original_matches(service, b, source)]
    if len(matched) > 1:
        # A bare "21日" matches every month; the nearest upcoming 21st is meant.
        stated = {d.date() for d in service._parse_multiple_dates(source)}
        narrowed = [b for b in matched if b['dt'].date() in stated]
        if narrowed:
            matched = narrowed
    return matched[0] if len(matched) == 1 else None


def desired_slot(service, desired):
    """Return the requested datetime, or None when no single day/time is stated."""
    dates = service._parse_multiple_dates(desired)
    time = service._extract_time(desired)
    if len(dates) != 1 or not time:
        return None
    return dates[0].replace(hour=time[0], minute=time[1])


def alternatives(slot, store, snapshot):
    """Same-day neighbours first, then the same time on nearby days."""
    same_day = [s for s in get_available_slots(slot, store, snapshot) if s != slot]
    picks = [s for s in same_day if s < slot][-1:] + [s for s in same_day if s > slot][:1]
    for delta in NEARBY_DAYS:
        if len(picks) >= 4:
            break
        candidate = slot + timedelta(days=delta)
        if check_availability(candidate, store, snapshot)['is_available']:
            picks.append(candidate)
    return sorted(picks)[:4]


def stamp(slot):
    return slot.strftime('%m/%d') + '（' + WEEKDAY[slot.weekday()] + '）' + slot.strftime('%H:%M')


async def _choice(uid, booking, slot):
    return await db.make_action(uid, {'a': 'conversation_select', 'intent': 'change',
                                      't': booking['type'], 'bid': booking['id'],
                                      'desired': slot.strftime('%Y-%m-%d %H:%M')}, ttl=7 * 24 * 60)


def _card(title, color, lines, buttons):
    body = [{'type': 'text', 'text': line, 'wrap': True,
             'size': 'sm' if index else 'md',
             'weight': 'bold' if index == 0 else 'regular',
             'color': '#243447' if index == 0 else '#52616B'}
            for index, line in enumerate(lines)]
    card = {'type': 'bubble', 'size': 'kilo',
            'header': {'type': 'box', 'layout': 'vertical', 'paddingAll': '16px',
                       'backgroundColor': color,
                       'contents': [{'type': 'text', 'text': title, 'color': '#FFFFFF',
                                     'weight': 'bold', 'size': 'sm', 'wrap': True}]},
            'body': {'type': 'box', 'layout': 'vertical', 'spacing': 'sm',
                     'paddingAll': '18px', 'contents': body}}
    if buttons:
        card['footer'] = {'type': 'box', 'layout': 'vertical', 'spacing': 'sm',
                          'paddingAll': '16px', 'contents': buttons}
    return card


def _button(label, token, primary=False):
    button = {'type': 'button', 'height': 'sm', 'style': 'primary' if primary else 'secondary',
              'action': {'type': 'postback', 'label': label[:20], 'data': token}}
    if primary:
        button['color'] = '#15803D'
    return button


async def _pair_card(service, uid, entries, snapshot, source, desired):
    booking = resolve_source(service, entries, source)
    if not booking:
        return _card('🔎 元の予約が特定できません', '#64748B',
                     ['「' + source.strip()[:40] + '」のご予約が見つかりませんでした',
                      '日付を「11/21」のように教えていただけますか😊'], [])
    before = stamp(booking['dt']) + ' ' + STORE_NAMES[booking['store']]
    slot = desired_slot(service, desired)
    if not slot:
        return _card('📅 変更後の日時を教えてください', '#167D8D',
                     ['変更前：' + before,
                      'ご希望の日時を「11/25 17:00」のように教えてください😊'], [])
    store = booking['store']
    if check_availability(slot, store, snapshot)['is_available']:
        return _card('✅ ご希望の日時で変更できます', '#15803D',
                     ['変更前：' + before, '変更後：' + stamp(slot) + ' ' + STORE_NAMES[store]],
                     [_button('この内容で変更を申し込む', await _choice(uid, booking, slot), True)])
    options = alternatives(slot, store, snapshot)
    lines = ['変更前：' + before, 'ご希望：' + stamp(slot) + ' は埋まっております🙇‍♂️']
    lines.append('近い時間の空きはこちらです😊' if options else '近い日にも空きがありませんでした。別の日程を教えてください😊')
    buttons = [_button(stamp(option) + ' にする', await _choice(uid, booking, option)) for option in options]
    return _card('🈵 ご希望の日時は埋まっています', '#B45309', lines, buttons)


async def show(service, token, uid, user, text):
    """Answer every change pair in one reply; False leaves routing unchanged."""
    from booking_view import user_bookings
    found = pairs(text)
    if len(found) < 2:
        return False
    entries = await user_bookings(service, uid, user)
    snapshot = await service._get_bookings(force=True)
    cards = [await _pair_card(service, uid, entries, snapshot, source, desired)
             for source, desired in found[:MAX_PAIRS]]
    await db.clear_session(uid)
    note = '📅 ご希望の変更を1件ずつ確認しました。進めるものを選んでください😊'
    if len(found) > MAX_PAIRS:
        note = '📅 先頭' + str(MAX_PAIRS) + '件を確認しました。残りは改めて送ってください😊'
    await service.reply_flex(token, note, {'type': 'carousel', 'contents': cards})
    return True
