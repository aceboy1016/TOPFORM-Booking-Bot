import json
from datetime import datetime,timedelta
from unittest.mock import AsyncMock
import pytest
from booking_rules import JST
from tests.test_flows import event,user,future,customer
from tests.test_availability_picker import buttons,tap
from tests.test_conversation import confirm_action,reserve
import booking_view
import booking_actions

async def test_old_card_during_change_and_question_preserves_original(service,database,monkeypatch):
    dt=future()
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 半蔵門空いてる？'),user())
    first=buttons(service)
    chosen=next(a for a in first if '10:00' in a['label'])
    await service.handle_text_message(event('明日は？'),user())
    await service.handle_text_message(event('明後日は？'),user())
    bid,old=await reserve(database,days=1)
    await booking_actions.handle_action(service,event(data=json.loads(await database.make_action('u',{'a':'conversation_select','intent':'change','t':'db','bid':bid}))),user())
    before=await database.get_session('u')
    monkeypatch.setattr(booking_view,'user_bookings',AsyncMock(return_value=[{'id':bid,'type':'db','dt':old,'store':'ebisu','status':'provisional'}]))
    await service.handle_text_message(event('あ、今って何回目？'),user())
    assert (await database.get_session('u'))==before
    assert '今月' in service.reply_text.call_args.args[1]
    await tap(service,chosen)
    session=await database.get_session('u');context=json.loads(session['flow_data'])
    assert session['flow_state']=='confirm' and context['target_booking_id']==bid and context['mode']=='change'
    await service.handle_postback_event(event(data=confirm_action(service)),user())
    rows=await database.get_user_bookings('u',True)
    assert len(rows)==2
    assert (await database.get_booking(bid,'u'))['status']=='provisional'
    assert any(r['metadata'].get('change_from',{}).get('id')==bid for r in rows)

async def test_older_page_and_card_at_confirmation(service,database):
    dt=future()
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 恵比寿空いてる？'),user())
    first=buttons(service)
    page=next(a for a in first if '次の時間' in a['label'])
    one=next(a for a in first if '10:00' in a['label'])
    two=next(a for a in first if '10:30' in a['label'])
    await tap(service,one);old_confirm=confirm_action(service)
    await service.handle_text_message(event('明日は？'),user())
    await tap(service,page)
    payload=service.reply_messages.call_args.args[1][0].to_dict()
    assert dt.strftime('%m/%d') in json.dumps(payload,ensure_ascii=False)
    await tap(service,two)
    assert json.loads((await database.get_session('u'))['flow_data'])['time']=='10:30'
    await service.handle_postback_event(event(data=old_confirm),user())
    assert await database.get_user_bookings('u',True)==[]

@pytest.mark.parametrize('question',['何回目？','あ、今って何回目？','今月何回利用した？','今月の利用回数を教えて'])
async def test_monthly_question_keeps_final_confirmation(service,database,monkeypatch,question):
    now=datetime(2026,9,15,12,tzinfo=JST)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return now
    monkeypatch.setattr(booking_view,'datetime',Clock)
    selected=now.replace(day=20,hour=10,minute=0,second=0,microsecond=0)
    entries=[{'id':'past','type':'cal','dt':now.replace(day=1),'store':'ebisu','status':'confirmed'},
             {'id':'pending','type':'db','dt':now.replace(day=19),'store':'ebisu','status':'provisional'},
             {'id':'other-month','type':'cal','dt':now.replace(day=1)-timedelta(days=1),'store':'ebisu','status':'confirmed'}]
    monkeypatch.setattr(booking_view,'user_bookings',AsyncMock(return_value=entries))
    await database.set_session('u','booking','confirm',json.dumps({'date':selected.strftime('%Y-%m-%d'),'time':'10:00','store':'ebisu','confirmation_id':'keep'}))
    before=await database.get_session('u')
    await service.handle_text_message(event(question),user())
    assert await database.get_session('u')==before
    response=service.reply_text.call_args.args[1]
    assert '利用済み：1回' in response and 'うち仮予約 1件' in response and '今月3回目' in response

async def test_old_card_checks_current_availability(service,database,monkeypatch):
    dt=future()
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 半蔵門空いてる？'),user())
    chosen=buttons(service)[0]
    await service.handle_text_message(event('明日は？'),user())
    monkeypatch.setattr(booking_actions,'check_availability',lambda *a:{'is_available':False})
    await tap(service,chosen)
    assert (await database.get_session('u'))['flow_state']!='confirm'
    assert await database.get_user_bookings('u',True)==[]
    assert service._get_bookings.call_args_list[-2].kwargs.get('force') or any(c.kwargs.get('force') for c in service._get_bookings.call_args_list)

async def test_monthly_planned_change_counts_once(service,database,monkeypatch):
    now=datetime(2026,9,15,12,tzinfo=JST)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return now
    monkeypatch.setattr(booking_view,'datetime',Clock)
    original=await database.save_booking('u','ebisu',now.replace(day=20).isoformat())
    old=await database.get_booking(original,'u')
    replacement=await database.save_booking('u','ebisu',now.replace(day=21).isoformat(),metadata={'change_from':{'id':old['public_id'],'type':'db'}})
    new=await database.get_booking(replacement,'u')
    entries=[{'id':r['public_id'],'type':'db','dt':datetime.fromisoformat(r['slot_datetime']),'store':'ebisu','status':'provisional'} for r in (old,new)]
    monkeypatch.setattr(booking_view,'user_bookings',AsyncMock(return_value=entries))
    await service.handle_text_message(event('今月何回？'),user())
    assert 'これからの予約：1件' in service.reply_text.call_args.args[1]
    assert len(await database.get_user_bookings('u',True))==2
