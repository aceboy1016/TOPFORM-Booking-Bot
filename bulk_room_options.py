"""Per-date room choices for a pasted booking list; no implicit submissions."""
import json
from datetime import timedelta
from linebot.v3.messaging import FlexMessage, FlexContainer, TextMessage
from database import db
from booking_rules import parse_slot
from booking_cards import card, details, button
from calendar_service import check_availability, get_available_slots


async def show(service, token, uid, user, entries):
    if len(entries) > 20:
        await service.reply_text(token, '📅 一度に20件まで確認できます。分けて送ってください😊')
        return
    snapshot = await service._get_bookings(force=True)
    from booking_view import user_bookings
    existing = {(b['dt'], b['store']) for b in await user_bookings(service, uid, user)}
    cards = []
    seen = set()
    preferred = user.get('room_pref')
    for entry in entries:
        store = entry['store']
        key = (entry['date_str'], entry['time_str'], store)
        if key in seen:
            continue
        seen.add(key)
        actions = []
        try:
            slot = parse_slot(entry['date_str'], entry['time_str'])
            if parse_slot(entry['date_str'], entry['end_time']) - slot != timedelta(hours=1):
                raise ValueError('duration')
            body = details({'slot_datetime': slot.isoformat(), 'store': store})
        except ValueError:
            cards.append(card('📅 日時をご確認ください', '#167D8D', [
                {'type': 'text', 'text': entry['display'] + '\n1枠60分の日時を教えてください😊', 'wrap': True}]))
            continue
        if (slot, store) in existing:
            cards.append(card('📋 受付済みです', '#167D8D', body))
            continue
        result = check_availability(slot, store, snapshot)
        rooms = result.get('rooms_available', [])
        wanted = preferred if store == 'ebisu' else None
        exact = result['is_available'] and (not wanted or wanted in rooms)
        title = '✅ ご希望の日時で空いています' if exact else '📅 こちらはいかがですか？'

        async def add_choice(candidate, room):
            label = candidate.strftime('%H:%M') + (f' 個室{room}' if room else '')
            payload = {'a': 'bulk_room_pick', 'date': candidate.strftime('%Y-%m-%d'),
                       'time': candidate.strftime('%H:%M'), 'store': store, 'room': room}
            action = await db.make_action(uid, payload, ttl=7*24*60)
            actions.append(button(label, action, room == wanted))

        if exact:
            body.append({'type': 'text', 'text': f'個室{wanted}でご案内できます😊' if wanted else 'ご案内できます😊', 'wrap': True})
            await add_choice(slot, wanted)
        else:
            if result['is_available'] and rooms:
                other = rooms[0]
                body.append({'type': 'text', 'text': f'ご希望の時間は個室{other}なら空いています。\n個室{wanted}をご希望なら、近い時間はこちらです👇', 'wrap': True})
                await add_choice(slot, other)
            else:
                body.append({'type': 'text', 'text': 'ご希望の時間はご案内できません。近い時間を確認しました😊', 'wrap': True})
            nearby = [s for s in get_available_slots(slot, store, snapshot)
                      if s != slot and abs((s-slot).total_seconds()) <= 2*3600
                      and (s, store) not in existing
                      and (not wanted or wanted in check_availability(s, store, snapshot).get('rooms_available', []))]
            for candidate in sorted(nearby, key=lambda s: (abs((s-slot).total_seconds()), s))[:2]:
                await add_choice(candidate, wanted)
            if not nearby:
                body.append({'type': 'text', 'text': '前後2時間には' + (f'個室{wanted}の' if wanted else '') + '空きがありません。別の時間帯・日付もご相談ください。', 'wrap': True, 'size': 'sm'})
        cards.append(card(title, '#167D8D', body, actions))
    await db.set_session(uid, 'booking', 'select_date', json.dumps({'room_pref': preferred, 'store': user.get('store_pref') or 'ebisu'}))
    messages = [TextMessage(text='📩 ご希望の日ごとに空きを確認しました😊\n各カードから時間・個室を選んでください。次の画面で申込みを確認します。\n複数日をご希望の場合は、1件申し込んだ後、この一覧の次の日を選べます。まだ仮予約はしていません。')]
    for i in range(0, len(cards), 10):
        messages.append(FlexMessage(alt_text='📅 日付ごとの空きと個室の候補', contents=FlexContainer.from_dict({'type': 'carousel', 'contents': cards[i:i+10]})))
    await service.reply_messages(token, messages)
