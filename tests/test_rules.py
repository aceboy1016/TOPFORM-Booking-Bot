from datetime import datetime,timedelta
import pytest
from booking_rules import JST,parse_slot,booking_limit,slot_error
from date_parser import parse_dates
import calendar_service as cs

def dt(s): return JST.localize(datetime.fromisoformat(s))
class Clock(datetime):
    @classmethod
    def now(cls,tz=None): return dt('2026-09-14T08:00')
@pytest.fixture(autouse=True)
def clock(monkeypatch): monkeypatch.setattr(cs,'datetime',Clock)
def data(): return cs.BookingData([],[],[])
def b(id,start,end,room='A',title='予約',store='ebisu'):
    return cs.Booking(id,dt(start),dt(end),store,title,room=room)

@pytest.mark.parametrize('text,expected',[
 ('来週月曜',['2026-09-21']),('来週の土曜',['2026-09-26']),
 ('今週月曜',['2026-09-14']),('10月2日と23日',['2026-10-02','2026-10-23']),
 ('2026-09-15',['2026-09-15']),('2027/01/02',['2027-01-02']),
 ('明日',['2026-09-15']),('明後日',['2026-09-16']),('9/15と9/16',['2026-09-15','2026-09-16'])])
def test_dates(text,expected): assert [d.date().isoformat() for d in parse_dates(text,Clock.now())]==expected

def test_next_week_from_friday():
    assert parse_dates('来週月曜',dt('2026-09-18T10:00'))[0].date().isoformat()=='2026-09-21'

def test_leap_month_limit(): assert booking_limit(dt('2026-12-31T10:00')).date().isoformat()=='2027-02-28'

@pytest.mark.parametrize('time,store,reason',[('22:30','ebisu','outside_hours'),('10:15','ebisu','invalid_interval'),('10:00','bad','invalid_store')])
def test_slot_validation(time,store,reason): assert cs.check_availability(parse_slot('2026-09-15',time),store,data())['reason']==reason

def test_half_hours(): assert any(s.minute==30 for s in cs.get_available_slots(dt('2026-09-15T00:00'),'ebisu',data()))

def test_forced_closure(monkeypatch):
    import booking_rules
    monkeypatch.setattr(booking_rules,'FORCED_CLOSED_DAYS',['2026-09-15'])
    assert not cs.check_availability(dt('2026-09-15T10:00'),'ebisu',data())['is_available']

def test_store_closed():
    d=data();d.ebisu=[b('x','2026-09-15T00:00','2026-09-16T00:00',room=None,title='休日')]
    assert not cs.check_availability(dt('2026-09-15T10:00'),'ebisu',d)['is_available']

def test_sequential_a_leaves_b_free():
    d=data();d.ebisu=[b('x','2026-09-15T09:30','2026-09-15T10:30'),b('y','2026-09-15T10:30','2026-09-15T11:30')]
    assert cs.check_availability(dt('2026-09-15T10:00'),'ebisu',d)['rooms_available']==['B']

def test_hanzomon_peak_not_total():
    d=data();d.hanzoomon=[b(str(i),s,e) for i,(s,e) in enumerate([('2026-09-15T09:30','2026-09-15T10:30'),('2026-09-15T09:30','2026-09-15T10:30'),('2026-09-15T10:30','2026-09-15T11:30')])]
    assert cs.check_availability(dt('2026-09-15T10:00'),'hanzoomon',d)['is_available']

def test_unknown_room_not_promised():
    d=data();d.ebisu=[b('x','2026-09-15T10:00','2026-09-15T11:00',room=None)]
    assert cs.check_availability(dt('2026-09-15T10:00'),'ebisu',d)['reason']=='room_unknown'

def test_hold_does_not_block_unrelated_hour():
    d=data();d.ishihara=[b('hold','2026-09-15T08:00','2026-09-15T23:00',title='TOPFORM 石原 淳哉'),b('real','2026-09-15T15:00','2026-09-15T16:00')]
    assert cs.check_availability(dt('2026-09-15T10:00'),'ebisu',d)['is_available']

def test_travel_unknown_is_conservative():
    d=data();d.ishihara=[b('real','2026-09-15T09:00','2026-09-15T10:00',store='unknown')]
    assert cs.check_availability(dt('2026-09-15T10:00'),'ebisu',d)['reason']=='travel_conflict'

def test_all_day_correct_timezone():
    event={'id':'x','summary':'予約不可','start':{'date':'2026-09-15'},'end':{'date':'2026-09-17'}}
    transformed=cs.CalendarService()._transform_event(event,'ebisu')
    assert transformed.start_dt.utcoffset()==timedelta(hours=9)
    assert transformed.all_day

def test_utc_normalized():
    event={'id':'x','summary':'test','start':{'dateTime':'2026-09-15T01:00:00Z'},'end':{'dateTime':'2026-09-15T02:00:00Z'}}
    assert cs.CalendarService()._transform_event(event,'ebisu').start_dt.hour==10

def test_missing_calendar_fails():
    with pytest.raises(cs.CalendarUnavailable): cs.CalendarService().fetch_all_bookings()

@pytest.mark.parametrize('name,title,expected',[('山田','山田太郎',False),('山田太郎','山田太郎（恵）',True),('田中太郎','田中太郎子（恵）',False)])
def test_name_matching(name,title,expected): assert cs.name_matches(name,title)==expected

def test_calendar_pagination(monkeypatch):
    from unittest.mock import MagicMock
    service=cs.CalendarService();service._credentials=MagicMock()
    client=MagicMock();client.events().list().execute.side_effect=[{'items':[{'id':'1'}],'nextPageToken':'next'},{'items':[{'id':'2'}]}]
    monkeypatch.setattr(cs,'build',lambda *a,**kw:client)
    assert len(service._fetch_events('calendar','start','end'))==2
    assert client.events().list.call_args.kwargs['pageToken']=='next'

def test_partial_calendar_failure_propagates(monkeypatch):
    service=cs.CalendarService();service._service=object()
    def fetch(cid,*args):
        if cid==cs.CALENDAR_IDS['ishihara_private']: raise cs.CalendarUnavailable('failure')
        return []
    monkeypatch.setattr(service,'_fetch_events',fetch)
    with pytest.raises(cs.CalendarUnavailable): service.fetch_all_bookings()
    assert service._consecutive_errors==1
