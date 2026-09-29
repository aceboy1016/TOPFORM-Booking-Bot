import json
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
from tests.test_flows import event,user,future,customer
from tests.test_conversation import reserve,state,confirm_action

@pytest.mark.parametrize('second_available',[True,False,None])
@pytest.mark.parametrize('different_day',[False,True])
async def test_change_alternatives_are_compared_before_selection(service,database,monkeypatch,second_available,different_day):
    bid,day=await reserve(database,hour=17)
    import candidate_options
    monkeypatch.setattr(candidate_options,'check_availability',lambda slot,*a:{'is_available':second_available is not None and (slot.hour==10 or second_available),'rooms_available':['B']})
    date=day.strftime('%Y/%m/%d')
    other=(day+timedelta(days=1) if different_day else day).strftime('%Y/%m/%d')
    text=f'{date}17時からの予約を下記のどちらかに変更できますか？\n【予約希望】\n・{date} 10:00〜11:00 @恵比寿\n・{other} 12:00〜13:00 @恵比寿\n候補の中で可能な日時は？'
    await service.handle_text_message(event(text),user())
    cards=service.reply_flex.call_args.args[2]['contents']
    assert len(cards)==2
    assert '10:00〜11:00' in json.dumps(cards[0],ensure_ascii=False)
    assert '12:00〜13:00' in json.dumps(cards[1],ensure_ascii=False)
    assert ('footer' in cards[1])==bool(second_available)
    assert len(await database.get_user_bookings('u'))==1
    _,data=await state(database)
    assert data['target_booking_id']==bid and 'confirmation_id' not in data
    if second_available is None:
        assert all('footer' not in c for c in cards)
        return
    selected=cards[1] if second_available else cards[0]
    action=json.loads(selected['footer']['contents'][0]['action']['data'])
    await service.handle_postback_event(event(data=action),user())
    s,data=await state(database)
    assert s['flow_state']=='confirm'
    assert data['time']==('12:00' if second_available else '10:00')
    assert data['target_booking_id']==bid
    assert len(await database.get_user_bookings('u'))==1
