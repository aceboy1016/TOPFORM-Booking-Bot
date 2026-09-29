"""Compare explicit alternatives without submitting or choosing one for the member."""
import json
from datetime import timedelta
from database import db
from config import STORE_NAMES
from booking_rules import parse_slot
from calendar_service import check_availability
from booking_cards import card, details, button


async def show(service, token, uid, text, data):
    entries=service._parse_hayamihyo_bulk(text)
    if len(entries)<2:
        return False
    if len(entries)>10:
        await service.reply_text(token,'📅 候補は一度に10件まで比較できます😊\n10件以内に分けて送ってください。')
        return True
    snapshot=await service._get_bookings(force=True)
    cards=[]
    for entry in entries:
        store=entry['store'] if entry['store_explicit'] else data.get('store','ebisu')
        if store not in STORE_NAMES: store='ebisu'
        body=[];buttons=[]
        try:
            slot=parse_slot(entry['date_str'],entry['time_str'])
            end=parse_slot(entry['date_str'],entry['end_time'])
            result=check_availability(slot,store,snapshot) if end-slot==timedelta(hours=1) else {'is_available':False}
            body=details({'slot_datetime':slot.isoformat(),'store':store})
        except ValueError:
            result={'is_available':False}
            body=[{'type':'text','text':entry['display'],'wrap':True}]
        if result['is_available']:
            room=None
            rooms=result.get('rooms_available',[])
            if store=='ebisu' and rooms:
                preferred=data.get('room_pref')
                room=preferred if preferred in rooms else rooms[0]
                body.append({'type':'text','text':f'🚪 個室{room}でご案内できます😊','wrap':True})
            payload={'a':'pick_slot','date':entry['date_str'],'time':entry['time_str'],'store':store}
            if room: payload['room']=room
            action=await db.make_action(uid,payload,ttl=7*24*60)
            buttons=[button('この候補を選ぶ',action,True)]
            title='✅ こちらは空いています'
        else:
            title='🌿 この候補はご案内できません'
            body.append({'type':'text','text':'別の候補を選ぶか、ご希望の日時を教えてください😊','wrap':True,'size':'sm'})
        cards.append(card(title,'#167D8D',body,buttons))
    data=dict(data)
    for key in ('time','room','confirmation_id','pending_datetime_text','requested_time'):
        data.pop(key,None)
    await db.set_session(uid,'booking','select_date',json.dumps(data))
    await service.reply_flex(token,'📅 候補ごとの空きを確認しました。ご希望の候補を選んでください😊',{'type':'carousel','contents':cards})
    return True
