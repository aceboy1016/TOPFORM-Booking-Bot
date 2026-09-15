"""Server-owned, expiring actions for changes, cancellation and waitlist replies."""
import json
from datetime import datetime, timedelta
from linebot.v3.messaging import QuickReply, QuickReplyItem, MessageAction
from config import settings, STORE_NAMES
from booking_rules import JST, as_jst, parse_slot
from calendar_service import find_user_bookings, check_availability
from sheets_service import sheets_service
from async_services import google_call
from database import db

async def resolve_booking(service,user_id,user,kind,ident):
    if kind=='db':
        row=await db.get_booking(str(ident),user_id)
        if not row or row['status'] not in ('provisional','confirmed'): return None
        return {'id':row['public_id'],'type':'db','dt':as_jst(datetime.fromisoformat(row['slot_datetime'])),'store':row['store']}
    if kind=='cal':
        if await db.is_done('calendar-cancel:'+user_id+':'+ident): return None
        snapshot=await service._get_bookings(force=True)
        matches=find_user_bookings(user.get('display_name',''),snapshot,user_id,allow_legacy=not user.get('ambiguous_name',False))
        found=[b for b in matches if b.id==ident]
        if len(found)==1:
            b=found[0];return {'id':b.id,'type':'cal','dt':b.start_dt,'store':b.store}
    return None

def cancel_band(slot):
    hours=(slot-datetime.now(JST)).total_seconds()/3600
    return 'urgent' if hours<=settings.URGENT_CONTACT_DEADLINE_HOURS else 'consume' if hours<=settings.BOOKING_DEADLINE_HOURS else 'normal'

async def cancellation_confirmation(service,token,uid,booking,context=""):
    band=cancel_band(booking['dt'])
    note={'normal':'この予約の取消を申請しますか？','consume':'開始12時間以内のため1回分消化扱いになります。取消を申請しますか？','urgent':'開始3時間以内のため1回分消化扱いになります。担当者へ直前取消を申請しますか？'}[band]
    data=await db.make_action(uid,{'a':'cancel_confirm','t':booking['type'],'bid':booking['id'],'band':band})
    await db.set_session(uid,'conversation','cancel_confirmation',json.dumps({'cancel_action':json.loads(data)['id']}))
    await service.reply_flex(token,'📝 ご予約の取消確認',service._build_confirm_flex('📝 ご予約の取消確認',(context+'\n\n' if context else '')+'📅 '+booking['dt'].strftime('%m/%d')+'（'+'月火水木金土日'[booking['dt'].weekday()]+'）\n🕐 '+booking['dt'].strftime('%H:%M')+'〜\n📍 '+STORE_NAMES[booking['store']]+'\n\n'+note,'取消を申請する',data,'#B45309'))

async def handle_action(service,event,user):
    uid,token=event.source.user_id,event.reply_token
    customer=await google_call(sheets_service.get_customer_by_line_id,uid)
    if not customer and uid!=settings.ADMIN_USER_ID:
        await service.reply_text(token,'🌱 ご利用には登録が必要です。担当者へお声がけくださいね。');return
    if customer: user.update(display_name=customer['name'],room_pref=customer.get('room_pref'),store_pref=customer.get('store_pref'),ambiguous_name=customer.get('ambiguous_name',False))
    try: raw=json.loads(event.postback.data)
    except (ValueError,TypeError): raw={}
    if not isinstance(raw,dict): raw={}
    # Only harmless pagination and admin-specific legacy actions are accepted raw.
    if raw.get('a')=='activate_user' and uid==settings.ADMIN_USER_ID:
        target=raw.get('uid','')
        if not await google_call(sheets_service.get_customer_by_line_id,target):
            await service.reply_text(token,'顧客マスタの登録を確認してから通知してください。');return
        await db.enqueue('activation:'+target,target,'予約Botの登録が完了しました。メニューからご利用ください。')
        await service.reply_text(token,'登録完了通知を受け付けました。');return
    if raw.get('a')=='change_list_more':
        offset=raw.get('off',0)
        if isinstance(offset,int) and 0<=offset<=1000: await service._show_booking_change_list(token,uid,user,offset)
        return
    data=await db.get_action(raw.get('id',''),uid) if raw.get('a')=='action' else None
    if not data:
        command='承認待ち' if uid==settings.ADMIN_USER_ID else '予約確認'
        await service.reply_text(token,f'⏳ このボタンは期限切れです。\n\n「{command}」から最新の予約を表示してくださいね😊');return
    action=data.get('a')
    if action in ('admin_review','admin_pending'):
        from admin_review import handle
        await handle(service,token,uid,data)
        return
    if action == 'waitlist_withdraw':
        changed=await db.withdraw_waitlist(data['wid'],uid)
        await service.reply_text(token,'👌 キャンセル待ちを取り下げました。予約はそのまま残っています。' if changed else '💡 このキャンセル待ちは受付を終了しています。')
        return
    if action == 'support_confirm':
        session=await db.get_session(uid)
        context=json.loads(session['flow_data']) if session else {}
        if not session or session['flow_type']!='support' or session['flow_state']!='confirm' or context.get('id')!=data.get('support_id'):
            await service.reply_text(token,'💡 この申込み確認は終了しています。');return
        from conversation_extras import confirm_support
        await confirm_support(service,token,uid,user,context)
        return
    if action in ('pick_slot', 'picker_page', 'picker_confirm'):
        session = await db.get_session(uid)
        context = json.loads(session.get('flow_data', '{}')) if session else {}
        if action == 'picker_confirm':
            valid = session and session.get('flow_type') == 'booking' and session.get('flow_state') == 'confirm' and context.get('confirmation_id') == data.get('confirmation_id')
            if not valid:
                await service.reply_text(token, '🌿 この申込み確認は終了しています。時間を選び直すと、新しい確認を表示できます😊')
                return
            await service._handle_booking_flow(token, uid, user, session, '確定する')
        elif action == 'picker_page':
            source = data.get('picker') or (context if context.get('picker_id') == data.get('picker_id') else None)
            if not source:
                await service.reply_text(token, '📅 この一覧は更新が必要です。ご希望の日を教えてください😊')
                return
            await service._show_available_cards(token, uid, source, data['date_offset'], data['slot_offset'], data.get('store'))
        else:
            # Time cards describe an option, not permission to submit. Reuse them
            # in the current draft and require a fresh final confirmation.
            paused = context.get('paused_booking')
            if paused:
                session = paused
                context = json.loads(paused['flow_data'])
            if session and session.get('flow_state') == 'select_target' and context.get('intent') in ('change', 'cancel'):
                await service.reply_text(token, '🔄 先に変更・取消の対象予約を選んでください😊\nそのあと、前の時間カードも選べます。')
                return
            if not session or session.get('flow_type') != 'booking':
                context = {'room_pref': user.get('room_pref')}
            for key in ('time', 'pending_time', 'room', 'confirmation_id', 'pending_datetime_text'):
                context.pop(key, None)
            context.update(date=data['date'], store=data['store'])
            snapshot = await service._get_bookings(force=True)
            if not check_availability(parse_slot(data['date'],data['time']),data['store'],snapshot)['is_available']:
                await service._process_select_date(token, uid, session or {}, data['date'], context)
                return
            await db.set_session(uid, 'booking', 'select_time', json.dumps(context))
            await service._handle_booking_flow(token, uid, user, await db.get_session(uid), data['time'])
        return
    if action in ('waitlist_accept','waitlist_decline'):
        row=await db.get_waitlist(data['wid'],uid)
        if not row or row['state']!='offered':
            await service.reply_text(token,'💡 この提案は回答済み、または受付を終了しています。');return
        payload=json.loads(row['payload'])
        if action=='waitlist_accept':
            snapshot=await service._get_bookings(force=True)
            if not check_availability(parse_slot(payload['date'],payload['time']),payload['store'],snapshot)['is_available']:
                await service.reply_text(token,'🌿 申し訳ありません。現在はこの枠をお取りできません。\n別の日時をご検討ください。');return
        state='accepted' if action=='waitlist_accept' else 'declined'
        notice=f"キャンセル待ち {'承諾' if state=='accepted' else '辞退'}\n{user['display_name']}\n{payload['date']} {payload['time']} {STORE_NAMES[payload['store']]}\nスタッフ確認をお願いします。"
        changed=await db.respond_waitlist(data['wid'],uid,state,notice)
        await service.reply_text(token,('📋 仮予約の希望を受け付けました！\n\nスタッフが確認後ご連絡します😊' if state=='accepted' else '👌 今回は見送りとして受け付けました。\nまたご都合のよい機会にご利用ください😊') if changed else '💡 回答済みです。ありがとうございます。')
        return
    booking=await resolve_booking(service,uid,user,data.get('t'),data.get('bid'))
    if not booking or booking['dt']<=datetime.now(JST):
        await service.reply_text(token,'🔎 この予約は変更済み・取消済み、または開始時刻を過ぎています。\n\n「予約確認」から最新の予約一覧をご確認ください。');return
    if action=='cancel_request':
        await cancellation_confirmation(service,token,uid,booking);return
    if action=='cancel_confirm':
        session=await db.get_session(uid)
        context=json.loads(session.get('flow_data','{}')) if session else {}
        if context.get('cancel_action')!=raw.get('id'):
            await service.reply_text(token,'💡 この確認は終了しています。\n\n取り消したい予約をもう一度選んでくださいね。')
            return
        if data.get('band')!=cancel_band(booking['dt']):
            await cancellation_confirmation(service,token,uid,booking);return
        band=cancel_band(booking['dt'])
        notice=f"予約取消申請 ({band})\n{user['display_name']}\n{booking['dt'].isoformat()} {booking['store']}\n"+('1回消化扱い。' if band!='normal' else '')+'カレンダーの取消確認をお願いします。'
        if booking['type']=='db': changed=await db.cancel_booking(booking['id'],uid,notice)
        else:
            key='calendar-cancel:'+uid+':'+booking['id'];owner=await db.claim(key)
            changed=bool(owner)
            if owner:
                try:
                    await db.enqueue(key,settings.ADMIN_USER_ID,notice)
                    await db.release(key,owner,done=True)
                except Exception:
                    await db.release(key,owner);raise
        await service.reply_text(token,'📝 取消申請を受け付けました。\n\nスタッフがカレンダーへの反映を確認します。\nご連絡ありがとうございます🌿' if changed else '📝 この取消申請は受付済みです。\nご連絡ありがとうございます。')
        await db.clear_session(uid)
        service._invalidate_cache();return
    if action=='conversation_select':
        from conversation import begin_change
        if data.get('intent')=='cancel':
            await cancellation_confirmation(service,token,uid,booking)
        elif data.get('intent')=='change':
            await begin_change(service,token,uid,user,booking,desired=data.get('desired'))
        return
    if action=='scb':
        from conversation import begin_change
        await begin_change(service,token,uid,user,booking)
