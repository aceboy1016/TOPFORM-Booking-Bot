from datetime import datetime, timedelta
import pytest
from booking_rules import JST, uncovered_holiday_years
from config import HOLIDAYS, settings
from notifications import warn_missing_holidays


def at(year, month, day):
    return JST.localize(datetime(year, month, day))


def test_no_warning_while_the_booking_window_is_covered():
    latest = max(HOLIDAYS)
    assert uncovered_holiday_years(at(latest - 1, 6, 1)) == []


def test_warns_with_time_to_spare():
    latest = max(HOLIDAYS)
    # Bookings run two months ahead, so the unlisted year is first offered on
    # 1 November. The warning has to arrive before that, and it does: 1 September.
    assert uncovered_holiday_years(at(latest, 8, 1)) == []
    assert uncovered_holiday_years(at(latest, 9, 1)) == [latest + 1]
    assert uncovered_holiday_years(at(latest, 11, 1)) == [latest + 1]


def test_reports_every_missing_year_in_range(monkeypatch):
    monkeypatch.setitem(HOLIDAYS, 2026, [])
    monkeypatch.setitem(HOLIDAYS, 2027, [])
    assert uncovered_holiday_years(at(2026, 11, 1)) == [2026, 2027]
    # A year with data is never reported.
    monkeypatch.setitem(HOLIDAYS, 2027, ['2027-01-01'])
    assert uncovered_holiday_years(at(2026, 11, 1)) == [2026]


async def test_admin_is_told_once_however_often_the_container_restarts(database, monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_USER_ID', 'audit-admin')
    latest = max(HOLIDAYS)
    when = at(latest, 11, 1)
    assert await warn_missing_holidays(when) == [latest + 1]
    for _ in range(3):
        await warn_missing_holidays(when)
    notices = [n for n in await database.notification_backlog()
               if n['recipient'] == 'audit-admin' and '祝日が未登録' in n['body']]
    assert len(notices) == 1
    body = notices[0]['body']
    assert str(latest + 1) in body and 'HOLIDAYS' in body


async def test_silent_while_the_data_is_current(database, monkeypatch):
    monkeypatch.setattr(settings, 'ADMIN_USER_ID', 'audit-admin')
    assert await warn_missing_holidays(at(max(HOLIDAYS) - 1, 6, 1)) == []
    assert await database.notification_backlog() == []
