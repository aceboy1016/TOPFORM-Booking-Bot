"""Local conversational search and explicit support requests. No language API."""
import json
import re
import uuid
from datetime import datetime, timedelta
from linebot.v3.messaging import QuickReply, QuickReplyItem, MessageAction
from database import db
from config import STORE_NAMES, settings
from booking_rules import JST, parse_slot, booking_limit, slot_error
from availability_search import filters_from, matching, upcoming_days, preferred_stores
from booking_view import user_bookings


async def restore(uid, paused):
    if paused: await db.set_session(uid,paused['flow_type'],paused['flow_state'],paused['flow_data'])
    else: await db.clear_session(uid)


async def clarify(service,token):
    await service.reply_text(token,'🤔 ご希望を確認させてください😊\n空き時間を探す・予約を変更する・スタッフに相談する、どれをご希望ですか？\n\n途中の予約内容はそのままです。',quick_reply=QuickReply(items=[QuickReplyItem(action=MessageAction(label=label,text=text)) for label,text in [('📅 空き確認','空き確認したい'),('🔄 予約変更','予約を変更したい'),('💬 スタッフ相談','スタッフに相談したい')]]))


async def route(service,event,user,session):
    text=event.message.text.strip()
    uid,token=event.source.user_id,event.reply_token
    data=json.loads(session.get('flow_data','{}')) if session else {}
    if session and session.get('flow_type')=='support':
        return await support_message(service,event,user,session,data)
    if re.search(r'スタッフ|石原さん|担当者',text) and re.search(r'相談|話したい|聞きたい|連絡したい',text):
        await start_support(service,event,user,session,'consult');return True
    if 'キャンセル待ち' in text and re.search(r'やめ|取り消|取消|中止',text):
        rows=await db.user_waitlists(uid)
        if not rows:
            await service.reply_text(token,'🌱 受付中のキャンセル待ちはありません。予約自体は取り消していません。');return True
        cards=[]
        for row in rows[:10]:
            payload=json.loads(row['payload']);dates=payload.get('dates') or [payload.get('date','')]
            action=await db.make_action(uid,{'a':'waitlist_withdraw','wid':row['id']})
            cards.append(service._build_confirm_flex('🔔 待ち希望の取り下げ', '📅 '+dates[0]+'\nこのキャンセル待ちだけを取り下げますか？\n通常の予約はそのまま残ります。','この待ち希望を取り下げる',action,'#B45309'))
        await service.reply_flex(token,'🔔 取り下げるキャンセル待ちを選択',{'type':'carousel','contents':cards});return True
    if re.search(r'キャンセル待ち|空いたら.*(?:教えて|知らせて|連絡)',text):
        await start_support(service,event,user,session,'waitlist');return True
    if re.search(r'(?:もう|これ|この予約|さっき).*(?:確定して|確定済み|仮予約)|予約.*(?:状況|状態)',text):
        entries=await user_bookings(service,uid,user)
        ident=data.get('target_booking_id') or data.get('last_request')
        selected=[b for b in entries if b['id']==ident] if ident else entries
        if session and session.get('flow_state')=='confirm':
            message='📋 選択中の内容は、まだ申し込まれていません。\n「仮予約を申し込む」を押すと受付します😊'
        elif not selected:
            message='🌱 これからの予約は見つかりませんでした。\n希望日時を送っていただければ空きを確認します😊'
        else:
            message='📖 ご予約の状態です😊\n\n'+'\n\n'.join('📅 '+b['dt'].strftime('%m/%d %H:%M')+' '+STORE_NAMES[b['store']]+'\n'+('⏳ 仮予約・スタッフ確認待ちです。まだ確定していません。' if b['status']=='provisional' else '✅ 確定済みです。') for b in selected[:10])
        await service.reply_text(token,message);return True
    active=session and session.get('flow_type')=='booking'
    if not active and data.get('paused_booking'):
        session=data['paused_booking'];data=json.loads(session['flow_data']);active=True
    if active and re.search(r'(?:日時|店舗)を変更したい',text):
        if '日時' in text:
            await db.set_session(uid,'booking','select_date',json.dumps(data))
            await service.reply_text(token,'📅 変更後の日時を教えてください😊\n前の時間カードから選び直しても大丈夫です。')
        else:
            if data.get('date') and data.get('time'): data['pending_datetime_text']=data['date']+' '+data['time']
            await db.set_session(uid,'booking','select_store',json.dumps(data))
            await service.reply_text(token,'📍 どちらの店舗にしますか？😊',quick_reply=QuickReply(items=[QuickReplyItem(action=MessageAction(label=n,text=n)) for n in STORE_NAMES.values()]))
        return True
    if active and re.search(r'さっき|前の',text) and re.search(r'戻|時間|候補',text):
        history=list(data.get('search_history',[]))
        if history:
            previous=history.pop()
            for key in ('date','time','picker_dates','filters','store','preferred_stores'): data.pop(key,None)
            data.update(previous);data['search_history']=history
            data['picker_id']=uuid.uuid4().hex
            await db.set_session(uid,'booking','select_time' if data.get('date') and data.get('store') in STORE_NAMES else 'select_store_after_date',json.dumps(data))
            await service._show_available_cards(token,uid,data,note='↩️ 前の候補です。最新の空きを確認しました😊')
        else:
            await service.reply_text(token,'📅 戻したい日時を教えてください😊\nトークに残っている時間カードから選ぶこともできます。')
        return True
    if re.search(r'キャンセル|取り消|取消|やめ|中止',text): return False
    preference=preferred_stores(text)
    earliest=bool(re.search(r'一番早|最短|最速|直近.*空|すぐ.*取れる',text))
    relative=bool(re.search(r'ほかの時間|他の時間|遅め|早め|もう少し遅|もう少し早',text))
    time_filter=bool(re.search(r'午前|午後|朝|夕方|夜|\d(?:時|:\d{2})(?:半)?(?:以降|まで)|いつでも|何時でも',text))
    period=bool(re.search(r'今週|来週|再来週|週末|今月|来月|から.+まで',text))
    if preference or earliest or relative or time_filter or period or text=='空き確認したい':
        if not active: data={'room_pref':user.get('room_pref')}
        explicit=[key for key,name in STORE_NAMES.items() if name.replace('店','') in text]
        if preference: data.update(store='both',preferred_stores=preference)
        elif len(explicit)==1: data['store']=explicit[0];data.pop('preferred_stores',None)
        data.setdefault('store','both')
        reference=service._extract_time(data.get('time',''))
        shown=data.get('last_shown',[])
        if not reference and shown: reference=service._extract_time(shown[-1] if '遅' in text else shown[0])
        filters=filters_from(text,data.get('filters'),reference[0]*60+reference[1] if reference else None)
        if relative and ('ほか' in text or '他の' in text): filters['exclude']=[data['time']] if data.get('time') else shown
        data['filters']=filters
        dates=service._parse_multiple_dates(text)
        if earliest:
            snapshot=await service._get_bookings()
            dates=[]
            from line_service import get_available_slots
            stores=preference or ([data['store']] if data['store'] in STORE_NAMES else list(STORE_NAMES))
            for day in upcoming_days():
                if any(matching(get_available_slots(day,store,snapshot),filters) for store in stores): dates=[day];break
            if not dates:
                await service.reply_text(token,'🌿 予約できる期間内に、ご希望に合う空きがありませんでした。\n「キャンセル待ち」や「スタッフに相談したい」も利用できます。');return True
        if not dates:
            dates=[datetime.fromisoformat(d) for d in data.get('picker_dates',[]) ] or ([datetime.fromisoformat(data['date'])] if data.get('date') else [])
        if not dates:
            await db.set_session(uid,'booking','select_date',json.dumps(data))
            await service.reply_text(token,'📅 いつ頃をご希望ですか？😊\n「今週」「来週」「9/20〜9/25」のように期間でも探せます。');return True
        await service._process_select_date(token,uid,session or {},' '.join(d.strftime('%Y-%m-%d') for d in dates),data)
        return True
    return False


def wait_description(data):
    from availability_search import filter_label
    days='・'.join(data['dates'][:7])+(' ほか'+str(len(data['dates'])-7)+'日' if len(data['dates'])>7 else '')
    return '📅 '+days+'\n📍 '+STORE_NAMES.get(data['store'],'両店舗')+'\n🕐 '+(data.get('time') or filter_label(data['filters']) or '空き時間はいつでも')


def valid_wait_dates(data):
    stores=list(STORE_NAMES) if data.get('store')=='both' else [data.get('store')]
    dates=[]
    for date in data.get('dates',[]):
        day=datetime.fromisoformat(date)
        slots=[parse_slot(date,data['time'])] if data.get('time') else [day+timedelta(minutes=m) for m in range(0,1440,30)]
        slots=matching(slots,data.get('filters',{}))
        if any(slot_error(slot,store) is None for slot in slots for store in stores): dates.append(date)
    return dates


async def start_support(service,event,user,paused,kind):
    previous=json.loads(paused.get('flow_data','{}')) if paused else {}
    if previous.get('paused_booking'): previous=json.loads(previous['paused_booking']['flow_data'])
    data={'kind':kind,'id':uuid.uuid4().hex,'paused':paused,'store':previous.get('store'),
          'dates':previous.get('picker_dates') or ([previous['date']] if previous.get('date') else []),
          'time':previous.get('time') or previous.get('requested_time'),'filters':previous.get('filters',{})}
    await db.set_session(event.source.user_id,'support','collect',json.dumps(data))
    await support_message(service,event,user,{'flow_state':'collect'},data,initial=True)


async def support_message(service,event,user,session,data,initial=False):
    text=event.message.text.strip();uid,token=event.source.user_id,event.reply_token
    if re.search(r'やめる|やめます|中止|戻る',text) or text in ('キャンセル','取消','取り消し'):
        await restore(uid,data.get('paused'))
        await service.reply_text(token,'👌 送信せずに元の操作へ戻りました。予約はそのままです。');return True
    if session.get('flow_state')=='confirm' and text in ('はい','お願いします','送信する','申し込む'):
        await confirm_support(service,token,uid,user,data);return True
    if data['kind']=='consult':
        if initial:
            await service.reply_text(token,'💬 ご相談内容を教えてください😊\n内容を確認してからスタッフへ送れます。予約の途中の内容は保持しています。');return True
        data['message']=text[:1500]
    else:
        dates=service._parse_multiple_dates(text)
        if dates: data['dates']=[d.strftime('%Y-%m-%d') for d in dates]
        stores=[key for key,name in STORE_NAMES.items() if name.replace('店','') in text]
        if stores: data['store']=stores[0] if len(stores)==1 else 'both'
        if 'どちらでも' in text or '両店舗' in text: data['store']='both'
        time=service._extract_time(text)
        if time: data['time']='%02d:%02d'%time
        data['filters']=filters_from(text,data.get('filters'))
        if re.search(r'以降|まで|午前|午後|夜|いつでも|何時でも',text): data['time']=None
        valid_dates=[d for d in data['dates'] if datetime.now(JST).date()<=datetime.fromisoformat(d).date()<=booking_limit(datetime.now(JST)).date()]
        data['dates']=valid_dates
        compatible=valid_wait_dates(data) if data.get('store') in (*STORE_NAMES,'both') else []
        if not compatible:
            await db.set_session(uid,'support','collect',json.dumps(data))
            await service.reply_text(token,'🔔 キャンセル待ちの希望日時・店舗を教えてください😊\n例：「来週の土曜、半蔵門、午前中」\n開始時刻は00分か30分、予約可能な期間・営業時間内で指定してください。時間指定がなければ、その日の空きを探します。');return True
    if data['kind']=='waitlist': data['dates']=compatible
    data['id']=uuid.uuid4().hex
    await db.set_session(uid,'support','confirm',json.dumps(data))
    action=await db.make_action(uid,{'a':'support_confirm','support_id':data['id']})
    if data['kind']=='consult': body='💬 '+data['message']+'\n\nスタッフへこの内容を送りますか？'
    else:
        from availability_search import filter_label
        body=wait_description(data)+'\n\n空きが見つかればLINEでお知らせします。枠の確保ではありません。'
    await service.reply_flex(token,'💬 内容をご確認ください',service._build_confirm_flex('🔔 キャンセル待ち' if data['kind']=='waitlist' else '💬 スタッフ相談',body,'✅ この内容で申し込む',action,'#167D8D'))
    return True


async def confirm_support(service,token,uid,user,data):
    if data['kind']=='consult':
        await db.enqueue('consult:'+data['id'],settings.ADMIN_USER_ID,'💬 スタッフ相談\n'+user.get('display_name','')+'\nLINE ID: '+uid+'\n\n'+data['message'])
    else:
        valid=valid_wait_dates(data)
        if not valid:
            await service.reply_text(token,'⏳ ご希望日時の受付期限を過ぎています。\n新しい希望日時を教えてください。');return
        data['dates']=valid
        payload={key:data[key] for key in ('dates','store','time','filters')}
        payload['source']='chat'
        await db.request_waitlist(data['id'],uid,payload,'🔔 キャンセル待ち受付\n'+user.get('display_name','')+'\n'+wait_description(data))
    await restore(uid,data.get('paused'))
    await service.reply_text(token,'✅ '+('ご相談を受け付けました。スタッフへ通知します。' if data['kind']=='consult' else 'キャンセル待ちを受け付けました。空きが見つかったらお知らせします。')+'\n\n😊 予約の途中だった場合は、そのまま続けられます。')
