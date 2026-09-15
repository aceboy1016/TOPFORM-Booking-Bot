import json
from datetime import timedelta
from unittest.mock import AsyncMock
from tests.test_flows import event,user,future,customer
from tests.test_availability_picker import buttons,tap
from tests.test_conversation import state,confirm_action
from calendar_service import Booking,BookingData

async def test_b_alternative_is_explicit_and_selected_without_changing_preference(service,database):
    day=future()
    service._get_bookings=AsyncMock(return_value=BookingData([Booking('busy',day,day+timedelta(hours=1),'ebisu','他の予約',room='A')],[],[]))
    await service.handle_text_message(event(f'{day.month}/{day.day} 恵比寿空いてますか'),user())
    content=json.dumps(service.reply_messages.call_args.args[1][0].contents.to_dict(),ensure_ascii=False)
    assert 'ご希望の個室A' in content and '個室Bなら' in content
    candidate=next(a for a in buttons(service) if a['label']=='🕐 10:00')
    assert (await database.get_action(json.loads(candidate['data'])['id'],'u'))['room']=='B'
    await tap(service,candidate)
    s,d=await state(database)
    assert s['flow_state']=='confirm' and d['room']=='B' and d['room_pref']=='A'
    await service.handle_postback_event(event(data=confirm_action(service)),user())
    assert (await database.get_user_bookings('u'))[0]['metadata']['room']=='B'

async def test_b_proposal_rechecks_when_b_becomes_occupied(service,database):
    day=future()
    busy=Booking('a',day,day+timedelta(hours=1),'ebisu','他の予約',room='A')
    service._get_bookings=AsyncMock(return_value=BookingData([busy],[],[]))
    await service.handle_text_message(event(f'{day.month}/{day.day} 恵比寿空いてますか'),user())
    candidate=next(a for a in buttons(service) if a['label']=='🕐 10:00')
    service._get_bookings=AsyncMock(return_value=BookingData([busy,Booking('b',day,day+timedelta(hours=1),'ebisu','他の予約',room='B')],[],[]))
    await tap(service,candidate)
    assert (await state(database))[0]['flow_state']!='confirm'
    assert await database.get_user_bookings('u')==[]

async def test_room_preference_survives_later_time_page(service,database):
    day=future()
    service._get_bookings=AsyncMock(return_value=BookingData([Booking('a',day.replace(hour=8),day.replace(hour=23),'ebisu','他の予約',room='A')],[],[]))
    await service.handle_text_message(event(f'{day.month}/{day.day} 恵比寿空いてますか'),user())
    await tap(service,next(a for a in buttons(service) if '次の時間' in a['label']))
    assert '個室Bなら' in json.dumps(service.reply_messages.call_args.args[1][0].contents.to_dict(),ensure_ascii=False)
    choices=[await database.get_action(json.loads(a['data'])['id'],'u') for a in buttons(service)]
    assert all(a['room']=='B' for a in choices if a['a']=='pick_slot')

async def test_reservation_count_excludes_cancelled_and_replaced_original(service,database,monkeypatch):
    from calendar_service import calendar_service
    monkeypatch.setattr(calendar_service,'fetch_user_past_bookings_this_month',lambda *args:[])
    import booking_view,line_service
    from datetime import datetime
    day=future().replace(day=15)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return day.replace(day=1)
    monkeypatch.setattr(booking_view,'datetime',Clock)
    monkeypatch.setattr(line_service,'datetime',Clock)
    original=await database.save_booking('u','ebisu',day.isoformat())
    original_id=(await database.get_booking(original,'u'))['public_id']
    await database.save_booking('u','ebisu',(day+timedelta(days=1)).isoformat(),'provisional',{'change_from':{'type':'db','id':original_id}})
    cancelled=await database.save_booking('u','ebisu',(day+timedelta(days=2)).isoformat())
    await database.cancel_booking(cancelled,'u','test')
    await service.handle_text_message(event('今月の予約件数を教えて'),user())
    message=service.reply_text.call_args.args[1]
    assert '予約件数：1件' in message and '利用済み' not in message
    await service.handle_text_message(event('予約確認'),user())
    message=service.reply_text.call_args.args[1]
    assert '今月の予約: 1件' in message and 'これからのご予約: 1件' in message
    assert '利用済み' not in message
