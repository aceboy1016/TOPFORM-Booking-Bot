import json
from datetime import timedelta
from unittest.mock import AsyncMock, Mock
import pytest
import calendar_hold
import calendar_service as cs
from calendar_service import BookingData, calendar_service
from config import settings
from tests.test_flows import event, user, future, customer


@pytest.fixture
def calendar_api(monkeypatch):
    """Capture what would be written to Google Calendar."""
    sent = []
    def insert(calendarId, body):
        sent.append({'calendar': calendarId, 'body': body})
        return Mock(execute=Mock(return_value={'id': body['id']}))
    service = Mock(events=Mock(return_value=Mock(insert=insert)))
    monkeypatch.setattr(cs, 'build', lambda *a, **k: service)
    monkeypatch.setattr(calendar_service, '_credentials', Mock())
    # conftest stubs hold_slot for every other test; here we exercise the real one.
    monkeypatch.setattr(calendar_service, 'hold_slot',
                        cs.CalendarService.hold_slot.__get__(calendar_service))
    return sent


async def test_accepting_a_booking_holds_the_slot(service, database, calendar_api):
    slot = future().replace(hour=17)
    await service.handle_text_message(event(
        f'【予約希望】\n{slot:%Y/%m/%d} 17:00〜18:00 @半蔵門'), user())
    assert len(await database.get_user_bookings('u')) == 1
    assert len(calendar_api) == 1, '仮予約がカレンダーに入っていない'
    first = calendar_api[0]
    # The trainer's own calendar is what availability is read from.
    assert first['calendar'] == cs.CALENDAR_IDS['ishihara_work']
    assert first['body']['summary'] == '(半)架空太郎様'
    assert first['body']['start']['dateTime'].startswith(slot.strftime('%Y-%m-%dT17:00'))
    assert first['body']['end']['dateTime'].startswith(slot.strftime('%Y-%m-%dT18:00'))
    assert first['body']['extendedProperties']['private']['line_user_id'] == 'u'


def test_written_events_read_back_as_the_booking_they_describe():
    """The reader has to recognise what the writer produced."""
    slot = future().replace(hour=17)
    for store, marker in (('hanzoomon', '(半)'), ('ebisu', '(恵)')):
        title = cs.STORE_MARKERS[store] + '架空太郎様'
        assert title.startswith(marker)
        booking = calendar_service._transform_event({
            'id': 'x', 'summary': title,
            'start': {'dateTime': slot.isoformat()},
            'end': {'dateTime': (slot + timedelta(hours=1)).isoformat()},
            'extendedProperties': {'private': {'line_user_id': 'u'}},
        }, store, 'work')
        # Carrying the LINE id keeps it out of the resource-hold exclusion,
        # so the slot really is blocked rather than silently ignored.
        assert booking.customer_id == 'u'
        assert not cs.is_resource_hold(booking)
        assert cs.is_trainer_busy(slot, [booking], BookingData([], [], [booking]))
        assert cs.find_user_bookings('架空太郎', BookingData([], [], [booking]), 'u') == [booking]


async def test_a_failed_write_keeps_the_booking_and_warns(service, database, monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_USER_ID', 'audit-admin')
    def explode(*a, **k): raise RuntimeError('calendar down')
    monkeypatch.setattr(calendar_service, 'hold_slot', explode)
    slot = future().replace(hour=17)
    await service.handle_text_message(event(
        f'【予約希望】\n{slot:%Y/%m/%d} 17:00〜18:00 @半蔵門'), user())
    assert len(await database.get_user_bookings('u')) == 1, '予約が失われている'
    warnings = [n for n in await database.notification_backlog()
                if n['recipient'] == 'audit-admin' and '自動登録に失敗' in n['body']]
    assert len(warnings) == 1
    assert '他のお客様にも空きとして案内され続けます' in warnings[0]['body']


def test_the_same_booking_never_creates_two_holds(calendar_api):
    slot = future().replace(hour=17)
    first = calendar_service.hold_slot('AbC-123-dEf', 'u', '架空太郎', 'hanzoomon', slot)
    second = calendar_service.hold_slot('AbC-123-dEf', 'u', '架空太郎', 'hanzoomon', slot)
    assert first == second
    # Google only accepts lowercase base32hex ids.
    assert first.isalnum() and first.islower()


def test_an_unknown_store_is_refused_rather_than_mislabelled(calendar_api):
    with pytest.raises(ValueError, match='Unknown store'):
        calendar_service.hold_slot('abc', 'u', '架空太郎', 'unknown', future())
    assert calendar_api == []


async def test_the_conversational_flow_also_holds_the_slot(service, database, calendar_api):
    from tests.test_conversation import confirm_action
    slot = future().replace(hour=17)
    await service.handle_text_message(event('予約したい'), user())
    await service.handle_text_message(event(f'{slot.month}/{slot.day} 17:00 恵比寿'), user())
    await service.handle_postback_event(event(data=confirm_action(service)), user())
    assert len(await database.get_user_bookings('u')) == 1
    assert len(calendar_api) == 1, '対話フローの仮予約がカレンダーに入っていない'
    assert calendar_api[0]['body']['summary'] == '(恵)架空太郎様'
