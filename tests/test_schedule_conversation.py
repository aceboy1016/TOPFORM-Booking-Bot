import json
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
from tests.test_flows import event,user,future,customer
from tests.test_conversation import reserve,state,confirm_action
from tests.test_availability_picker import buttons
import line_service as ls

async def test_arrow_change_keeps_source_and_destination_separate(service,database):
    bid,old=await reserve(database,hour=16)
    new=old+timedelta(days=1)
    await service.handle_text_message(event(f'こんばんは、日程変更のご相談です。\n{old.month}/{old.day}16:00〜@恵比寿\n↓\n{new.month}/{new.day}15:30〜@半蔵門\nに変更お願いできますでしょうか'),user())
    s,d=await state(database)
    assert d['target_booking_id']==bid and d['store']=='hanzoomon'
    assert d['date']==new.strftime('%Y-%m-%d') and d['time']=='15:30'
    assert s['flow_state']=='confirm' and len(await database.get_user_bookings('u'))==1
    await service.handle_postback_event(event(data=confirm_action(service)),user())
    rows=await database.get_user_bookings('u')
    assert len(rows)==2
    assert next(r for r in rows if r['public_id']!=bid)['metadata']['change_from']['id']==bid

async def test_change_template_is_not_two_new_bookings(service,database):
    bid,old=await reserve(database,hour=16)
    new=old+timedelta(days=2)
    await service.handle_text_message(event(f'{old.day}日の16-17時のトレーニングをずらしたいです！\n【予約希望】\n{new:%Y/%m/%d} 11:00〜12:00 @恵比寿\n上記の時間で予約は可能でしょうか？'),user())
    s,d=await state(database)
    assert d['target_booking_id']==bid and d['time']=='11:00' and d['date']==new.strftime('%Y-%m-%d')
    assert len(await database.get_user_bookings('u'))==1

async def test_same_day_destination_time_does_not_filter_original(service,database):
    bid,old=await reserve(database,hour=10)
    await service.handle_text_message(event(f'こんにちは、{old.month}/{old.day}ですが予約変更可能でしょうか？\n16:00〜17:00の半蔵門でお願いできればと思います。'),user())
    s,d=await state(database)
    assert d['target_booking_id']==bid and d['time']=='16:00' and d['store']=='hanzoomon'
    assert d['date']==old.strftime('%Y-%m-%d')

async def test_unspecified_time_change_then_store_time_reply(service,database):
    bid,old=await reserve(database)
    await service.handle_text_message(event(f'お疲れ様です！{old.day}日、時間の変更は不可でしょうか？'),user())
    assert (await state(database))[1]['date']==old.strftime('%Y-%m-%d')
    await service.handle_text_message(event('半蔵門15時お願いします！'),user())
    s,d=await state(database)
    assert d['time']=='15:00' and d['store']=='hanzoomon' and d['target_booking_id']==bid

async def test_source_weekday_compact_time_then_destination_options(service,database):
    old=service._parse_multiple_dates('来週土曜日')[0].replace(hour=10)
    raw=await database.save_booking('u','ebisu',old.isoformat())
    bid=(await database.get_booking(raw,'u'))['public_id']
    await service.handle_text_message(event('来週土曜日1000からの予定について、変更したく。日曜日の選択肢があれば教えていただければ幸いです。'),user())
    s,d=await state(database)
    assert d['target_booking_id']==bid
    assert d['date']==(old+timedelta(days=1)).strftime('%Y-%m-%d')
    assert s['flow_state']=='select_time'

@pytest.mark.parametrize('choice',['deferred_keep','deferred_cancel'])
async def test_unknown_destination_requires_explicit_original_disposition(service,database,choice):
    bid,old=await reserve(database)
    await service.handle_text_message(event(f'すみません！{old.month}/{old.day}ですが日程変更でお願いいたします。変えた日程はまた連絡いたします'),user())
    assert (await database.get_booking(bid,'u'))['status']=='provisional'
    card=service.reply_flex.call_args.args[2]
    actions=[json.loads(c['action']['data']) for c in card['footer']['contents']]
    chosen=None
    for action in actions:
        if (await database.get_action(action['id'],'u'))['a']==choice: chosen=action
    await service.handle_postback_event(event(data=chosen),user())
    assert (await database.get_booking(bid,'u'))['status']=='provisional'
    if choice=='deferred_keep':
        assert '決まったら' in service.reply_text.call_args.args[1]
        await service.handle_text_message(event((old+timedelta(days=2)).strftime('%m/%d')+' 15時'),user())
        assert (await state(database))[1]['target_booking_id']==bid
    else:
        assert (await state(database))[0]['flow_state']=='cancel_confirmation'
        await service.handle_postback_event(event(data=confirm_action(service)),user())
        assert (await database.get_booking(bid,'u'))['status']=='cancelled'

async def test_undecided_during_change_and_stale_choice(service,database):
    bid,_=await reserve(database)
    await service.handle_postback_event(event(data=json.loads(await database.make_action('u',{'a':'scb','t':'db','bid':bid}))),user())
    await service.handle_text_message(event('まだ決まってないので、後で連絡します'),user())
    action=confirm_action(service)
    await service.handle_text_message(event('新しく予約したい'),user())
    await service.handle_postback_event(event(data=action),user())
    assert '終了' in service.reply_text.call_args.args[1]
    assert (await database.get_booking(bid,'u'))['status']=='provisional'

async def test_thanks_with_date_does_not_start_new_change(service,database):
    bid,old=await reserve(database)
    await service.handle_text_message(event(f'{old.day}日への時間変更ありがとうございました！明日もよろしくお願い致します。'),user())
    assert service.reply_flex.await_count==0 and await database.get_session('u') is None
    assert len(await database.get_user_bookings('u'))==1

@pytest.mark.parametrize('text,result',[('金曜日730',(7,30)),('土曜日１０００から',(10,0)),('15時半お願いします',(15,30)),('2026/09/21',None),('2026年9月21日',None)])
def test_compact_chat_time(service,text,result):
    assert service._extract_time(text)==result

async def test_short_time_infers_only_displayed_store(service,database,monkeypatch):
    old=future()
    monkeypatch.setattr(ls,'get_available_slots',lambda day,store,snapshot:[day.replace(hour=11)] if store=='ebisu' else [day.replace(hour=17)])
    await service.handle_text_message(event(f'{old.month}/{old.day} 両店舗空いてます？'),user())
    await service.handle_text_message(event('11時お願いします'),user())
    s,d=await state(database)
    assert s['flow_state']=='confirm' and d['store']=='ebisu' and d['time']=='11:00'

async def test_later_question_uses_requested_time(service,database):
    old=future()
    await service.handle_text_message(event(f'{old.month}/{old.day} 恵比寿14時空いてますか'),user())
    await service.handle_text_message(event('もうちょいあととかないですか'),user())
    s,d=await state(database)
    assert d['filters']['after']==14*60+30
    assert d['date']==old.strftime('%Y-%m-%d')


async def test_polite_relative_cancellation_keeps_other_date(service,database):
    from datetime import datetime
    from booking_rules import JST
    tomorrow=(datetime.now(JST)+timedelta(days=1)).replace(hour=18,minute=0,second=0,microsecond=0)
    bid=await database.save_booking('u','ebisu',tomorrow.isoformat())
    other=await database.save_booking('u','ebisu',(tomorrow+timedelta(days=7)).isoformat())
    await service.handle_text_message(event('ご連絡ありがとうございます。明日もキャンセルさせていただければと存じます。その次の週は予定通りかと思います。よろしくお願いします。'),user())
    action=confirm_action(service)
    assert (await database.get_action(action['id'],'u'))['bid']==(await database.get_booking(bid,'u'))['public_id']
    assert (await database.get_booking(other,'u'))['status']=='provisional'

async def test_emoji_confirmation_works_after_time_choice(service,database):
    old=future()
    await service.handle_text_message(event(f'{old.month}/{old.day} 半蔵門15時お願いします'),user())
    assert (await state(database))[0]['flow_state']=='confirm'
    await service.handle_text_message(event('お願いします🙌'),user())
    assert len(await database.get_user_bookings('u'))==1

async def test_compact_outside_hours_is_not_booked(service,database):
    await service.handle_text_message(event('来週金曜日730'),user())
    assert await database.get_user_bookings('u')==[]
    s,d=await state(database)
    assert s['flow_state']!='confirm'
    assert '07:30' not in [a['label'].split()[-1] for a in buttons(service)]

async def test_month_inherited_across_original_target_selection(service,database):
    bid,old=await reserve(database)
    await reserve(database,hour=12)
    new=old+timedelta(days=2)
    await service.handle_text_message(event(f'{old.month}/{old.day}の予約、変更をお願いできますでしょうか。{new.day}日16:00半蔵門を希望しています。'),user())
    card=service.reply_flex.call_args.args[2]['contents'][0]
    action=json.loads(card['footer']['contents'][0]['action']['data'])
    await service.handle_postback_event(event(data=action),user())
    s,d=await state(database)
    assert d['date']==new.strftime('%Y-%m-%d') and d['time']=='16:00'
    assert d['store']=='hanzoomon' and d['mode']=='change'
    assert len(await database.get_user_bookings('u'))==2


async def test_new_booking_draft_can_switch_to_existing_schedule_change(service,database):
    bid,old=await reserve(database)
    await database.set_session('u','booking','select_date',json.dumps({'store':'ebisu'}))
    await service.handle_text_message(event(f'{old.month}/{old.day}ですが日程変更をお願いします。変更先は未定です'),user())
    s,d=await state(database)
    assert s['flow_state']=='deferred_options'
    action=confirm_action(service)
    assert (await database.get_action(action['id'],'u'))['bid']==bid
    assert len(await database.get_user_bookings('u'))==1

async def test_undecided_change_without_original_day_asks_which_booking(service,database):
    bid,_=await reserve(database)
    await service.handle_text_message(event('日程変更したいけど、変更先はまだ決まっていないです'),user())
    card=service.reply_flex.call_args.args[2]['contents'][0]
    await service.handle_postback_event(event(data=json.loads(card['footer']['contents'][0]['action']['data'])),user())
    assert (await state(database))[0]['flow_state']=='deferred_options'
    assert (await database.get_booking(bid,'u'))['status']=='provisional'


async def test_day_after_tomorrow_is_not_undecided(service,database):
    from datetime import datetime
    from booking_rules import JST
    old=(datetime.now(JST)+timedelta(days=1)).replace(hour=23,minute=0,second=0,microsecond=0)
    bid=await database.save_booking('u','ebisu',old.isoformat())
    await service.handle_text_message(event('明日の予約を明後日15時に変更したいです'),user())
    s,d=await state(database)
    assert s['flow_type']=='booking' and s['flow_state']=='confirm'
    assert d['date']==(old+timedelta(days=1)).strftime('%Y-%m-%d') and d['time']=='15:00'
    assert d['target_booking_id']==(await database.get_booking(bid,'u'))['public_id']
