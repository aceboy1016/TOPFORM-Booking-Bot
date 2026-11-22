"""A booking named by day alone: "12の分を13へ変更します".

Without 日 the day was not read as a date, so the only mention left was the
destination — and the destination was then searched for as the source, which
never matches. The reply was "該当する予約が見つかりませんでした".
"""
import json
from datetime import timedelta
import pytest
from conversation import mentioned_dates
from schedule_conversation import date_mentions, split_change
from tests.test_flows import event, user, future, customer
from tests.test_conversation import reserve, state, confirm_action


def test_a_day_on_its_own_is_read_as_a_date():
    assert mentioned_dates('12の分') == [(None, None, 12)]
    assert mentioned_dates('12日の分') == [(None, None, 12)]
    assert mentioned_dates('12の方') == [(None, None, 12)]
    # A plain number is still not a date.
    assert mentioned_dates('12を13へ') == []


def test_the_destination_is_no_longer_taken_for_the_source():
    text = 'ごめんなさん、12の分を13へ変更します🙇\n2026/12/13(日) 13:00〜14:00 @恵比寿'
    assert [m[0] for m in date_mentions(text)] == ['12の分', '2026/12/13']
    source, desired = split_change(text)
    assert mentioned_dates(source) == [(None, None, 12)], '変更元が12日になっていない'
    assert desired.startswith('2026/12/13')


async def test_changing_one_of_several_bookings_by_day(service, database):
    """The real case: four bookings held, one of them moved by day alone."""
    first = future().replace(hour=13)
    kept, _ = await reserve(database, days=0, hour=13)
    moved, moved_at = await reserve(database, days=7, hour=13)
    await reserve(database, days=14, hour=13)
    target = moved_at + timedelta(days=1)
    await service.handle_text_message(event(
        f'ごめんなさん、{moved_at.day}の分を{target.day}へ変更します🙇\n'
        f'{target:%Y/%m/%d}({"月火水木金土日"[target.weekday()]}) 13:00〜14:00 @恵比寿'), user())
    session, data = await state(database)
    assert data['target_booking_id'] == moved, 'ずらす対象を取り違えている'
    assert data['date'] == target.strftime('%Y-%m-%d') and data['time'] == '13:00'
    # Nothing is submitted until the member confirms.
    assert len(await database.get_user_bookings('u')) == 3
    await service.handle_postback_event(event(data=confirm_action(service)), user())
    rows = await database.get_user_bookings('u')
    assert len(rows) == 4
    added = next(r for r in rows if r['public_id'] not in (kept, moved))
    assert added['metadata']['change_from']['id'] == moved


async def test_an_unknown_day_still_asks_rather_than_guessing(service, database):
    _, held = await reserve(database, days=0, hour=13)
    absent = held + timedelta(days=3)
    target = held + timedelta(days=5)
    await service.handle_text_message(event(
        f'{absent.day}の分を{target.day}へ変更します\n'
        f'{target:%Y/%m/%d} 13:00〜14:00 @恵比寿'), user())
    assert len(await database.get_user_bookings('u')) == 1
    said = ' '.join(str(c) for c in service.reply_text.call_args_list) + \
           ' '.join(str(c) for c in service.reply_flex.call_args_list)
    assert '見つかりません' in said or '選んで' in said


def test_a_destination_day_never_lands_in_the_past():
    """Moving a month-end booking to "1日" means next month, not a past date."""
    from datetime import date
    from schedule_conversation import month_prefix
    from booking_rules import JST
    from datetime import datetime
    today = datetime.now(JST).date()
    end_of_month = date(today.year + (today.month == 12),
                        1 if today.month == 12 else today.month + 1, 1) - timedelta(days=2)
    prefix = month_prefix(end_of_month, 1)
    year, month = (int(p) for p in prefix.strip('/').split('/'))
    assert date(year, month, 1) >= today, f'{prefix}1日 は過去'
    assert (year, month) != (end_of_month.year, end_of_month.month)
    # A day still ahead of today keeps the booking's own month.
    ahead = today + timedelta(days=3)
    assert month_prefix(ahead, ahead.day) == f'{ahead.year}/{ahead.month}/'
