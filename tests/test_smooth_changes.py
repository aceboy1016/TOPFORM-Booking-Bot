import json
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
import line_service as ls
from tests.test_flows import event,user,future,customer
from tests.test_conversation import confirm_action,reserve,state

async def test_store_reply_keeps_latest_requested_day(service,database,monkeypatch):
    day=future();old=day+timedelta(days=5)
    await database.set_session('u','booking','select_date',json.dumps({'store':'hanzoomon','date':old.strftime('%Y-%m-%d'),'pending_datetime_text':old.strftime('%Y-%m-%d')+' 11:30'}))
    monkeypatch.setattr(ls,'get_available_slots',lambda date,store,snapshot:[date.replace(hour=11,minute=30)] if store=='ebisu' else [])
    await service.handle_text_message(event(day.strftime('%m/%d')),user())
    await service.handle_text_message(event('恵比寿'),user())
    _,data=await state(database)
    assert data['date']==day.strftime('%Y-%m-%d') and data['store']=='ebisu'
    assert 'pending_datetime_text' not in data

async def test_stale_confirmation_rebuilds_selected_change_and_requires_new_submit(service,database):
    bid,day=await reserve(database,hour=13)
    await service.handle_text_message(event('予約変更'),user())
    card=service.reply_flex.call_args.args[2]['contents'][0]
    await service.handle_postback_event(event(data=json.loads(card['footer']['contents'][0]['action']['data'])),user())
    await service.handle_text_message(event(day.strftime('%m/%d')+' 11:30'),user())
    old=confirm_action(service)
    card=service.reply_flex.call_args.args[2]
    assert '変更内容の確認' in service.reply_flex.call_args.args[1]
    assert 'この内容で変更を申し込む' in json.dumps(card,ensure_ascii=False)
    await service.handle_text_message(event('日時を変更したい'),user())
    await service.handle_text_message(event((day+timedelta(days=1)).strftime('%m/%d')),user())
    await service.handle_postback_event(event(data=old),user())
    s,data=await state(database)
    assert s['flow_state']=='confirm' and data['date']==day.strftime('%Y-%m-%d') and data['time']=='11:30'
    assert data['target_booking_id']==bid and len(await database.get_user_bookings('u'))==1
    latest=confirm_action(service)
    assert latest!=old
    await service.handle_postback_event(event(data=latest),user())
    assert len(await database.get_user_bookings('u'))==2
    assert 'ebisu' not in service.reply_text.call_args.args[1]
    await service.handle_postback_event(event(data=old),user())
    assert len(await database.get_user_bookings('u'))==2

async def test_unavailable_summary_is_text_and_does_not_change_requested_date(service,database,monkeypatch):
    day=future();later=day+timedelta(days=1)
    monkeypatch.setattr(ls,'get_available_slots',lambda date,store,snapshot:[date.replace(hour=10)] if date.date()==later.date() and store=='ebisu' else [])
    await service.handle_text_message(event(day.strftime('%m/%d')+' 恵比寿'),user())
    messages=service.reply_messages.call_args.args[1]
    assert messages[0].type=='text' and messages[1].type=='flex'
    assert len(messages[1].contents.to_dict()['contents'])==1
    _,data=await state(database)
    assert data['date']==day.strftime('%Y-%m-%d')

async def test_stale_confirmation_unavailable_returns_current_options(service,database,monkeypatch):
    import booking_actions
    day=future()
    await service.handle_text_message(event(day.strftime('%m/%d')+' 恵比寿 11:30'),user())
    old=confirm_action(service)
    await service.handle_text_message(event('日時を変更したい'),user())
    monkeypatch.setattr(booking_actions,'check_availability',lambda *a:{'is_available':False})
    service.reply_flex.reset_mock()
    await service.handle_postback_event(event(data=old),user())
    assert not service.reply_flex.called
    assert service.reply_messages.called
    assert await database.get_user_bookings('u',True)==[]
