import json
from datetime import timedelta
from unittest.mock import AsyncMock
from calendar_service import Booking, BookingData
from change_pairs import pairs
from tests.test_flows import event, user, future, customer
from tests.test_conversation import reserve, state
import line_service as ls


def cards(service):
    return service.reply_flex.call_args.args[2]['contents']


def texts(card):
    return [c['text'] for c in card['body']['contents']] + [c['text'] for c in card['header']['contents']]


def actions(card):
    return [b['action'] for b in card.get('footer', {}).get('contents', [])]


async def tap(service, action):
    await service.handle_postback_event(event(data=json.loads(action['data'])), user())


def test_pairs_keeps_each_source_with_its_own_destination():
    assert pairs('石原さん\n日程変更21日を25日17時\n23日を27日17時\n変更できますか。') == [
        ('21日を', '25日17時\n'), ('23日を', '27日17時\n変更できますか。')]


def test_pairs_reads_arrows_and_explicit_dates():
    assert [s for s, _ in pairs('21日→25日17時\n23日→27日17時 変更可能ですか')] == ['21日→', '23日→']
    assert [s for s, _ in pairs('11/21を11/25 17:00に、11/23を11/27 17:00に変更できますか')] == ['11/21を', '11/23を']


def test_pairs_ignores_single_change_so_existing_routing_still_runs():
    assert pairs('21日を25日17時に変更お願いします') == [('21日を', '25日17時に変更お願いします')]
    assert pairs('11/21 16:00〜@恵比寿\n↓\n11/25 15:30〜@半蔵門\nに変更お願いします') == []


async def test_two_changes_each_get_their_own_card(service, database):
    first, one = await reserve(database, days=0, hour=16)
    second, two = await reserve(database, days=2, hour=16)
    want_one, want_two = one + timedelta(days=4), two + timedelta(days=4)
    await service.handle_text_message(event(
        f'石原さん\n日程変更{one.day}日を{want_one.day}日17時\n{two.day}日を{want_two.day}日17時\n変更できますか。'), user())
    shown = cards(service)
    assert len(shown) == 2
    assert all('✅' in texts(card)[-1] for card in shown)
    assert want_one.strftime('%m/%d') in ' '.join(texts(shown[0]))
    assert want_two.strftime('%m/%d') in ' '.join(texts(shown[1]))
    # Nothing is submitted until the member taps a card.
    assert len(await database.get_user_bookings('u')) == 2


async def test_card_submits_only_its_own_booking(service, database):
    first, one = await reserve(database, days=0, hour=16)
    second, two = await reserve(database, days=2, hour=16)
    want_one, want_two = one + timedelta(days=4), two + timedelta(days=4)
    await service.handle_text_message(event(
        f'{one.day}日を{want_one.day}日17時、{two.day}日を{want_two.day}日17時に変更できますか'), user())
    await tap(service, actions(cards(service)[1])[0])
    _, data = await state(database)
    assert data['target_booking_id'] == second
    assert data['date'] == want_two.strftime('%Y-%m-%d') and data['time'] == '17:00'


async def test_taken_slot_is_named_and_alternatives_offered(service, database):
    first, one = await reserve(database, days=0, hour=16)
    second, two = await reserve(database, days=2, hour=16)
    want_one, want_two = one + timedelta(days=4), two + timedelta(days=4)
    busy = want_two.replace(hour=17)
    # Both Ebisu rooms taken by other customers: the requested hour is genuinely full.
    service._get_bookings = AsyncMock(return_value=BookingData(
        [Booking(room, busy, busy + timedelta(hours=1), 'ebisu', '他のお客様', room=room)
         for room in ('A', 'B')], [], []))
    await service.handle_text_message(event(
        f'{one.day}日を{want_one.day}日17時、{two.day}日を{want_two.day}日17時に変更できますか'), user())
    taken = cards(service)[1]
    assert '埋まって' in ' '.join(texts(taken))
    assert actions(taken), '代替候補が1件も出ていない'
    # The full slot is never offered back as an alternative.
    stamp = busy.strftime('%m/%d') + '（' + '月火水木金土日'[busy.weekday()] + '）' + busy.strftime('%H:%M')
    assert all(not action['label'].startswith(stamp) for action in actions(taken))


async def test_bare_day_prefers_the_nearest_month(service, database):
    near, one = await reserve(database, days=0, hour=16)
    far, _ = await reserve(database, days=28, hour=16)
    other, two = await reserve(database, days=2, hour=16)
    want_one, want_two = one + timedelta(days=4), two + timedelta(days=4)
    await service.handle_text_message(event(
        f'{one.day}日を{want_one.day}日17時、{two.day}日を{want_two.day}日17時に変更できますか'), user())
    await tap(service, actions(cards(service)[0])[0])
    _, data = await state(database)
    assert data['target_booking_id'] == near


async def test_unknown_source_asks_instead_of_guessing(service, database):
    _, one = await reserve(database, days=0, hour=16)
    missing = one + timedelta(days=10)
    want = one + timedelta(days=4)
    await service.handle_text_message(event(
        f'{missing.day}日を{want.day}日17時、{one.day}日を{want.day}日17時に変更できますか'), user())
    first = cards(service)[0]
    assert '見つかりませんでした' in ' '.join(texts(first))
    assert actions(first) == []
