"""Shared LINE booking review cards; no external image hosting required."""
import json
import uuid
from datetime import datetime, timedelta
from booking_rules import JST, as_jst
from config import settings, STORE_NAMES


def details(row):
    slot=as_jst(datetime.fromisoformat(row['slot_datetime']))
    return [
        {'type':'text','text':'📅 '+slot.strftime('%Y/%m/%d')+'（'+'月火水木金土日'[slot.weekday()]+'）','weight':'bold','size':'lg','wrap':True},
        {'type':'text','text':'🕐 '+slot.strftime('%H:%M')+'〜'+(slot+timedelta(hours=1)).strftime('%H:%M'),'weight':'bold','size':'lg'},
        {'type':'text','text':'📍 '+STORE_NAMES.get(row['store'],row['store']),'wrap':True},
    ]


def card(title, color, contents, buttons=None):
    result={'type':'bubble','header':{'type':'box','layout':'vertical','backgroundColor':color,'contents':[{'type':'text','text':title,'color':'#FFFFFF','weight':'bold','size':'lg','wrap':True}]},
            'body':{'type':'box','layout':'vertical','spacing':'md','contents':contents}}
    if buttons: result['footer']={'type':'box','layout':'vertical','spacing':'sm','contents':buttons}
    return result


def button(label,token,primary=False):
    result={'type':'button','height':'sm','style':'primary' if primary else 'secondary','action':{'type':'postback','label':label,'data':token}}
    if primary: result['color']='#15803D'
    return result


def admin_card(row,approve,reject):
    extra=row.get('metadata') or {}
    if isinstance(extra,str): extra=json.loads(extra)
    contents=[{'type':'text','text':'👤 '+str(extra.get('customer_name') or 'お客様'),'weight':'bold','wrap':True}]+details(row)
    contents.append({'type':'text','text':'🚪 個室希望：'+str(extra.get('room') or '指定なし'),'wrap':True,'size':'sm'})
    if extra.get('change_from'):
        contents.append({'type':'text','text':'🔄 予約変更のご希望です。承認まで元の予約は残ります。カレンダーの旧予定の変更・取消もお願いします。','wrap':True,'size':'sm'})
    contents.append({'type':'text','text':'カレンダー登録後、下のボタンで承認してください。お客様へ結果を通知します。','wrap':True,'size':'sm'})
    return card('📥 ご予約が届いています','#167D8D',contents,[button('✅ 確定する',approve,True),button('今回は見送る',reject)])


def admin_notification(row):
    """Return a card and token records to persist in the booking transaction."""
    records=[];tokens=[]
    for decision in ('approve','reject'):
        ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'admin-review:'+row['public_id']+':'+decision))
        records.append(dict(id=ident,line_user_id=settings.ADMIN_USER_ID,
                            payload=json.dumps({'a':'admin_review','bid':row['public_id'],'decision':decision}),
                            expires_at=(as_jst(datetime.fromisoformat(row['created_at']))+timedelta(days=7)).isoformat()))
        tokens.append(json.dumps({'a':'action','id':ident}))
    return admin_card(row,*tokens),records


def result_card(row,state):
    extra=row.get('metadata') or {}
    if isinstance(extra,str): extra=json.loads(extra)
    approved=state=='confirmed'
    title=('✅ ご予約の変更が確定しました' if extra.get('change_from') else '✅ ご予約が確定しました') if approved else 'ご予約についてのお知らせ'
    text='スタッフが承認しました😊\n当日お待ちしております！' if approved else 'ご希望の予約をお取りできませんでした。\n別の日時もお探しできます。'
    if not approved and extra.get('change_from'): text+='\n元の予約はそのまま残っています。'
    return card(title,'#15803D' if approved else '#64748B',details(row)+[{'type':'separator','margin':'md'},{'type':'text','text':text,'wrap':True}])
