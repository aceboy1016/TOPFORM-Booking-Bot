"""Openings on a day a member waited for are reported to the administrator only.

The member asked, was told nothing was free, and said they would wait. Nothing
further is ever sent to them: the opening goes to the administrator, who
decides whether to offer it.
"""
import json
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
import line_service as ls
import slot_watch
from calendar_service import BookingData
from config import settings
from slot_watch import check, remember, wants_to_wait
from tests.test_flows import event, user, future, customer


@pytest.fixture(autouse=True)
def admin(monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_USER_ID', 'audit-admin')


def notices(rows):
    return [r for r in rows if r['recipient'] == 'audit-admin' and '空きが出ました' in r['body']]


@pytest.mark.parametrize('text', [
    'もし空きが出ましたらご連絡いただけると嬉しいです。',
    '空きが出たら教えてください',
    '空いたら連絡ください',
    'キャンセル待ちでお願いします',
])
def test_waiting_is_recognised(text):
    assert wants_to_wait(text)


@pytest.mark.parametrize('text', [
    '11/25空いてますか？',
    '空き状況を教えてください',
    '予約したいです',
])
def test_merely_asking_is_not_waiting(text):
    assert not wants_to_wait(text)


async def test_an_opening_is_reported_to_the_administrator_alone(service, database, monkeypatch):
    day = future() + timedelta(days=3)
    date = day.strftime('%Y-%m-%d')
    await remember('u', '扇田 純', [(date, 'ebisu')])
    # Still full: nothing is said.
    monkeypatch.setattr(slot_watch, 'get_available_slots', lambda *a: [])
    assert await check(service) == 0
    assert notices(await database.notification_backlog()) == []
    # It opens.
    monkeypatch.setattr(slot_watch, 'get_available_slots',
                        lambda d, store, snap: [d.replace(hour=15), d.replace(hour=16)])
    assert await check(service) == 1
    sent = notices(await database.notification_backlog())
    assert len(sent) == 1
    body = sent[0]['body']
    assert day.strftime('%m/%d') in body and '恵比寿店' in body
    assert '15:00' in body and '扇田 純' in body
    assert 'お客様には通知していません' in body
    # The member hears nothing, now or ever.
    assert [r for r in await database.notification_backlog() if r['recipient'] == 'u'] == []


async def test_a_reported_day_is_not_reported_again(service, database, monkeypatch):
    day = future() + timedelta(days=3)
    await remember('u', '扇田 純', [(day.strftime('%Y-%m-%d'), 'ebisu')])
    monkeypatch.setattr(slot_watch, 'get_available_slots',
                        lambda d, store, snap: [d.replace(hour=15)])
    assert await check(service) == 1
    assert await check(service) == 0
    assert len(notices(await database.notification_backlog())) == 1


async def test_a_day_that_has_passed_is_dropped_without_a_word(service, database, monkeypatch):
    stale = (future() - timedelta(days=30)).strftime('%Y-%m-%d')
    await remember('u', '扇田 純', [(stale, 'ebisu')])
    monkeypatch.setattr(slot_watch, 'get_available_slots',
                        lambda d, store, snap: [d.replace(hour=15)])
    assert await check(service) == 0
    assert notices(await database.notification_backlog()) == []
    assert await database.open_slot_watches() == []


async def test_nothing_is_watched_unless_the_member_said_they_would_wait(service, database, monkeypatch):
    monkeypatch.setattr(ls, 'get_available_slots', lambda *a: [])
    day = future() + timedelta(days=3)
    await service.handle_text_message(event(f'{day.month}/{day.day} 空いてますか？'), user())
    assert await database.open_slot_watches() == []


async def test_saying_they_will_wait_records_the_days_asked_about(service, database, monkeypatch):
    monkeypatch.setattr(ls, 'get_available_slots', lambda *a: [])
    first = future() + timedelta(days=3)
    second = first + timedelta(days=2)
    await service.handle_text_message(event(
        f'{first.month}.{first.day}.{second.day}でもし空きが出ましたらご連絡ください'), user())
    watched = {json.loads(r['payload'])['date'] if isinstance(r['payload'], str)
               else r['payload']['date'] for r in await database.open_slot_watches()}
    assert {first.strftime('%Y-%m-%d'), second.strftime('%Y-%m-%d')} <= watched
    # The member was answered, but never promised a follow-up.
    assert [r for r in await database.notification_backlog() if r['recipient'] == 'u'] == []


async def test_one_notice_per_day_even_when_both_stores_were_asked(service, database, monkeypatch):
    day = future() + timedelta(days=3)
    date = day.strftime('%Y-%m-%d')
    await remember('u', '', [(date, 'ebisu'), (date, 'hanzoomon')])
    monkeypatch.setattr(slot_watch, 'get_available_slots',
                        lambda d, store, snap: [d.replace(hour=15)])
    assert await check(service) == 1
    assert len(notices(await database.notification_backlog())) == 1
    assert await database.open_slot_watches() == []


async def test_the_member_is_named_from_the_register(service, database, monkeypatch):
    day = future() + timedelta(days=3)
    await remember('u', '', [(day.strftime('%Y-%m-%d'), 'ebisu')])
    monkeypatch.setattr(slot_watch, 'get_available_slots',
                        lambda d, store, snap: [d.replace(hour=15)])
    await check(service)
    assert '架空太郎 様' in notices(await database.notification_backlog())[0]['body']
