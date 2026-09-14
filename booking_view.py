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
    pending_signatures={(as_jst(datetime.fromisoformat(r['slot_datetime'])),r['store']) for r in rows if r['status']=='provisional'}
    for b in unique.values():
        if await db.is_done('calendar-cancel:'+user_id+':'+b.id):
            cancelled_signatures.add((b.start_dt,b.store))
            continue
        if (b.start_dt,b.store) in pending_signatures: continue
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


async def monthly_usage_reply(service, token, uid, user, session):
    """Answer a side question without mutating the active booking draft."""
    import json
    from booking_rules import parse_slot
    from config import STORE_NAMES
    entries = await user_bookings(service, uid, user, include_past=True)
    now = datetime.now(JST)
    # Pending changes replace the original in the *planned* count only.
    # The real original booking remains untouched until staff approval.
    rows = await db.get_user_bookings(uid, include_past=True)
    visible_ids = {b['id'] for b in entries}
    replacements = {(r['metadata']['change_from']['type'], r['metadata']['change_from']['id'])
                    for r in rows if r['public_id'] in visible_ids and r.get('metadata',{}).get('change_from')}
    count_entries = [b for b in entries if b['dt']<=now or (b['type'],b['id']) not in replacements]
    month = [b for b in count_entries if (b['dt'].year, b['dt'].month) == (now.year, now.month)]
    completed = sum(b['status']=='confirmed' and b['dt']+timedelta(hours=1)<=now for b in month)
    scheduled = [b for b in month if b['dt']>now]
    provisional = sum(b['status']=='provisional' for b in scheduled)
    lines = [f'📊 今月（{now.month}月）のご利用状況です😊', '',
             f'✅ 利用済み：{completed}回', f'📅 これからの予約：{len(scheduled)}件（うち仮予約 {provisional}件）']
    context = json.loads(session.get('flow_data','{}')) if session else {}
    if context.get('paused_booking'):
        session = context['paused_booking']
        context = json.loads(session['flow_data'])
    selected = None
    proposed = bool(context.get('date') and context.get('time') and context.get('store') in STORE_NAMES)
    if proposed:
        selected = {'dt':parse_slot(context['date'],context['time']), 'store':context['store']}
    else:
        ident = context.get('target_booking_id') or context.get('last_request')
        selected = next((b for b in entries if b['id']==ident), None)
    if selected and (selected['dt'].year,selected['dt'].month)==(now.year,now.month):
        timeline = [b for b in month if b['status']=='confirmed' or b['dt']>now]
        if proposed and context.get('mode')=='change':
            timeline = [b for b in timeline if not (b['id']==context.get('target_booking_id') and b['type']==context.get('target_booking_type'))]
        earlier = {(b['dt'],b['store']) for b in timeline if b['dt']<selected['dt']}
        lines += ['', '🕐 '+selected['dt'].strftime('%m/%d %H:%M')+' '+STORE_NAMES[selected['store']],
                  f'この予約は、今ある予定どおりなら今月{len(earlier)+1}回目になります。']
    elif selected:
        lines += ['', '📅 選択中の予約は'+selected['dt'].strftime('%m月%d日')+'です（今月分には含みません）。']
    lines += ['', '💡 仮予約は利用済みには含めず、予定の順番に含めています。']
    if session and session.get('flow_type')=='booking':
        lines += ['', '😊 '+('変更' if context.get('mode')=='change' else '予約')+'の途中の内容はそのままです。前の時間ボタンや日時の入力で続けられます。']
    await service.reply_text(token, '\n'.join(lines))
