"""Moving an existing booking, said without the word 変更.

"明日の予約、時間前倒して良いですか？" was read as a brand new request, so the
member ended up holding both the original booking and a second one.
"""
from datetime import timedelta
import pytest
from booking_rules import JST
from datetime import datetime
from tests.test_flows import event, user, future, customer
from tests.test_conversation import state, confirm_action


async def reserve_tomorrow(database, hour=13):
    """The message says 明日, so the booking has to be there."""
    dt = (datetime.now(JST) + timedelta(days=1)).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    bid = await database.save_booking('u', 'ebisu', dt.isoformat())
    row = await database.get_booking(bid, 'u')
    return row['public_id'], dt


@pytest.mark.parametrize('phrase', [
    '時間前倒して良いですか？',
    '前倒しでお願いします',
    '繰り上げたいです',
    '繰り下げてください',
    '少し早めてもらえますか',
    '30分遅らせてください',
    '後ろ倒しでお願いします',
])
async def test_moving_a_booking_never_creates_a_second_one(service, database, phrase):
    held, when = await reserve_tomorrow(database)
    moved = when.replace(hour=11)
    await service.handle_text_message(event(
        f'明日の予約、{phrase}\n\n{moved:%Y/%m/%d}({"月火水木金土日"[moved.weekday()]}) '
        f'11:00〜12:00 @恵比寿'), user())
    rows = await database.get_user_bookings('u')
    assert len(rows) == 1, f'{phrase} で予約が増えている'
    session, data = await state(database)
    assert data.get('mode') == 'change', f'{phrase} が変更として扱われていない'
    assert data.get('target_booking_id') == held
    assert data.get('date') == moved.strftime('%Y-%m-%d') and data.get('time') == '11:00'


async def test_confirming_the_move_replaces_rather_than_adds(service, database):
    held, when = await reserve_tomorrow(database)
    moved = when.replace(hour=11)
    await service.handle_text_message(event(
        f'明日の予約、時間前倒して良いですか？\n\n{moved:%Y/%m/%d} 11:00〜12:00 @恵比寿'), user())
    await service.handle_postback_event(event(data=confirm_action(service)), user())
    rows = await database.get_user_bookings('u')
    added = next(r for r in rows if r['public_id'] != held)
    assert added['metadata']['change_from']['id'] == held, '元の予約と結び付いていない'


@pytest.mark.parametrize('text', [
    '早めに予約したいです',
    '予約したいです',
])
async def test_a_plain_new_request_is_still_a_new_request(service, database, text):
    await service.handle_text_message(event(text), user())
    _, data = await state(database)
    assert data.get('mode') != 'change', f'{text} が変更と誤解されている'
