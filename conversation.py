"""Local conversation routing. Resolve intent before interpreting dates.

Never execute cancellation from free text: resolve an owned reservation, then
use the existing expiring confirmation action. No external language model.
"""
import json
import re
import unicodedata
from database import db
from config import STORE_NAMES
from booking_view import user_bookings
from booking_actions import resolve_booking, cancellation_confirmation, cancel_band

CANCEL = r'キャンセル|取り消|取消'
NEGATIVE = r'取り消さない|取り消さなく|取り消しません|(?:キャンセル|取り消し?|取消)(?:は)?(?:しない|しなく|しません|せず|不要)|残し|そのまま'
CHANGE = r'変更|ずらし|ずらす'


def normalize(text):
    return unicodedata.normalize('NFKC', text).strip()


def mentioned_dates(text):
    """Partial dates identify existing bookings; never roll them into next year."""
    pattern = r'(?:(\d{4})[/年-])?(\d{1,2})[/月-](\d{1,2})日?|(?<!\d)(\d{1,2})日'
    return [(int(m[1]) if m[1] else None, int(m[2]) if m[2] else None,
             int(m[3] or m[4])) for m in re.finditer(pattern, text)]


def matches_date(booking, dates):
    dt = booking['dt']
    return any((y is None or dt.year == y) and (m is None or dt.month == m) and dt.day == d
               for y, m, d in dates)


def label(booking):
    return booking['dt'].strftime('%m/%d %H:%M') + ' ' + STORE_NAMES[booking['store']]


async def remember(uid, ident, data):
    row = await db.get_booking(ident, uid)
    ident = row['public_id'] if row else ident
    await db.set_session(uid, 'conversation', 'submitted', json.dumps({
        'last_request': str(ident), 'change_from': data.get('change_from')}))


async def begin_change(service, token, uid, user, booking, desired=None):
    if cancel_band(booking['dt']) != 'normal':
        await service.reply_text(token, '開始12時間以内の予約変更は担当者へご相談ください。元の予約は残っています。')
        return
    data = {'mode': 'change', 'target_booking_id': booking['id'],
            'target_booking_type': booking['type'], 'store': booking['store'],
            'room_pref': user.get('room_pref'),
            'original_booking_info': {'dt': booking['dt'].isoformat(), 'store': booking['store']}}
    if desired:
        for word, store in [('恵比寿','ebisu'),('半蔵門','hanzoomon')]:
            if word in desired: data['store']=store
    await db.set_session(uid, 'booking', 'select_date', json.dumps(data))
    if desired and service._parse_multiple_dates(desired):
        await service._process_select_date(token,uid,{},desired,data)
        return
    await service.reply_text(token, label(booking) + ' の変更ですね。\n変更後の日時を教えてください。店舗は同じで進めます。別の店舗も指定できます。\n元の予約は変更が承認されるまで残ります。')


async def choose(service, token, uid, bookings, intent, note='', desired=None):
    if not bookings:
        await service.reply_text(token, '該当する予約が見つかりませんでした。予約日を月日で教えてください。')
        return
    bubbles = []
    for booking in bookings[:10]:
        action = await db.make_action(uid, {'a': 'conversation_select', 'intent': intent,
                                            't': booking['type'], 'bid': booking['id'], 'desired':desired})
        bubbles.append({'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical',
                        'contents': [{'type':'text','text':'取り消す予約を選択' if intent=='cancel' else '変更する予約を選択','size':'sm'}, {'type': 'text', 'text': label(booking), 'wrap': True}]},
                        'footer': {'type': 'box', 'layout': 'vertical', 'contents': [
                            {'type': 'button', 'action': {'type': 'postback', 'label': 'この予約を選ぶ', 'data': action}}]}})
    await db.set_session(uid, 'conversation', 'select_target', json.dumps({'intent': intent,'desired':desired}))
    await service.reply_flex(token, (note or '対象の予約を選んでください。') + (' 最初の10件です。日付でも絞り込めます。' if len(bookings)>10 else ''),
                             {'type': 'carousel', 'contents': bubbles})


async def route(service, event, user, session):
    text = normalize(event.message.text)
    uid, token = event.source.user_id, event.reply_token
    data = json.loads(session.get('flow_data', '{}')) if session else {}
    if session and session.get('flow_state')=='cancel_confirmation':
        if text in ('はい','はい、お願いします','はいお願いします','お願いします','取り消す','取消を申請する'):
            from types import SimpleNamespace
            from booking_actions import handle_action
            confirmation = SimpleNamespace(source=event.source,reply_token=token,
                postback=SimpleNamespace(data=json.dumps({'a':'action','id':data.get('cancel_action')})))
            await handle_action(service,confirmation,user)
            return True
        if text in ('戻る','⬅️ 戻る','いいえ','いいえ、やめます'):
            await db.clear_session(uid)
            await service.reply_text(token,'取り消しは実行していません。予約はそのまま残っています。')
            return True
    active = bool(session and session.get('flow_type') == 'booking')
    changing = active and data.get('mode') == 'change'
    if 'キャンセル待ち' in text:
        await service.reply_text(token,'キャンセル待ちのご相談ですね。希望日時と店舗を添えて担当者へご相談ください。現在の予約は取り消していません。')
        return True
    if active and text in ('時間を変更する','時間変更','時間を変える'):
        if session.get('flow_state')=='resolve_room_conflict':
            return False
        if data.get('date'):
            for key in ('time','pending_time','room'):
                data.pop(key,None)
            await service._process_select_date(token,uid,session,data['date'],data)
            return True
    cancel = bool(re.search(CANCEL, text))
    abort_change = bool(re.search(r'(?:日程|予約)?変更.*(?:取り消|取消|キャンセル|やめ|中止)', text)) and not re.search(NEGATIVE,text)
    abort = text in ('やめる', '操作をやめる', '中止', 'やめます', 'キャンセル')

    if abort_change or (abort and active):
        if active:
            await db.clear_session(uid)
            await service.reply_text(token, '変更の入力を中止しました。元の予約はそのまま残っています。' if changing else '予約の入力を中止しました。受付済みの予約は取り消していません。')
            return True
        if abort_change and data.get('last_request') and data.get('change_from'):
            booking = await resolve_booking(service, uid, user, 'db', data['last_request'])
            row = await db.get_booking(data['last_request'], uid)
            if booking and row['status'] == 'provisional':
                await cancellation_confirmation(service, token, uid, booking,
                    '変更リクエストだけを取り消します。元の予約は残ります。')
                return True
            await service.reply_text(token, '変更リクエストは承認済み、または受付状態が変わっています。最新の予約一覧から対象を確認してください。')
            return True
        if abort_change:
            await service.reply_text(token, 'どの変更リクエストを取り消すか確認が必要です。予約確認から対象の日時を教えてください。元の予約は取り消していません。')
            return True
    if abort and not cancel:
        await db.clear_session(uid)
        await service.reply_text(token, '操作を終了しました。受付済みの予約はそのままです。')
        return True

    # Respect explicit negation clause by clause. Dates in "残す" clauses are
    # excluded even if another clause asks for cancellation.
    clauses = re.split(r'[。！!？?\n、,]+', text)
    positive = [c for c in clauses if re.search(CANCEL, c) and not re.search(NEGATIVE, c)]
    protected = [d for c in clauses if re.search(NEGATIVE, c) for d in mentioned_dates(c)]
    if cancel and not positive:
        if session and session.get('flow_state')=='cancel_confirmation':
            await db.clear_session(uid)
        await service.reply_text(token, '予約は取り消していません。変更したい内容があれば教えてください。')
        return True
    if re.search(r'変更(?:は)?(?:しない|しません|せず|不要)', text):
        await db.clear_session(uid)
        await service.reply_text(token, '変更の入力を終了しました。受付済みの予約はそのままです。')
        return True
    intent = 'cancel' if positive else 'change' if re.search(CHANGE, text) else None
    if (not intent and not active
            and re.search(r'やっぱり|やはり|訂正|じゃなく', text)):
        bookings = await user_bookings(service, uid, user)
        if data.get('last_request'):
            bookings = [b for b in bookings if b['type']=='db' and b['id']==data['last_request']]
        await choose(service, token, uid, bookings, 'change', '変更元の予約を選んでください。', desired=text[:1000])
        return True
    if text == '予約 店舗変更' or '店舗変更' in text:
        return False
    if not intent and session and session.get('flow_state') == 'select_target':
        if mentioned_dates(text):
            intent = data.get('intent')

    if intent:
        # Clarification after a change submission must not create another request.
        if intent == 'change' and data.get('last_request') and data.get('change_from') and not mentioned_dates(text):
            await service.reply_text(token, '直前の受付は日程変更として受け付けています。元の予約はスタッフの承認まで残ります。変更後の日程を直す場合は、その日時を教えてください。')
            return True
        if intent == 'change' and changing:
            if service._parse_multiple_dates(text):
                for key in ('time', 'room', 'pending_time', 'suggested_dates'):
                    data.pop(key, None)
                await service._process_select_date(token, uid, session, text, data)
            else:
                await service.reply_text(token, '日程変更として進めています。変更後の日時を教えてください。元の予約は残ります。')
            return True
        bookings = await user_bookings(service, uid, user)
        dates = [d for c in positive for d in mentioned_dates(c)] if positive else mentioned_dates(text)
        quoted = bool(getattr(event.message, 'quoted_message_id', None))
        if protected:
            bookings = [b for b in bookings if not matches_date(b, protected)]
        if dates:
            bookings = [b for b in bookings if matches_date(b, dates)]
        elif intent == 'change' and data.get('last_request') and not quoted:
            bookings = [b for b in bookings if b['type']=='db' and b['id']==data['last_request']]
        elif intent == 'cancel' and changing and not quoted:
            bookings = [b for b in bookings if b['type']==data['target_booking_type'] and b['id']==data['target_booking_id']]
        time = service._extract_time(text)
        if dates and time:
            bookings = [b for b in bookings if (b['dt'].hour, b['dt'].minute)==time]
        if len(bookings)==1 and (dates or (intent=='change' and data.get('last_request'))):
            if intent == 'cancel':
                await cancellation_confirmation(service, token, uid, bookings[0],
                    '残すと指定した予約は取り消しません。' if protected else '')
            else:
                await begin_change(service, token, uid, user, bookings[0],desired=data.get('desired'))
        else:
            await choose(service, token, uid, bookings, intent,
                         '引用だけでは対象を特定できないため、予約を選んでください。' if quoted else '', desired=data.get('desired'))
        return True

    if text in ('戻る', '⬅️ 戻る') and active and session['flow_state']=='select_store' and changing:
        await service._show_booking_change_list(token, uid, user)
        await db.clear_session(uid)
        return True

    if active and text in ('店舗はそのまま','同じ店舗','そのままの店舗') and data.get('store') in STORE_NAMES:
        await service.reply_text(token, STORE_NAMES[data['store']]+'で進めます。希望日時を教えてください。')
        return True

    # Corrections may arrive at any input step, including final confirmation.
    if active and re.search(r'やっぱり|やはり|ではなく|じゃなく|訂正', text):
        text = re.split(r'ではなく|じゃなく',text)[-1]
        dates = service._parse_multiple_dates(text)
        if dates:
            for key in ('time', 'room', 'pending_time', 'suggested_dates'):
                data.pop(key, None)
            for word, store in [('恵比寿','ebisu'), ('半蔵門','hanzoomon')]:
                if word in text: data['store'] = store
            if not data.get('store'):
                await service.reply_text(token, '日時の変更ですね。店舗も教えてください。')
                return True
            await service._process_select_date(token, uid, session, text, data)
            return True
        if service._extract_time(text) and data.get('date') and data.get('store') not in (None,'both'):
            session = dict(session, flow_state='select_time')
            await service._handle_booking_flow(token, uid, user, session, text)
            return True
    if (not active and not intent and '予約' in text
            and not any(word in text for word in ('予約確認','予約一覧','マイ予約'))
            and not service._parse_hayamihyo_bulk(text)):
        dates = service._parse_multiple_dates(text)
        if dates:
            store = 'both' if '両店舗' in text or 'どちらでも' in text else None
            if store is None:
                for word, code in [('恵比寿','ebisu'),('半蔵門','hanzoomon')]:
                    if word in text: store=code
            store = store or user.get('store_pref')
            if store not in ('ebisu','hanzoomon','both'): store='both'
            draft = {'store':store, 'room_pref':user.get('room_pref')}
            await db.set_session(uid,'booking','select_date',json.dumps(draft))
            await service._process_select_date(token,uid,{},text,draft)
            return True
    return False
