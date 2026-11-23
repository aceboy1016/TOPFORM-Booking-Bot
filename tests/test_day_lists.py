"""Days listed against one month: "11.25.27.30".

Read literally only the first date survived, so a member naming three days was
answered about one. The rest were dropped without any sign of it.
"""
from datetime import datetime
import pytest
from booking_rules import JST
from date_parser import parse_dates
from tests.test_flows import event, user, future, customer

NOW = JST.localize(datetime(2026, 11, 23, 12, 46))


def days(text, now=NOW):
    return [d.strftime('%m/%d') for d in parse_dates(text, now)]


@pytest.mark.parametrize('text', [
    '11.25.27.30でもし空きが出ましたらご連絡いただけると嬉しいです。',
    '11/25,27,30',
    '11/25、27、30',
    '11/25・27・30',
    '25,27,30日',
])
def test_every_listed_day_is_read(text):
    assert days(text) == ['11/25', '11/27', '11/30']


def test_a_full_date_carries_its_year_through_the_list():
    assert days('2026/12/05,12,19,26') == ['12/05', '12/12', '12/19', '12/26']


@pytest.mark.parametrize('text,expected', [
    # A day that leads its own date is not folded into the previous month.
    ('11/25,12/3', ['11/25', '12/03']),
    # A time is never mistaken for a day.
    ('11/25 14:00〜15:00', ['11/25']),
    ('11/25,14:00', ['11/25']),
    ('2026/12/13(日) 13:00〜14:00 @恵比寿', ['12/13']),
    ('12/5', ['12/05']),
])
def test_what_already_worked_still_works(text, expected):
    assert days(text) == expected


async def test_a_listed_request_is_answered_for_every_day(service, database, monkeypatch):
    """The reply has to cover all three days, not just the first."""
    import line_service as ls
    shown = []
    monkeypatch.setattr(ls, 'get_available_slots',
                        lambda day, store, snapshot: shown.append(day) or [])
    await service.handle_text_message(event('11/25,27,30 空いてますか？'), user())
    assert sorted({d.strftime('%m/%d') for d in shown}) == ['11/25', '11/27', '11/30']
