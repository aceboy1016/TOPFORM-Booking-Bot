import json
from datetime import timedelta
import pytest
from tests.test_flows import event, user, future, customer
from tests.test_conversation import confirm_action
import line_service as ls


def buttons(service):
    payload = service.reply_messages.call_args.args[1][0].contents.to_dict()
    result = []
    def walk(value):
        if isinstance(value, dict):
            if value.get('type') == 'postback': result.append(value)
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(payload)
    return result

async def tap(service, action):
    await service.handle_postback_event(event(data=json.loads(action['data'])), user())

@pytest.mark.parametrize('use_button', [False, True])
async def test_inquiry_unavailable_time_then_booking(service, database, monkeypatch, use_button):
    dt=future().replace(hour=19,minute=30)
    # Both the listing and final availability check use controlled availability.
    monkeypatch.setattr(ls,'get_available_slots',lambda day,store,snapshot: [dt,dt+timedelta(minutes=30)] if store=='hanzoomon' else [])
    monkeypatch.setattr(ls,'check_availability',lambda slot,store,snapshot: {'is_available':store=='hanzoomon' and slot in [dt,dt+timedelta(minutes=30)],'rooms_available':[]})
    await service.handle_text_message(event('明後日恵比寿で空いてるとこない？'),user())
    await service.handle_text_message(event('金曜日は？'),user())
    assert json.loads((await database.get_session('u'))['flow_data'])['store']=='ebisu'
    await service.handle_text_message(event('日曜日は？'),user())
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 半蔵門13:00'),user())
    context=json.loads((await database.get_session('u'))['flow_data'])
    assert context['store']=='hanzoomon' and context['date']==dt.strftime('%Y-%m-%d')
    assert await database.get_user_bookings('u',True)==[]
    slot=next(a for a in buttons(service) if '19:30' in a['label'])
    if use_button: await tap(service,slot)
    else: await service.handle_text_message(event('19:30'),user())
    assert (await database.get_session('u'))['flow_state']=='confirm'
    assert await database.get_user_bookings('u',True)==[]
    confirm=confirm_action(service)
    await service.handle_postback_event(event(data=confirm),user())
    rows=await database.get_user_bookings('u',True)
    assert len(rows)==1 and rows[0]['store']=='hanzoomon' and '19:30' in rows[0]['slot_datetime']
    assert len(await database.pending_notifications())==1
    await service.handle_postback_event(event(data=confirm),user())
    assert len(await database.get_user_bookings('u',True))==1

async def test_pagination_and_stale_card(service,database):
    dt=future()
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 恵比寿空いてる？'),user())
    first=buttons(service)
    await tap(service,next(a for a in first if '次の時間' in a['label']))
    later=buttons(service)
    assert any(a['label'].startswith('🕐') and a['label'] not in [b['label'] for b in first] for a in later)
    old=next(a for a in first if a['label'].startswith('🕐'))
    await service.handle_text_message(event('明日は？'),user())
    await tap(service,old)
    assert '終了' in service.reply_text.call_args.args[1]
    assert await database.get_user_bookings('u',True)==[]

async def test_foreign_button_and_availability_changed(service,database,monkeypatch):
    dt=future()
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 恵比寿空いてる？'),user())
    action=next(a for a in buttons(service) if a['label'].startswith('🕐'))
    other=event(data=json.loads(action['data']));other.source.user_id='other'
    await service.handle_postback_event(other,user())
    assert await database.get_session('other') is None
    monkeypatch.setattr(ls,'check_availability',lambda *args: {'is_available':False})
    await tap(service,action)
    assert (await database.get_session('u'))['flow_state']=='select_time'
    assert await database.get_user_bookings('u',True)==[]

async def test_both_store_time_is_retained_until_store_selected(service,database):
    dt=future()
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 空いてる？'),user())
    await service.handle_text_message(event('10:00'),user())
    assert (await database.get_session('u'))['flow_state']=='select_store_after_date'
    await service.handle_text_message(event('半蔵門でお願いします'),user())
    session=await database.get_session('u')
    data=json.loads(session['flow_data'])
    assert session['flow_state']=='confirm' and data['time']=='10:00' and data['store']=='hanzoomon'

async def test_confirmation_checks_fresh_availability(service,database,monkeypatch):
    dt=future()
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 半蔵門10:00'),user())
    action=confirm_action(service)
    monkeypatch.setattr(ls,'check_availability',lambda *args: {'is_available':False})
    await service.handle_postback_event(event(data=action),user())
    assert await database.get_user_bookings('u',True)==[]
    assert await database.pending_notifications()==[]

async def test_evening_filter_survives_paging(service,database):
    dt=future()
    await service.handle_text_message(event(f'{dt.month}/{dt.day} 恵比寿 夜空いてる？'),user())
    times=[a['label'] for a in buttons(service) if a['label'].startswith('🕐')]
    assert times and all(int(t.split()[1].split(':')[0])>=17 for t in times)
