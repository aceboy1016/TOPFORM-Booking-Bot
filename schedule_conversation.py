"""Resolve schedule-change source and destination separately, without an LLM."""
import json
import re
import uuid
from database import db

# Order matters: consume full dates before shorter days and relative expressions.
DATE = re.compile(r'(?<!\d)(?:\d{4}[/年-]\d{1,2}[/月-]\d{1,2}日?|\d{1,2}[/月]\d{1,2}日?)|(?:(?:再来週|来週|今週)の?)?\d{1,2}日|(?:再来週|来週|今週)?の?[月火水木金土日]曜日?|明後日|あさって|明日|今日')
DEFERRED = re.compile(r'未定|決まって(?:い)?ない|まだ決め|決まったら|(?<!明)後日|また連絡|改めて連絡|あとで|後で')
CHANGE = re.compile(r'変更|ずらし|ずらす|振替|振り替')


def date_mentions(text):
    mentions=[]
    for match in DATE.finditer(text):
        # A weekday label immediately following a numeric date annotates it.
        if mentions and re.fullmatch(r'の?[月火水木金土日]曜日?',match[0]) and re.search(r'\d',mentions[-1][0]) and re.fullmatch(r'[\s(（]*',text[mentions[-1].end():match.start()]):
            continue
        mentions.append(match)
    return mentions


def split_change(text):
    """Return original description and destination, never a combined date list."""
    dates=date_mentions(text)
    if len(dates)>=2:
        cut=dates[1].start()
        return text[:cut],text[cut:]
    if not dates: return text,None
    # With one date, time after the change request describes the destination.
    change=CHANGE.search(text)
    if change and change.start()>dates[0].end():
        return text[:change.start()],text[change.end():]
    return text,None


def original_matches(service, booking, source):
    from conversation import mentioned_dates, matches_date
    partial=mentioned_dates(source)
    if partial:
        if not matches_date(booking,partial): return False
    else:
        dates=service._parse_multiple_dates(source)
        if dates and booking['dt'].date() not in [d.date() for d in dates]: return False
    time=service._extract_time(source)
    return not time or (booking['dt'].hour,booking['dt'].minute)==time


async def deferred_options(service,token,uid,booking):
    from conversation import label
    ident=uuid.uuid4().hex
    await db.set_session(uid,'conversation','deferred_options',json.dumps({'deferred_id':ident}))
    actions=[]
    for name,title in [('deferred_keep','📅 元の予約を残す'),('deferred_cancel','📝 元の予約の取消へ')]:
        payload=await db.make_action(uid,{'a':name,'t':booking['type'],'bid':booking['id'],'deferred_id':ident})
        actions.append({'type':'button','style':'secondary','height':'sm','action':{'type':'postback','label':title,'data':payload}})
    card=service._build_confirm_flex('🔄 変更先は後で決められます',label(booking)+'\n\n新しい日程が未定でも大丈夫です😊\n元の予約はどうしますか？\n\n「取消へ」を選ぶと、取消条件と確認画面を表示します。今はまだ取り消していません。','元の予約を残す',actions[0]['action']['data'],'#167D8D')
    card['footer']['contents']=actions
    await service.reply_flex(token,'🔄 変更先は後で決められます。元の予約を残すか、取消確認へ進むか選んでください。',card)


async def route(service,event,user,session):
    from conversation import normalize, begin_change, choose
    from booking_view import user_bookings
    from booking_actions import resolve_booking
    text=normalize(event.message.text)
    uid,token=event.source.user_id,event.reply_token
    data=json.loads(session.get('flow_data','{}')) if session else {}
    changing=session and session.get('flow_type')=='booking' and data.get('mode')=='change'
    # An acknowledgement mentioning a date is not a new booking/change request.
    if re.search(r'(?:変更|予約).*(?:ありがとう|有難う)',text) and not re.search(r'キャンセル|取消|取り消|(?:変更|予約).*(?:できます|可能|お願いできます|したい|希望)',text):
        await service.reply_text(token,'😊 ありがとうございます！\nご予約の日時は「予約確認」でいつでも確認できます。')
        return True
    deferred=bool(DEFERRED.search(text))
    if deferred and changing:
        booking=await resolve_booking(service,uid,user,data.get('target_booking_type'),data.get('target_booking_id'))
        if booking:
            await deferred_options(service,token,uid,booking)
            return True
    # Leave negative/aborted changes and cancellation to the existing safe router.
    if not CHANGE.search(text) or re.search(r'取り消|取消|キャンセル|やめ|中止|しない|しません|せず|不要',text): return False
    source,desired=split_change(text)
    if session and session.get('flow_type')=='booking' and len(date_mentions(text))<2:
        if changing or not re.search(r'予約|予定|トレーニング|ですが|時間の変更',source):
            return False
    if not DATE.search(source):
        if deferred:
            await choose(service,token,uid,await user_bookings(service,uid,user),'change',desired='__deferred__')
            return True
        return False
    entries=await user_bookings(service,uid,user)
    entries=[b for b in entries if original_matches(service,b,source)]
    if desired and re.match(r'^の?[月火水木金土日]曜',desired) and re.search(r'今週|来週|再来週',source):
        dates=service._parse_multiple_dates(source)
        weekday=re.match(r'^の?([月火水木金土日])曜(?:日)?',desired)
        if len(dates)==1:
            from datetime import timedelta
            day=dates[0]+timedelta(days='月火水木金土日'.index(weekday[1])-dates[0].weekday())
            desired=day.strftime('%Y-%m-%d')+desired[weekday.end():]
    if deferred: desired='__deferred__'
    elif re.search(r'時間(?:の)?(?:変更|を変)',text) and len(entries)==1 and not service._extract_time(desired or ''):
        desired=entries[0]['dt'].strftime('%Y-%m-%d')
    elif desired:
        # Bare destination day inherits the explicitly stated source month/year.
        source_dates=service._parse_multiple_dates(source)
        if source_dates and re.match(r'^\d{1,2}日',desired):
            desired=source_dates[0].strftime('%Y/%m/')+desired
        # "8/9変更可能？16時恵比寿" is a same-day time/store change.
        if not service._parse_multiple_dates(desired) and service._extract_time(desired):
            if len(entries)==1: desired=entries[0]['dt'].strftime('%Y-%m-%d')+' '+desired
    if len(entries)==1:
        if desired=='__deferred__': await deferred_options(service,token,uid,entries[0])
        else: await begin_change(service,token,uid,user,entries[0],desired=desired)
    else:
        await choose(service,token,uid,entries,'change',desired=desired)
    return True
