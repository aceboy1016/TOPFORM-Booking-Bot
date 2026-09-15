"""Drain durable notifications using LINE retry keys, independently of replies."""
import json
from datetime import datetime, timedelta
from linebot.v3.messaging import PushMessageRequest, TextMessage, FlexMessage, FlexContainer
from booking_rules import JST, as_jst
from database import db

async def flush_notifications(api,limit=5):
    if api is None: return
    for row in await db.pending_notifications(limit=limit):
        if row['kind']=='sheet' or row['kind'].startswith('flex:') or row['body'].startswith(('🔔 キャンセル待ち','キャンセル待ち 承諾','キャンセル待ち 辞退')):
            await db.discard_notification(row['id'])
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
