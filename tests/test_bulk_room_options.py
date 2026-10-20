import json
from datetime import timedelta
from unittest.mock import AsyncMock
from tests.test_flows import event, user, future, customer
from tests.test_conversation import state, confirm_action
from calendar_service import Booking, BookingData


def cards(service):
    return [c for m in service.reply_messages.call_args.args[1][1:] for c in m.contents.to_dict()['contents']]


def actions(card):
    return card.get('footer', {}).get('contents', [])


async def test_bulk_room_choices_and_independent_selections(service, database):
    day = future()
    other = day + timedelta(days=1)
    service._get_bookings = AsyncMock(return_value=BookingData([
        Booking('busy', other, other+timedelta(hours=1), 'ebisu', '他の予約', room='A')], [], []))
    text = '来月の予約をします！何回か金曜にしようかと思います！\n' + '\n'.join(
        f'{d:%Y/%m/%d} 10:00〜11:00 @恵比寿' for d in (day, other))
    await service.handle_text_message(event(text), user())
    shown = cards(service)
    assert len(shown) == 2
    assert '個室Aでご案内' in json.dumps(shown[0], ensure_ascii=False)
    labels = [a['action']['label'] for a in actions(shown[1])]
    assert '10:00 個室B' in labels and any('個室A' in x for x in labels)
    assert await database.get_user_bookings('u') == []
    # Submit the first day, then select a separate card without losing the list.
    await service.handle_postback_event(event(data=json.loads(actions(shown[0])[0]['action']['data'])), user())
    assert (await state(database))[1]['room'] == 'A'
    await service.handle_postback_event(event(data=confirm_action(service)), user())
    await service.handle_postback_event(event(data=json.loads(actions(shown[1])[0]['action']['data'])), user())
    _, draft = await state(database)
    assert draft['room'] == 'B' and draft['room_pref'] == 'A'
    await service.handle_postback_event(event(data=confirm_action(service)), user())
    rows = await database.get_user_bookings('u')
    assert len(rows) == 2
    assert {r['metadata']['room'] for r in rows} == {'A', 'B'}


async def test_stale_room_choice_is_rechecked(service, database):
    day = future()
    text = '\n'.join(f'{d:%Y/%m/%d} 10:00〜11:00 @恵比寿' for d in (day, day+timedelta(days=1)))
    await service.handle_text_message(event(text), user())
    selected = actions(cards(service)[0])[0]
    service._get_bookings = AsyncMock(return_value=BookingData([
        Booking('busy', day, day+timedelta(hours=1), 'ebisu', '他の予約', room='A')], [], []))
    await service.handle_postback_event(event(data=json.loads(selected['action']['data'])), user())
    assert (await state(database))[0]['flow_state'] != 'confirm'
    assert await database.get_user_bookings('u') == []


async def test_no_nearby_a_and_bulk_card_cannot_change_another_booking(service, database):
    day = future()
    service._get_bookings = AsyncMock(return_value=BookingData([
        Booking('busy', day.replace(hour=8), day.replace(hour=23), 'ebisu', '他の予約', room='A')], [], []))
    text = '\n'.join(f'{d:%Y/%m/%d} 10:00〜11:00 @恵比寿' for d in (day, day+timedelta(days=1)))
    await service.handle_text_message(event(text), user())
    shown = cards(service)
    assert len(actions(shown[0])) == 1
    assert '前後2時間には個室Aの空きがありません' in json.dumps(shown[0], ensure_ascii=False)
    await database.set_session('u', 'booking', 'select_date', json.dumps({'mode':'change','target_booking_id':'original'}))
    await service.handle_postback_event(event(data=json.loads(actions(shown[0])[0]['action']['data'])), user())
    assert (await state(database))[1]['target_booking_id'] == 'original'
    assert '新しい予約用' in service.reply_text.call_args.args[1]


async def test_twenty_days_are_split_into_valid_carousels(service, database):
    day = future()
    await service.handle_text_message(event('\n'.join(
        f'{day+timedelta(days=i):%Y/%m/%d} 10:00〜11:00 @恵比寿' for i in range(20))), user())
    messages = service.reply_messages.call_args.args[1]
    assert len(messages) == 3
    assert [len(m.contents.to_dict()['contents']) for m in messages[1:]] == [10, 10]
    assert await database.get_user_bookings('u') == []
