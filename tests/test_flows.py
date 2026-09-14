import json
from types import SimpleNamespace as NS
from datetime import datetime,timedelta
from unittest.mock import AsyncMock,Mock
import pytest
from booking_rules import JST
import line_service as ls
from calendar_service import BookingData,Booking
from config import settings

def event(text='',data=None): return NS(source=NS(user_id='u'),reply_token='t',message=NS(text=text),postback=NS(data=json.dumps(data or {})))
def future():
    day=datetime.now(JST)+timedelta(days=7)
    return day.replace(hour=10,minute=0,second=0,microsecond=0)
def user(): return {'line_user_id':'u','display_name':'架空太郎'}
@pytest.fixture(autouse=True)
def customer(monkeypatch): monkeypatch.setattr(ls.sheets_service,'get_customer_by_line_id',lambda uid:{'name':'架空太郎','store_pref':'ebisu','room_pref':'A'})

@pytest.mark.parametrize('message',['booking','2026/10/01 10:00-11:00 恵比寿','明日空いてる？','確定する'])
async def test_unregistered_blocked(message,service,database,monkeypatch):
    monkeypatch.setattr(ls.sheets_service,'get_customer_by_line_id',lambda uid:None)
    await service.handle_text_message(event(message),user())
    assert await database.get_session('u') is None
    assert await database.get_user_bookings('u',True)==[]
    assert '登録' in service.reply_text.call_args.args[1]

async def test_bulk_pads_hour_and_checks_duration(service,database):
    day=future().strftime('%Y/%m/%d')
    entries=service._parse_hayamihyo_bulk(f'{day} 9:00-10:00 hanzoomon\n{day} 99:99-10:00 恵比寿\n{day} 12:00-14:00 恵比寿')
    await service._handle_bulk_booking('t','u',user(),entries)
    rows=await database.get_user_bookings('u',True)
    assert len(rows)==1
    assert 'T09:00:' in rows[0]['slot_datetime'] and rows[0]['store']=='hanzoomon'

async def test_confirmation_revalidates_past(service,database):
    session={'flow_state':'confirm','flow_data':json.dumps({'store':'ebisu','date':'2020-01-01','time':'10:00'})}
    await service._handle_booking_flow('t','u',user(),session,'確定する')
    assert await database.get_user_bookings('u',True)==[]

async def test_reply_failure_still_has_outbox(service,database):
    day=future()
    session={'flow_state':'confirm','flow_data':json.dumps({'store':'ebisu','date':day.strftime('%Y-%m-%d'),'time':'10:00'})}
    service.reply_text=AsyncMock(side_effect=RuntimeError())
    with pytest.raises(RuntimeError): await service._handle_booking_flow('t','u',user(),session,'確定する')
    assert len(await database.pending_bookings())==1
    assert len(await database.pending_notifications())==1

async def test_back_keeps_change_target(service,database):
    session={'flow_state':'select_date','flow_data':json.dumps({'mode':'change','target_booking_id':'abc','store':'ebisu'})}
    await service._handle_booking_flow('t','u',user(),session,'戻る')
    new=json.loads((await database.get_session('u'))['flow_data'])
    assert new['mode']=='change' and new['target_booking_id']=='abc'

async def test_store_button_routes(service,database):
    await database.set_session('u','booking','select_date',json.dumps({'store':'ebisu'}))
    await service.handle_text_message(event('予約 店舗変更'),user())
    assert (await database.get_session('u'))['flow_state']=='select_store'

async def test_multiple_dates_single_reply(service,database):
    await service.handle_text_message(event('明日と明後日空いてる？'),user())
    assert service.reply_messages.await_count==1
    assert service.reply_flex.await_count==0

async def test_normal_cancel_button_present(service,database):
    await database.save_booking('u','ebisu',future().isoformat())
    await service._show_booking_change_list('t','u',user())
    flex=service.reply_flex.call_args.args[2]
    assert len(flex['contents'][0]['footer']['contents'])==2
    for button in flex['contents'][0]['footer']['contents']:
        data=button['action']['data'];assert len(data.encode())<300
        token=json.loads(data)['id'];assert await database.get_action(token,'u')

async def test_calendar_cancellation_accepts_and_notifies(service,database):
    day=future();booking=Booking('cal',day,day+timedelta(hours=1),'ebisu','架空太郎（恵）',source='work')
    service._get_bookings=AsyncMock(return_value=BookingData([],[],[booking]))
    action=json.loads(await database.make_action('u',{'a':'cancel_confirm','t':'cal','bid':'cal','band':'normal'}))
    await database.set_session('u','conversation','cancel_confirmation',json.dumps({'cancel_action':action['id']}))
    await service.handle_postback_event(event(data=action),user())
    assert await database.is_done('calendar-cancel:u:cal')
    assert len(await database.pending_notifications())==1

async def test_old_raw_button_is_rejected(service,database):
    await service.handle_postback_event(event(data={'a':'cancel_request','bid':1}),user())
    assert '期限切れ' in service.reply_text.call_args.args[1]

async def test_waitlist_reply_records_once(service,database):
    day=future()
    await database.save_waitlist_offer('wid','u',{'date':day.strftime('%Y-%m-%d'),'time':'10:00','store':'ebisu','expires_at':(datetime.now(JST)+timedelta(minutes=30)).isoformat()},{})
    action=json.loads(await database.make_action('u',{'a':'waitlist_accept','wid':'wid'}))
    await service.handle_postback_event(event(data=action),user())
    assert (await database.get_waitlist('wid','u'))['state']=='accepted'
    await service.handle_postback_event(event(data=action),user())
    assert '回答済み' in service.reply_text.call_args.args[1]

async def test_booking_view_deduplicates(service,database,monkeypatch):
    from booking_view import user_bookings
    day=future();await database.save_booking('u','ebisu',day.isoformat())
    booking=Booking('cal',day,day+timedelta(hours=1),'ebisu','架空太郎（恵）',source='work')
    service._get_bookings=AsyncMock(return_value=BookingData([],[],[booking]))
    entries=await user_bookings(service,'u',user())
    assert len(entries)==1 and entries[0]['type']=='cal'

async def test_cancelled_calendar_does_not_reappear_as_db_request(service,database):
    from booking_view import user_bookings
    from booking_actions import resolve_booking
    day=future()
    await database.save_booking('u','ebisu',day.isoformat(),metadata={'calendar_id':'cal'})
    booking=Booking('cal',day,day+timedelta(hours=1),'ebisu','架空太郎（恵）',source='work')
    service._get_bookings=AsyncMock(return_value=BookingData([],[],[booking]))
    owner=await database.claim('calendar-cancel:u:cal')
    await database.release('calendar-cancel:u:cal',owner,done=True)
    assert await user_bookings(service,'u',user())==[]
    assert await resolve_booking(service,'u',user(),'cal','cal') is None
