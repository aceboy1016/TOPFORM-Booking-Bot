"""Administrator-only LINE approval using existing Calendar registration."""
from datetime import datetime
from database import db
from config import settings
from booking_rules import JST, as_jst
from booking_cards import admin_card, card, details, button
from calendar_service import find_user_bookings
from sheets_service import sheets_service
from async_services import google_call


async def show_pending(service,token,uid,offset=0):
    if uid!=settings.ADMIN_USER_ID: return
    rows=await db.pending_bookings()
    if not rows:
        await service.reply_text(token,'✅ 承認待ちの予約はありません。');return
    if offset>=len(rows): offset=0
    cards=[]
    for row in rows[offset:offset+9]:
        tokens=[await db.make_action(uid,{'a':'admin_review','bid':row['public_id'],'decision':decision},ttl=7*24*60) for decision in ('approve','reject')]
        cards.append(admin_card(row,*tokens))
    if offset+9<len(rows):
        action=await db.make_action(uid,{'a':'admin_pending','offset':offset+9})
        cards.append(card('📥 続きの予約','#167D8D',[{'type':'text','text':f'承認待ち：全{len(rows)}件','wrap':True}],[button('次の予約を見る ➡️',action)]))
    await service.reply_flex(token,f'📥 承認待ちの予約：{len(rows)}件',{'type':'carousel','contents':cards})


async def handle(service,token,uid,data):
    if uid!=settings.ADMIN_USER_ID:
        await service.reply_text(token,'この操作は管理者専用です。');return
    if data['a']=='admin_pending':
        await show_pending(service,token,uid,data.get('offset',0));return
    row=next((r for r in await db.pending_bookings() if r['public_id']==data.get('bid')),None)
    if not row:
        await service.reply_text(token,'💡 この予約は処理済み、または取り消されています。\n「承認待ち」で現在の予約を確認できます。');return
    decision=data.get('decision')
    if decision=='reject':
        action=await db.make_action(uid,{'a':'admin_review','bid':row['public_id'],'decision':'reject_confirm'})
        back=await db.make_action(uid,{'a':'admin_pending','offset':0})
        await service.reply_flex(token,'予約を見送る前に確認',card('予約を見送りますか？','#64748B',details(row)+[{'type':'text','text':'お客様へ「ご希望の予約をお取りできませんでした」と通知します。カレンダーは変更しません。','wrap':True,'size':'sm'}],[button('見送ってお客様に通知',action),button('戻る・まだ判断しない',back)]));return
    calendar_id=''
    if decision=='approve':
        if as_jst(datetime.fromisoformat(row['slot_datetime']))<=datetime.now(JST):
            await service.reply_text(token,'⏳ 開始時刻を過ぎた予約です。内容を確認して個別にご対応ください。');return
        customer=await google_call(sheets_service.get_customer_by_line_id,row['line_user_id'])
        if not customer:
            await service.reply_text(token,'顧客マスタの登録が確認できません。登録を確認してからもう一度押してください。');return
        snapshot=await service._get_bookings(force=True)
        entries=find_user_bookings(customer['name'],snapshot,row['line_user_id'],allow_legacy=not customer.get('ambiguous_name',False))
        matches=[b for b in entries if as_jst(b.start_dt)==as_jst(datetime.fromisoformat(row['slot_datetime'])) and b.store==row['store']]
        if len(matches)!=1:
            await service.reply_text(token,'📅 カレンダーに一致する予約を1件に特定できませんでした。\n\nお客様・日時・店舗の登録をご確認のうえ、もう一度「確定する」を押してください。\nまだお客様へ確定通知は送っていません。');return
        calendar_id=matches[0].id
    elif decision!='reject_confirm': return
    changed=await db.review_booking(row['public_id'],'confirmed' if decision=='approve' else 'rejected',calendar_id)
    await service.reply_text(token,('✅ 予約を確定しました。' if decision=='approve' else '予約を見送りました。')+'\nお客様への結果カードの送信を受け付けました。\n\n「承認待ち」で残りの予約を確認できます。' if changed else '💡 この予約はすでに処理済みです。再通知はしていません。')
