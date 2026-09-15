import json
from unittest.mock import AsyncMock
import pytest
from tests.test_flows import event,user,customer,future
from tests.test_conversation import reserve
from notifications import flush_notifications
from database import outbox
from tests.storage_helpers import records

@pytest.mark.parametrize('message',['キャンセル待ちお願いします','空いたら教えて','キャンセル待ちを取り消して'])
async def test_waitlist_requests_do_not_cancel_or_notify(service,database,message):
    bid,_=await reserve(database)
    before=await database.notification_backlog()
    await service.handle_text_message(event(message),user())
    assert '受付は終了' in service.reply_text.call_args.args[1]
    assert await database.waiting_requests()==[]
    assert await database.notification_backlog()==before
    assert (await database.get_booking(bid,'u'))['status']=='provisional'

@pytest.mark.parametrize('name',['waitlist_accept','waitlist_decline','waitlist_withdraw'])
async def test_old_waitlist_buttons_cannot_resume_feature(service,database,name):
    await database.save_waitlist_offer('legacy','u',{}, {})
    token=json.loads(await database.make_action('u',{'a':name,'wid':'legacy'}))
    await service.handle_postback_event(event(data=token),user())
    assert (await database.get_waitlist('legacy','u'))['state']=='offered'
    assert '受付は終了' in service.reply_text.call_args.args[1]
    assert await database.get_user_bookings('u')==[]

async def test_old_support_confirmation_does_not_register_waitlist(service,database):
    await database.set_session('u','support','confirm',json.dumps({'kind':'waitlist','id':'old'}))
    token=json.loads(await database.make_action('u',{'a':'support_confirm','support_id':'old'}))
    await service.handle_postback_event(event(data=token),user())
    assert await database.waiting_requests()==[] and await database.notification_backlog()==[]
    assert await database.get_session('u') is None

async def test_all_retired_notice_kinds_discard_without_external_calls(database):
    for i,(kind,body) in enumerate([('flex:legacy','{}'),('sheet','{}'),('text','🔔 キャンセル待ち受付\nname'),('text','キャンセル待ち 承諾\nname'),('text','🔔 キャンセル待ちの取り下げ\nname')]):
        await database.enqueue(str(i),'u',body,kind)
    await database.enqueue('booking','u','✅ ご予約が確定しました')
    api=AsyncMock()
    await flush_notifications(api,limit=20)
    assert api.push_message.await_count==1
    assert api.push_message.call_args.args[0].messages[0].text=='✅ ご予約が確定しました'
    assert await database.notification_backlog()==[]
    rows=await records(database,outbox)
    assert sum(r['state']=='discarded' for r in rows)==5
    assert len(rows)==6

async def test_old_scheduler_is_noop():
    from waitlist_service import check_waitlist
    assert await check_waitlist()=={'status':'disabled','reason':'waitlist_retired'}
