"""Drain durable notifications using LINE retry keys, independently of replies."""
import json
from datetime import datetime, timedelta
from linebot.v3.messaging import PushMessageRequest, TextMessage, FlexMessage, FlexContainer
from booking_rules import JST, as_jst
from database import db

async def flush_notifications(api,limit=5):
    if api is None: return
    for row in await db.pending_notifications(limit=limit):
        if row['kind']=='sheet':
            from sheets_service import sheets_service
            from async_services import google_call
            try:
                payload=json.loads(row['body'])
                state=await db.waitlist_state(payload['id'])
                if payload['status']!='通知済み' or state=='offered':
                    await google_call(sheets_service.update_waitlist_status,payload['id'],payload['status'])
                await db.notification_result(row['id'])
            except Exception as exc: await db.notification_result(row['id'],exc)
            continue
        if row['kind'].startswith('flex:') and await db.waitlist_state(row['kind'].split(':',1)[1])!='offered':
            await db.notification_result(row['id'])
            continue
        # LINE retry keys have a finite deduplication window. Do not automatically
        # resend an uncertain delivery after it has expired.
        if datetime.now(JST)-as_jst(datetime.fromisoformat(row['created_at']))>timedelta(hours=23):
            await db.notification_result(row['id'],RuntimeError('Manual delivery review required'),manual=True)
            continue
        try:
            if row['kind']=='card':
                contents=json.loads(row['body'])
                title=contents.get('header',{}).get('contents',[{}])[0].get('text','予約のお知らせ')
                messages=[FlexMessage(alt_text=title,contents=FlexContainer.from_dict(contents))]
            elif row['kind'].startswith('flex:'):
                messages=[FlexMessage(alt_text='空き枠のお知らせ',contents=FlexContainer.from_dict(json.loads(row['body'])))]
            else:
                messages=[TextMessage(text=row['body'][i:i+4500]) for i in range(0,len(row['body']),4500)]
            if len(messages)>5: raise ValueError('Notification too large')
            await api.push_message(PushMessageRequest(to=row['recipient'],messages=messages),x_line_retry_key=row['id'],_request_timeout=20)
        except Exception as exc:
            # 409 with the accepted-request ID means LINE accepted the original.
            if getattr(exc,'status',None)==409 and (getattr(exc,'headers',{}) or {}).get('x-line-accepted-request-id'):
                await db.notification_result(row['id'])
            else: await db.notification_result(row['id'],exc)
        else:
            await db.notification_result(row['id'])
