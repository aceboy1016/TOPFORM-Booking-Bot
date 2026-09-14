import json
from datetime import datetime,timedelta
from unittest.mock import AsyncMock
from sqlalchemy import update
from database import outbox
from notifications import flush_notifications
from booking_rules import JST
from tests.storage_helpers import patch_rows

async def test_retry_uses_same_key(database):
    await database.enqueue('key','user','message')
    api=AsyncMock();api.push_message.side_effect=RuntimeError('temporary')
    await flush_notifications(api)
    key=api.push_message.call_args.kwargs['x_line_retry_key']
    await patch_rows(database,outbox,{'lease_until':None})
    api.push_message.side_effect=None
    await flush_notifications(api)
    assert api.push_message.call_args.kwargs['x_line_retry_key']==key
    assert await database.notification_backlog()==[]

async def test_old_uncertain_delivery_requires_manual_review(database):
    await database.enqueue('key','user','message')
    await patch_rows(database,outbox,{'created_at':(datetime.now(JST)-timedelta(days=2)).isoformat()})
    api=AsyncMock();await flush_notifications(api)
    assert api.push_message.await_count==0
    assert (await database.notification_backlog())[0]['state']=='review'

async def test_flex_and_sheet_projection_are_durable(database):
    await database.save_waitlist_offer('id','user',{}, {'type':'bubble','body':{'type':'box','layout':'vertical','contents':[{'type':'text','text':'test'}]}})
    api=AsyncMock();await flush_notifications(api)
    rows=await database.notification_backlog()
    assert len(rows)==1 and rows[0]['kind']=='sheet'

async def test_stale_offer_projection_does_not_overwrite_response(database,monkeypatch):
    import notifications
    await database.save_waitlist_offer('id','user',{}, {})
    await database.respond_waitlist('id','user','accepted','notice')
    await database.enqueue('sheet-offer:id','sheets',json.dumps({'id':'id','status':'通知済み'}),'sheet')
    calls=[]
    async def google_call(fn,*args): calls.append(args)
    monkeypatch.setattr('async_services.google_call',google_call)
    await patch_rows(database,outbox,{'state':'sent'},'kind','sheet',negate=True)
    await flush_notifications(AsyncMock())
    assert ('id','通知済み') not in calls
    assert ('id','承諾') in calls
