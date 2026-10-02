import json
from datetime import datetime,timedelta
from booking_rules import JST
from database import sessions
from tests.storage_helpers import patch_rows
from tests.test_flows import event,user,customer
from tests.test_conversation import reserve,confirm_action,state

async def test_delayed_change_selection_and_confirmation_keep_original(service,database):
    bid,day=await reserve(database,hour=20)
    await service.handle_text_message(event('予約変更'),user())
    card=service.reply_flex.call_args.args[2]['contents'][0]
    await service.handle_postback_event(event(data=json.loads(card['footer']['contents'][0]['action']['data'])),user())
    target=day+timedelta(days=7)
    while target.weekday()>4: target+=timedelta(days=1)
    action=json.loads(await database.make_action('u',{'a':'pick_slot','date':target.strftime('%Y-%m-%d'),'store':'hanzoomon','time':'21:00'},ttl=10080))
    await patch_rows(database,sessions,{'updated_at':(datetime.now(JST)-timedelta(hours=2)).isoformat()})
    await service.handle_postback_event(event(data=action),user())
    assert '変更内容' in service.reply_flex.call_args.args[1]
    confirmation=confirm_action(service)
    # Showing the same slot again must not make the previous identical consent loop.
    await service.handle_postback_event(event(data=action),user())
    await patch_rows(database,sessions,{'updated_at':(datetime.now(JST)-timedelta(days=1)).isoformat()})
    await service.handle_postback_event(event(data=confirmation),user())
    rows=await database.get_user_bookings('u')
    assert len(rows)==2
    new=next(r for r in rows if r['public_id']!=bid)
    assert new['metadata']['change_from']['id']==bid
    assert new['status']=='provisional'
    await service.handle_postback_event(event(data=confirmation),user())
    assert len(await database.get_user_bookings('u'))==2
