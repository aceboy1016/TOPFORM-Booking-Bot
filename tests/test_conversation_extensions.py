import json
from datetime import datetime,timedelta
from unittest.mock import AsyncMock
import pytest
from booking_rules import JST
from date_parser import parse_dates
from availability_search import filters_from
from tests.test_flows import event,user,future,customer
from tests.test_availability_picker import buttons,tap
from tests.test_conversation import confirm_action,reserve
import line_service as ls
import waitlist_service
from notifications import flush_notifications


def context(session): return json.loads(session['flow_data'])

def times(service): return [a for a in buttons(service) if a['label'].startswith('🕐')]

@pytest.mark.parametrize('phrase,count',[('今週どこか空いてる？',6),('来週は？',7),('週末',2),('9/20〜9/25',6)])
def test_periods(phrase,count):
    now=JST.localize(datetime(2026,9,15,12))
    dates=parse_dates(phrase,now)
    assert len(dates)==count and all(d.date()>=now.date() for d in dates)

def test_morning_anytime_and_minute_boundaries():
    assert filters_from('午前中ならいつでも')=={'before':720}
    assert filters_from('19:30以降で')=={'after':1170}

async def test_later_other_and_previous_continue_to_booking(service,database):
    day=future()
    await service.handle_text_message(event(f'{day.month}/{day.day} 半蔵門 10:00'),user())
    assert (await database.get_session('u'))['flow_state']=='confirm'
    await service.handle_text_message(event('もう少し遅め'),user())
    assert times(service) and all(a['label'].split()[-1]>'10:00' for a in times(service))
    await service.handle_text_message(event('さっきの時間に戻して'),user())
    assert context(await database.get_session('u'))['time']=='10:00'
    await tap(service,next(a for a in times(service) if '10:00' in a['label']))
    await service.handle_text_message(event('ほかの時間は？'),user())
    assert all('10:00' not in a['label'] for a in times(service))
    await tap(service,times(service)[0])
    await service.handle_postback_event(event(data=confirm_action(service)),user())
    assert len(await database.get_user_bookings('u',True))==1

async def test_time_filter_before_date_and_period_paging(service,database):
    await service.handle_text_message(event('午前中ならいつでも'),user())
    await service.handle_text_message(event('来週どこか空いてる？'),user())
    assert len(context(await database.get_session('u'))['picker_dates'])==7
    assert times(service) and all(int(a['label'].split()[-1].split(':')[0])<12 for a in times(service))
    await tap(service,next(a for a in buttons(service) if '次の日程' in a['label']))
    assert times(service) and all(int(a['label'].split()[-1].split(':')[0])<12 for a in times(service))

async def test_preferred_store_and_alternatives(service,database,monkeypatch):
    day=future()
    def slots(date,store,snapshot):
        return [date.replace(hour=10,minute=0)] if store=='hanzoomon' else []
    monkeypatch.setattr(ls,'get_available_slots',slots)
    await service.handle_text_message(event(f'{day.month}/{day.day} 恵比寿がダメなら半蔵門で'),user())
    actions=[await database.get_action(json.loads(a['data'])['id'],'u') for a in times(service)]
    assert actions and all(a['store']=='hanzoomon' for a in actions)
    await service.handle_text_message(event(f'{day.month}/{day.day} 恵比寿で空いてる？'),user())
    actions=[await database.get_action(json.loads(a['data'])['id'],'u') for a in times(service)]
    assert any(a['store']=='hanzoomon' for a in actions)

async def test_earliest_query_finds_first_available_date(service,database,monkeypatch):
    day=future()
    monkeypatch.setattr(ls,'get_available_slots',lambda date,store,snapshot:[date.replace(hour=10)] if date.date()==day.date() else [])
    await service.handle_text_message(event('一番早く取れるのは？'),user())
    assert context(await database.get_session('u'))['picker_dates']==[day.strftime('%Y-%m-%d')]

async def test_confirmation_edits_status_and_abort_change(service,database):
    bid,day=await reserve(database)
    await service.handle_text_message(event('予約変更'),user())
    card=service.reply_flex.call_args.args[2]['contents'][0]
    await service.handle_postback_event(event(data=json.loads(card['footer']['contents'][0]['action']['data'])),user())
    await service.handle_text_message(event('変更やっぱりやめる。元のままで'),user())
    assert day.strftime('%m/%d') in service.reply_text.call_args.args[1]
    assert (await database.get_booking(bid,'u'))['status']=='provisional'
    await service.handle_text_message(event('これ、もう確定してる？'),user())
    assert '仮予約' in service.reply_text.call_args.args[1]
    await service.handle_text_message(event(f'{day.month}/{day.day} 半蔵門 11:00'),user())
    card=service.reply_flex.call_args.args[2]
    assert any(c.get('action',{}).get('text')=='日時を変更したい' for c in card['footer']['contents'])
    await service.handle_text_message(event('店舗を変更したい'),user())
    await service.handle_text_message(event('恵比寿店'),user())
    assert context(await database.get_session('u'))['time']=='11:00'

async def test_unclear_input_offers_choices_without_losing_draft(service,database):
    day=future()
    await service.handle_text_message(event(f'{day.month}/{day.day} 半蔵門空いてる？'),user())
    before=await database.get_session('u')
    await service.handle_text_message(event('えーっとどうしようかな'),user())
    assert await database.get_session('u')==before
    assert len(service.reply_text.call_args.kwargs['quick_reply'].items)==3

async def test_staff_consultation_confirmation_and_resume(service,database):
    day=future()
    await service.handle_text_message(event(f'{day.month}/{day.day} 半蔵門 10:00'),user())
    before=await database.get_session('u')
    await service.handle_text_message(event('石原さんに相談したい'),user())
    await service.handle_text_message(event('当日の持ち物を教えてください'),user())
    action=confirm_action(service)
    assert await database.notification_backlog()==[]
    await service.handle_postback_event(event(data=action),user())
    assert context(await database.get_session('u'))==context(before)
    notices=await database.notification_backlog()
    assert len(notices)==1 and '持ち物' in notices[0]['body']
    await service.handle_postback_event(event(data=action),user())
    assert len(await database.notification_backlog())==1

async def test_native_waitlist_intake_offer_accept_without_sheet_projection(service,database,monkeypatch):
    day=future()
    await service.handle_text_message(event(f'{day.month}/{day.day} 半蔵門 10:00'),user())
    before=await database.get_session('u')
    await service.handle_text_message(event('空いたら教えて'),user())
    assert await database.waiting_requests()==[]
    await service.handle_postback_event(event(data=confirm_action(service)),user())
    waiting=await database.waiting_requests()
    assert len(waiting)==1 and context(await database.get_session('u'))==context(before)
    monkeypatch.setattr(waitlist_service.sheets_service,'fetch_waitlist',lambda:[])
    monkeypatch.setattr(waitlist_service.calendar_service,'fetch_all_bookings',lambda:ls.BookingData([],[],[]))
    assert (await waitlist_service.check_waitlist())['offered']==1
    assert (await waitlist_service.check_waitlist())['offered']==0
    api=AsyncMock();await flush_notifications(api,limit=10)
    assert await database.notification_backlog()==[]
    offered=await database.get_waitlist(waiting[0]['id'],'u')
    action=json.loads(await database.make_action('u',{'a':'waitlist_accept','wid':offered['id']}))
    await service.handle_postback_event(event(data=action),user())
    assert (await database.get_waitlist(offered['id'],'u'))['state']=='accepted'
    assert all(row['kind']!='sheet' for row in await database.notification_backlog())

async def test_support_back_does_not_notify(service,database):
    await service.handle_text_message(event('スタッフに相談したい'),user())
    await service.handle_text_message(event('やめる'),user())
    assert await database.notification_backlog()==[]

async def test_withdraw_waitlist_suppresses_queued_offer(service,database):
    day=future()
    await database.request_waitlist('native','u',{'dates':[day.strftime('%Y-%m-%d')],'store':'ebisu','time':None,'filters':{},'source':'chat'},'waiting')
    await database.save_waitlist_offer('native','u',{'date':day.strftime('%Y-%m-%d'),'source':'chat'},{'type':'bubble','body':{'type':'box','layout':'vertical','contents':[{'type':'text','text':'offer'}]}})
    await service.handle_text_message(event('キャンセル待ちを取り消して'),user())
    card=service.reply_flex.call_args.args[2]['contents'][0]
    await service.handle_postback_event(event(data=json.loads(card['footer']['contents'][0]['action']['data'])),user())
    assert (await database.get_waitlist('native','u'))['state']=='cancelled'
    api=AsyncMock();await flush_notifications(api,limit=10)
    assert all(call.args[0].to!='u' for call in api.push_message.call_args_list)
    assert await database.get_user_bookings('u',True)==[]

async def test_expired_waitlist_and_foreign_withdraw_are_safe(database):
    await database.request_waitlist('old','u',{'dates':['2020-01-01'],'source':'chat'},'old')
    assert not await database.withdraw_waitlist('old','other')
    assert await database.waiting_requests()==[]
    assert (await database.get_waitlist('old','u'))['state']=='expired'

async def test_waitlist_registration_atomic_and_idempotent(database,monkeypatch):
    from config import settings
    payload={'dates':[future().strftime('%Y-%m-%d')],'source':'chat'}
    monkeypatch.setattr(settings,'ADMIN_USER_ID','')
    with pytest.raises(ValueError): await database.request_waitlist('same','u',payload,'request')
    assert await database.get_waitlist('same','u') is None
    monkeypatch.setattr(settings,'ADMIN_USER_ID','audit-admin')
    assert await database.request_waitlist('same','u',payload,'request')
    assert not await database.request_waitlist('same','u',payload,'request')
    assert len(await database.notification_backlog())==1

async def test_filtered_query_can_receive_time_text(service,database):
    day=future()
    await service.handle_text_message(event(f'{day.month}/{day.day} 半蔵門 19時以降で'),user())
    assert times(service) and all(a['label'].split()[-1]>='19:00' for a in times(service))
    time=times(service)[0]['label'].split()[-1]
    await service.handle_text_message(event(time),user())
    assert (await database.get_session('u'))['flow_state']=='confirm'

async def test_unavailable_primary_suggests_next_day(service,database,monkeypatch):
    day=future();later=day+timedelta(days=1)
    monkeypatch.setattr(ls,'get_available_slots',lambda date,store,snapshot:[date.replace(hour=10)] if date.date()==later.date() and store=='ebisu' else [])
    await service.handle_text_message(event(f'{day.month}/{day.day} 恵比寿で空いてる？'),user())
    choices=[await database.get_action(json.loads(a['data'])['id'],'u') for a in times(service)]
    assert choices and all(a['date']==later.strftime('%Y-%m-%d') and a['store']=='ebisu' for a in choices)

async def test_waitlist_time_correction_retains_date_and_store(service,database):
    day=future()
    await service.handle_text_message(event(f'{day.month}/{day.day} 半蔵門 10:15 キャンセル待ち'),user())
    session=await database.get_session('u')
    assert session['flow_state']=='collect'
    assert context(session)['dates']==[day.strftime('%Y-%m-%d')]
    assert await database.waiting_requests()==[]
    await service.handle_text_message(event('10:30'),user())
    assert (await database.get_session('u'))['flow_state']=='confirm'
    await service.handle_postback_event(event(data=confirm_action(service)),user())
    rows=await database.waiting_requests()
    assert len(rows)==1
    payload=json.loads(rows[0]['payload'])
    assert payload['time']=='10:30' and payload['store']=='hanzoomon'

async def test_edited_support_rejects_old_confirmation(service,database):
    await service.handle_text_message(event('スタッフに相談したい'),user())
    await service.handle_text_message(event('持ち物を教えてください'),user())
    old=confirm_action(service)
    await service.handle_text_message(event('場所を教えてください'),user())
    latest=confirm_action(service)
    await service.handle_postback_event(event(data=old),user())
    assert await database.notification_backlog()==[]
    await service.handle_postback_event(event(data=latest),user())
    notices=await database.notification_backlog()
    assert len(notices)==1 and '場所' in notices[0]['body']

async def test_preferred_store_survives_date_paging(service,database):
    await service.handle_text_message(event('来週、恵比寿がダメなら半蔵門で'),user())
    await tap(service,next(a for a in buttons(service) if '次の日程' in a['label']))
    choices=[await database.get_action(json.loads(a['data'])['id'],'u') for a in times(service)]
    assert choices and all(a['store']=='ebisu' for a in choices)
