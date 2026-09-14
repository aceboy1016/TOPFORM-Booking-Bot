import json
from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from date_parser import parse_dates
from booking_rules import JST
from datetime import datetime
from tests.test_flows import event, user, future, customer
from conversation import remember

async def reserve(database, days=0, hour=10, uid='u'):
    dt=(future()+timedelta(days=days)).replace(hour=hour)
    bid=await database.save_booking(uid,'ebisu',dt.isoformat())
    row=await database.get_booking(bid,uid)
    return row['public_id'],dt

async def state(database):
    s=await database.get_session('u')
    return s,json.loads(s['flow_data']) if s else {}

def confirm_action(service):
    flex=service.reply_flex.call_args.args[2]
    return json.loads(flex['footer']['contents'][0]['action']['data'])

async def test_cancel_positive_and_negative_days(service,database):
    one,dt=await reserve(database)
    two,other=await reserve(database,days=1)
    await service.handle_text_message(event(f'{dt.month}月{dt.day}日をキャンセルお願いします。{other.month}月{other.day}日はキャンセルしないでください'),user())
    action=confirm_action(service)
    payload=await database.get_action(action['id'],'u')
    assert payload['bid']==one
    assert (await database.get_booking(one,'u'))['status']=='provisional'
    await service.handle_postback_event(event(data=action),user())
    assert (await database.get_booking(one,'u'))['status']=='cancelled'
    assert (await database.get_booking(two,'u'))['status']=='provisional'

async def test_negation_only_never_cancels(service,database):
    bid,dt=await reserve(database)
    await service.handle_text_message(event(f'{dt.day}日はキャンセルしないでください'),user())
    assert service.reply_flex.await_count==0
    assert (await database.get_booking(bid,'u'))['status']=='provisional'

async def test_quoted_cancel_requires_target(service,database):
    await reserve(database);await reserve(database,days=1)
    e=event('こちらキャンセルお願いします');e.message.quoted_message_id='unknown'
    await service.handle_text_message(e,user())
    flex=service.reply_flex.call_args.args[2]
    assert flex['type']=='carousel' and len(flex['contents'])==2
    assert len(await database.get_user_bookings('u'))==2

async def test_target_filter_does_not_include_other_users(service,database):
    bid,dt=await reserve(database,uid='another')
    await service.handle_text_message(event(f'{dt.month}/{dt.day}をキャンセルお願いします'),user())
    assert service.reply_flex.await_count==0
    assert (await database.get_booking(bid,'another'))['status']=='provisional'

async def test_same_day_multiple_times_requires_choice(service,database):
    _,dt=await reserve(database);await reserve(database,hour=12)
    await service.handle_text_message(event(f'{dt.month}/{dt.day}キャンセル'),user())
    assert len(service.reply_flex.call_args.args[2]['contents'])==2
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 12時'),user())
    p=await database.get_action(confirm_action(service)['id'],'u')
    assert '12:00' in (await database.get_booking(p['bid'],'u'))['slot_datetime']

async def test_cancel_confirmation_abandoned_token_cannot_execute(service,database):
    bid,dt=await reserve(database)
    await service.handle_text_message(event(f'{dt.month}/{dt.day}キャンセル'),user())
    action=confirm_action(service)
    await service.handle_text_message(event('操作をやめる'),user())
    await service.handle_postback_event(event(data=action),user())
    assert (await database.get_booking(bid,'u'))['status']=='provisional'
    assert '終了' in service.reply_text.call_args.args[1]

async def test_change_button_preserves_original_store(service,database):
    bid,_=await reserve(database)
    a=json.loads(await database.make_action('u',{'a':'scb','t':'db','bid':bid}))
    await service.handle_postback_event(event(data=a),user())
    s,d=await state(database)
    assert s['flow_state']=='select_date' and d['store']=='ebisu'
    assert d['target_booking_id']==bid

async def test_stop_change_keeps_original(service,database):
    bid,_=await reserve(database)
    await database.set_session('u','booking','select_date',json.dumps({'mode':'change','target_booking_id':bid,'store':'ebisu'}))
    await service.handle_text_message(event('日程変更は取り消しとさせてください'),user())
    assert await database.get_session('u') is None
    assert (await database.get_booking(bid,'u'))['status']=='provisional'
    assert '元の予約' in service.reply_text.call_args.args[1]

async def test_change_clarification_is_not_date_error(service,database):
    bid,_=await reserve(database)
    await database.set_session('u','booking','select_date',json.dumps({'mode':'change','target_booking_id':bid,'store':'ebisu'}))
    await service.handle_text_message(event('あ、すみません、上記の日程変更です'),user())
    assert '日程変更として' in service.reply_text.call_args.args[1]
    assert (await state(database))[1]['target_booking_id']==bid

async def test_bulk_paste_in_change_stages_and_keeps_target(service,database):
    bid,dt=await reserve(database)
    await database.set_session('u','booking','select_date',json.dumps({'mode':'change','target_booking_id':bid,'target_booking_type':'db','store':'ebisu'}))
    new=dt+timedelta(days=1)
    await service.handle_text_message(event(f'{new:%Y/%m/%d} 10:00-11:00 恵比寿'),user())
    s,d=await state(database)
    assert s['flow_state']=='confirm'
    assert d['mode']=='change' and d['target_booking_id']==bid
    assert len(await database.get_user_bookings('u'))==1
    await service.handle_text_message(event('確定する'),user())
    rows=await database.get_user_bookings('u')
    assert len(rows)==2
    child=next(r for r in rows if r['public_id']!=bid)
    assert child['metadata']['change_from']['id']==bid
    await service.handle_text_message(event('上記の日程変更です'),user())
    assert '直前の受付は日程変更' in service.reply_text.call_args.args[1]
    await service.handle_text_message(event('日程変更は取り消しでお願いします'),user())
    action=confirm_action(service)
    assert (await database.get_action(action['id'],'u'))['bid']==child['public_id']
    await service.handle_postback_event(event(data=action),user())
    assert (await database.get_booking(bid,'u'))['status']=='provisional'
    assert (await database.get_booking(child['public_id'],'u'))['status']=='cancelled'

async def test_repeat_pasted_request_has_one_booking_and_notice(service,database):
    dt=future();text=f'{dt:%Y/%m/%d} 10:00-11:00 恵比寿'
    await service.handle_text_message(event(text),user())
    await service.handle_text_message(event(text),user())
    assert len(await database.get_user_bookings('u'))==1
    assert len(await database.pending_notifications())==1
    assert '受付済み' in service.reply_text.call_args.args[1]

async def test_confirmation_repeat_with_new_event_does_not_duplicate(service,database):
    _,dt=await reserve(database)
    await database.set_session('u','booking','confirm',json.dumps({'date':dt.strftime('%Y-%m-%d'),'time':'10:00','store':'ebisu'}))
    await service.handle_text_message(event('確定する'),user())
    assert len(await database.get_user_bookings('u'))==1
    assert '追加していません' in service.reply_text.call_args.args[1]

async def test_date_correction_at_confirmation_preserves_change(service,database):
    bid,dt=await reserve(database)
    new=dt+timedelta(days=2)
    await database.set_session('u','booking','confirm',json.dumps({'mode':'change','target_booking_id':bid,'target_booking_type':'db','date':dt.strftime('%Y-%m-%d'),'time':'10:00','store':'ebisu'}))
    await service.handle_text_message(event(f'すみません、やっぱり{new.month}/{new.day}でお願いしたいです'),user())
    s,d=await state(database)
    assert d['date']==new.strftime('%Y-%m-%d') and 'time' not in d
    assert d['target_booking_id']==bid
    assert len(await database.get_user_bookings('u'))==1

async def test_after_submitted_correction_does_not_create_booking(service,database):
    bid,dt=await reserve(database)
    await remember('u',bid,{})
    await service.handle_text_message(event(f'やっぱり{dt.month}/{dt.day}でお願いします'),user())
    assert service.reply_flex.call_args.args[2]['type']=='carousel'
    assert len(await database.get_user_bookings('u'))==1

@pytest.mark.parametrize('text',['7/6月曜日','7月6日月曜','2026/07/06(月)','2026/07/06（月曜日）'])
def test_explicit_day_does_not_expand_weekday(text):
    now=JST.localize(datetime(2026,7,2))
    assert [d.strftime('%Y-%m-%d') for d in parse_dates(text,now)]==['2026-07-06']

async def test_new_request_uses_supplied_date_and_store(service,database):
    dt=future()
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 12時に半蔵門で予約したいです'),user())
    s,d=await state(database)
    assert d['store']=='hanzoomon' and d['date']==dt.strftime('%Y-%m-%d')
    assert len(await database.get_user_bookings('u'))==0

async def test_bulk_change_without_store_keeps_hanzomon(service,database):
    dt=future()
    await database.set_session('u','booking','select_date',json.dumps({'mode':'change','store':'hanzoomon','target_booking_id':'original'}))
    await service.handle_text_message(event(f'{dt:%Y/%m/%d} 10:00-11:00'),user())
    assert (await state(database))[1]['store']=='hanzoomon'

async def test_invalid_bulk_change_does_not_reset_or_save(service,database):
    dt=future()
    await database.set_session('u','booking','select_date',json.dumps({'mode':'change','store':'ebisu','target_booking_id':'original'}))
    await service.handle_text_message(event(f'{dt:%Y/%m/%d} 99:99-10:00'),user())
    assert (await state(database))[1]['target_booking_id']=='original'
    assert len(await database.get_user_bookings('u'))==0
    assert '有効な日時' in service.reply_text.call_args.args[1]

async def test_back_and_store_choice_preserves_date(service,database):
    dt=future()
    await database.set_session('u','booking','select_date',json.dumps({'mode':'change','store':'ebisu','date':dt.strftime('%Y-%m-%d'),'target_booking_id':'original'}))
    await service.handle_text_message(event('戻る'),user())
    await service.handle_text_message(event('半蔵門店'),user())
    s,d=await state(database)
    assert s['flow_state']=='select_time'
    assert d['date']==dt.strftime('%Y-%m-%d') and d['store']=='hanzoomon'
    assert d['target_booking_id']=='original'

async def test_change_cancel_negated_does_not_abort(service,database):
    await database.set_session('u','booking','select_date',json.dumps({'mode':'change','store':'ebisu','target_booking_id':'original'}))
    await service.handle_text_message(event('日程変更は取り消さないでください'),user())
    assert (await state(database))[1]['target_booking_id']=='original'

async def test_time_correction_at_confirmation(service,database):
    dt=future()
    await database.set_session('u','booking','confirm',json.dumps({'store':'ebisu','date':dt.strftime('%Y-%m-%d'),'time':'10:00'}))
    await service.handle_text_message(event('やっぱり12時でお願いします'),user())
    s,d=await state(database)
    assert s['flow_state']=='confirm' and d['time']=='12:00'
    assert len(await database.get_user_bookings('u'))==0

async def test_correction_after_session_expiry_asks_target_and_retains_new_date(service,database):
    bid,dt=await reserve(database)
    new=dt+timedelta(days=3)
    await service.handle_text_message(event(f'すみません、やっぱり{new.month}/{new.day}でお願いしたいです'),user())
    bubble=service.reply_flex.call_args.args[2]['contents'][0]
    action=json.loads(bubble['footer']['contents'][0]['action']['data'])
    await service.handle_postback_event(event(data=action),user())
    s,d=await state(database)
    assert d['target_booking_id']==bid and d['date']==new.strftime('%Y-%m-%d')
    assert len(await database.get_user_bookings('u'))==1

async def test_text_yes_confirms_only_selected_cancellation(service,database):
    bid,dt=await reserve(database)
    await service.handle_text_message(event(f'{dt.month}/{dt.day}キャンセルお願いします'),user())
    await service.handle_text_message(event('はい、お願いします'),user())
    assert (await database.get_booking(bid,'u'))['status']=='cancelled'

async def test_back_cancellation_invalidates_button(service,database):
    bid,dt=await reserve(database)
    await service.handle_text_message(event(f'{dt.month}/{dt.day}キャンセル'),user())
    action=confirm_action(service)
    await service.handle_text_message(event('戻る'),user())
    await service.handle_postback_event(event(data=action),user())
    assert (await database.get_booking(bid,'u'))['status']=='provisional'

async def test_waitlist_word_is_not_reservation_cancellation(service,database):
    bid,_=await reserve(database)
    await service.handle_text_message(event('キャンセル待ちをお願いします'),user())
    assert service.reply_flex.await_count==0
    assert (await database.get_booking(bid,'u'))['status']=='provisional'

async def test_time_change_button_keeps_booking_draft(service,database):
    dt=future()
    await database.set_session('u','booking','confirm',json.dumps({'store':'ebisu','date':dt.strftime('%Y-%m-%d'),'time':'10:00'}))
    await service.handle_text_message(event('時間を変更する'),user())
    s,d=await state(database)
    assert s['flow_state']=='select_time' and d['date']==dt.strftime('%Y-%m-%d')
    assert 'time' not in d
