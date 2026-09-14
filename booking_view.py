"""Merge requests with their calendar counterpart without double counting."""
from datetime import datetime, timedelta
from database import db
from booking_rules import JST, as_jst
from calendar_service import calendar_service, find_user_bookings
from async_services import google_call

async def user_bookings(service,user_id,user,include_past=False):
    now=datetime.now(JST)
    rows=await db.get_user_bookings(user_id,include_past=include_past)
    snapshot=await service._get_bookings()
    cal=find_user_bookings(user.get('display_name',''),snapshot,user_id,allow_legacy=not user.get('ambiguous_name',False))
    if include_past:
        cal+=await google_call(calendar_service.fetch_user_past_bookings_this_month,user.get('display_name',''),user_id,not user.get('ambiguous_name',False))
    unique={b.id:b for b in cal}
    result=[]
    cancelled_signatures=set()
    for b in unique.values():
        if await db.is_done('calendar-cancel:'+user_id+':'+b.id):
            cancelled_signatures.add((b.start_dt,b.store))
            continue
        if not include_past and b.start_dt<=now: continue
        result.append({'id':b.id,'type':'cal','dt':b.start_dt,'store':b.store,'status':'confirmed'})
    cal_ids={b['id'] for b in result}
    signatures={(b['dt'],b['store']) for b in result}
    for row in rows:
        slot=as_jst(datetime.fromisoformat(row['slot_datetime']))
        calendar_id=row.get('metadata',{}).get('calendar_id')
        if (calendar_id and await db.is_done('calendar-cancel:'+user_id+':'+calendar_id)) or (slot,row['store']) in cancelled_signatures: continue
        if calendar_id in cal_ids or (slot,row['store']) in signatures: continue
        result.append({'id':row['public_id'],'type':'db','dt':slot,'store':row['store'],'status':row['status']})
    return sorted(result,key=lambda b:b['dt'])
