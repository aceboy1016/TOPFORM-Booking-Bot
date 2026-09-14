"""ASGI entrypoint: verified webhooks and authenticated operational endpoints."""
import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent
from config import settings
from booking_rules import JST
from calendar_service import calendar_service, CalendarUnavailable, get_available_slots, find_user_bookings
from sheets_service import sheets_service, SheetsUnavailable
from database import db, current_event
from line_service import line_service
from async_services import google_call
from notifications import flush_notifications

logger=logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app):
    missing=settings.validate()
    if missing: raise RuntimeError('Missing configuration: '+', '.join(missing))
    await db.init_db()
    try:
        await google_call(calendar_service.initialize_sync)
        await google_call(sheets_service.fetch_customer_master)
        await line_service.initialize()
        await line_service._get_bookings(force=True)
        yield
    finally:
        await line_service.close()
        await db.close()

app=FastAPI(title='TOPFORM Booking Bot',version='2.0.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

async def require_admin(request:Request):
    value=request.headers.get('authorization','')
    token=settings.ADMIN_API_TOKEN
    if len(token)<32 or not secrets.compare_digest(value,'Bearer '+token):
        raise HTTPException(401,'Authentication required',headers={'WWW-Authenticate':'Bearer'})

@app.exception_handler(CalendarUnavailable)
@app.exception_handler(SheetsUnavailable)
async def unavailable(request,exc):
    return JSONResponse(status_code=503,content={'detail':'External service temporarily unavailable'})

@app.api_route('/',methods=['GET','HEAD'])
async def root(): return {'status':'ok','service':'TOPFORM Booking Bot'}

@app.api_route('/health',methods=['GET','HEAD'])
async def health_check():
    try: await db.health(); database_ready=True
    except Exception: database_ready=False
    calendar_ready=bool(calendar_service.last_success and calendar_service._consecutive_errors==0)
    ready=not settings.validate() and database_ready and calendar_ready and line_service._api is not None
    return JSONResponse(status_code=200 if ready else 503,content={'status':'healthy' if ready else 'unavailable','services':{'database':database_ready,'calendar':calendar_ready,'line':line_service._api is not None}})

@app.post('/webhook')
async def webhook_handler(request:Request):
    signature=request.headers.get('X-Line-Signature','')
    if not signature or not settings.LINE_CHANNEL_SECRET: raise HTTPException(400,'Invalid webhook')
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>256*1024: raise HTTPException(413,'Webhook too large')
    try: events=WebhookParser(settings.LINE_CHANNEL_SECRET).parse(body.decode('utf-8'),signature)
    except (InvalidSignatureError,ValueError,UnicodeDecodeError): raise HTTPException(400,'Invalid webhook')
    for event in events: await process_event(event)
    return {'status':'ok'}

async def process_event(event):
    uid=getattr(event.source,'user_id',None)
    if not uid: return
    event_id=getattr(event,'webhook_event_id',None)
    if not event_id: raise HTTPException(400,'Webhook event ID required')
    key='event:'+event_id
    if await db.is_done(key):
        await flush_notifications(line_service._api)
        return
    owner=await db.claim(key,ttl=300)
    if not owner: raise HTTPException(503,'Event already processing')
    user_key='user:'+uid; user_owner=await db.claim(user_key,ttl=300)
    if not user_owner:
        await db.release(key,owner)
        raise HTTPException(503,'User operation already processing')
    context_token=current_event.set(event_id)
    completed=False
    try:
        user=await db.get_or_create_user(uid)
        if isinstance(event,FollowEvent): await line_service.handle_follow_event(event)
        elif isinstance(event,MessageEvent) and isinstance(event.message,TextMessageContent):
            await line_service.handle_text_message(event,user)
        elif isinstance(event,PostbackEvent): await line_service.handle_postback_event(event,user)
        completed=True
    except (CalendarUnavailable,SheetsUnavailable):
        # Never turn missing calendar data into availability. Event remains retryable.
        try: await line_service.reply_text(event.reply_token,'現在データを確認できません。時間を置いて再度お試しください。')
        except Exception: pass
        raise HTTPException(503,'External service unavailable')
    except Exception:
        logger.error('Webhook processing failed',extra={'event_id':event_id})
        raise HTTPException(503,'Processing temporarily unavailable')
    finally:
        current_event.reset(context_token)
        await db.release(key,owner,done=completed)
        await db.release(user_key,user_owner)
        # Outbox survives reply failures. Scheduler also retries pending deliveries.
        try: await flush_notifications(line_service._api)
        except Exception: logger.error('Outbox drain failed; pending deliveries retained')

@app.get('/api/availability/{date}')
async def get_availability(date:str,store:Literal['ebisu','hanzoomon']='ebisu'):
    try: target=JST.localize(datetime.strptime(date,'%Y-%m-%d'))
    except ValueError: raise HTTPException(400,'Use YYYY-MM-DD')
    snapshot=await line_service._get_bookings()
    slots=get_available_slots(target,store,snapshot)
    return {'date':date,'store':store,'available_slots':[s.strftime('%H:%M') for s in slots],'count':len(slots)}

@app.get('/api/bookings/{line_user_id}',dependencies=[Depends(require_admin)])
async def get_user_bookings(line_user_id:str):
    return {'bookings':await db.get_user_bookings(line_user_id,include_past=True)}

@app.post('/api/check-waitlist',dependencies=[Depends(require_admin)])
async def trigger_check_waitlist():
    from waitlist_service import check_waitlist
    try: return await check_waitlist()
    finally: await flush_notifications(line_service._api)

@app.post('/api/notifications/retry',dependencies=[Depends(require_admin)])
async def retry_notifications():
    await flush_notifications(line_service._api)
    return {'status':'processed'}

@app.get('/api/notifications',dependencies=[Depends(require_admin)])
async def notification_backlog():
    return {'notifications':await db.notification_backlog()}

@app.get('/api/requests',dependencies=[Depends(require_admin)])
async def pending_requests(): return {'requests':await db.pending_bookings()}

@app.get('/api/waitlist',dependencies=[Depends(require_admin)])
async def waitlist_overview(): return {'requests':await db.waitlist_overview()}

class ReviewRequest(BaseModel):
    status:Literal['confirmed','rejected']
    calendar_id:str=Field(default='',max_length=1024)

@app.post('/api/requests/{public_id}/review',dependencies=[Depends(require_admin)])
async def review_request(public_id:str,body:ReviewRequest):
    pending=await db.pending_bookings()
    row=next((r for r in pending if r['public_id']==public_id),None)
    if not row: raise HTTPException(409,'Request is not pending')
    if body.status=='confirmed':
        customer=await google_call(sheets_service.get_customer_by_line_id,row['line_user_id'])
        if not customer: raise HTTPException(409,'Customer is no longer registered')
        snapshot=await line_service._get_bookings(force=True)
        matches=find_user_bookings(customer['name'],snapshot,row['line_user_id'],allow_legacy=not customer.get('ambiguous_name',False))
        match=next((b for b in matches if b.id==body.calendar_id),None)
        if not match or match.start_dt.isoformat()!=row['slot_datetime'] or match.store!=row['store']:
            raise HTTPException(409,'Calendar event does not match the request')
    changed=await db.review_booking(public_id,body.status,body.calendar_id)
    if not changed: raise HTTPException(409,'Request was already reviewed')
    await flush_notifications(line_service._api)
    return {'status':body.status}

if __name__=='__main__':
    import uvicorn
    uvicorn.run('main:app',host=settings.HOST,port=settings.PORT,reload=settings.DEBUG)
