"""Durable waitlist offers. Calendar remains read-only."""
import json
from datetime import datetime, timedelta
from database import db
from sheets_service import sheets_service
from calendar_service import calendar_service, check_availability
from async_services import google_call
from booking_rules import parse_slot, JST
from config import STORE_NAMES

async def check_waitlist():
    entries=await google_call(sheets_service.fetch_waitlist)
    if not entries: return {'offered':0}
    snapshot=await google_call(calendar_service.fetch_all_bookings)
    count=0
    for entry in entries:
        if await db.get_waitlist(entry['id'],entry['line_id']): continue
        customer=await google_call(sheets_service.get_customer_by_line_id,entry['line_id'])
        if not customer: continue
        try: slot=parse_slot(entry['date'],entry['time'])
        except ValueError: continue
        raw=entry['store']
        stores=[s for s,n in STORE_NAMES.items() if n.replace('店','') in raw or s==raw]
        if any(w in raw for w in ('または','どちら','両店舗')): stores=list(STORE_NAMES)
        for store in stores:
            if not check_availability(slot,store,snapshot)['is_available']: continue
            payload={'date':entry['date'],'time':entry['time'],'store':store,'expires_at':(datetime.now(JST)+timedelta(minutes=30)).isoformat()}
            buttons=[]
            for action,label in [('waitlist_accept','受けます'),('waitlist_decline','見送ります')]:
                token=await db.make_action(entry['line_id'],{'a':action,'wid':entry['id']})
                buttons.append({'type':'button','action':{'type':'postback','label':label,'data':token}})
            flex={'type':'bubble','body':{'type':'box','layout':'vertical','contents':[{'type':'text','text':'空き枠のお知らせ','weight':'bold'},{'type':'text','text':f"{entry['date']} {entry['time']} {STORE_NAMES[store]}",'wrap':True},{'type':'text','text':'30分以内にお返事ください。仮予約の受付で、枠の確保はスタッフ確認後です。','wrap':True,'size':'sm'}]},'footer':{'type':'box','layout':'horizontal','contents':buttons}}
            if await db.save_waitlist_offer(entry['id'],entry['line_id'],payload,flex): count+=1
            break
    return {'offered':count}
