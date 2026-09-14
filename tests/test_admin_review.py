import json
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
from config import settings
from calendar_service import Booking, BookingData, CalendarUnavailable
from booking_view import user_bookings
from notifications import flush_notifications
from tests.test_flows import event, user, future, customer
from tests.storage_helpers import patch_rows
from database import actions, outbox


def admin_event(text='',data=None):
    e=event(text,data);e.source.user_id=settings.ADMIN_USER_ID
    return e


async def request(database):
    ident=await database.save_booking('u','ebisu',future().isoformat(),metadata={'customer_name':'架空太郎','room':None})
    row=await database.get_booking(ident,'u')
    notice=next(n for n in await database.notification_backlog() if n['recipient']==settings.ADMIN_USER_ID)
    card=json.loads(notice['body'])
    tokens=[json.loads(b['action']['data']) for b in card['footer']['contents']]
    return row,tokens,card


def calendar(service):
    slot=future()
    entry=Booking('cal',slot,slot+timedelta(hours=1),'ebisu','架空太郎（恵）',source='work')
    service._get_bookings=AsyncMock(return_value=BookingData([],[],[entry]))
    return entry


async def test_admin_card_approve_and_customer_receipt_once(service,database):
    row,tokens,card=await request(database)
    assert 'None' not in json.dumps(card,ensure_ascii=False)
    assert all(len(json.dumps(t).encode())<=300 for t in tokens)
    assert all([await database.get_action(t['id'],settings.ADMIN_USER_ID) for t in tokens])
    calendar(service)
    await service.handle_postback_event(admin_event(data=tokens[0]),user())
    saved=await database.get_booking(row['public_id'],'u')
    assert saved['status']=='confirmed' and saved['metadata']['calendar_id']=='cal'
    service._get_bookings.assert_awaited_with(force=True)
    await service.handle_postback_event(admin_event(data=tokens[0]),user())
    receipts=[n for n in await database.notification_backlog() if n['recipient']=='u']
    assert len(receipts)==1 and receipts[0]['kind']=='card'
    assert '✅ ご予約が確定しました' in receipts[0]['body']
    api=AsyncMock();await flush_notifications(api)
    sent=[c.args[0] for c in api.push_message.call_args_list if c.args[0].to=='u']
    assert len(sent)==1 and sent[0].messages[0].type=='flex'
    assert await database.notification_backlog()==[]


async def test_missing_calendar_keeps_request_then_same_button_works(service,database):
    row,tokens,_=await request(database)
    await service.handle_postback_event(admin_event(data=tokens[0]),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='provisional'
    assert not any(n['recipient']=='u' for n in await database.notification_backlog())
    calendar(service)
    await service.handle_postback_event(admin_event(data=tokens[0]),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='confirmed'


async def test_rejection_requires_second_confirmation(service,database):
    row,tokens,_=await request(database)
    await service.handle_postback_event(admin_event(data=tokens[1]),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='provisional'
    card=service.reply_flex.call_args.args[2]
    token=json.loads(card['footer']['contents'][0]['action']['data'])
    await service.handle_postback_event(admin_event(data=token),user())
    await service.handle_postback_event(admin_event(data=token),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='rejected'
    assert len([n for n in await database.notification_backlog() if n['recipient']=='u'])==1


async def test_customer_cannot_use_admin_token_or_forge_role(service,database):
    row,tokens,_=await request(database)
    calendar(service)
    await service.handle_postback_event(event(data=tokens[0]),user())
    forged=json.loads(await database.make_action('u',{'a':'admin_review','bid':row['public_id'],'decision':'approve'}))
    await service.handle_postback_event(event(data=forged),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='provisional'
    service._get_bookings.assert_not_awaited()


async def test_cancelled_and_expired_buttons_cannot_confirm(service,database):
    row,tokens,_=await request(database)
    await patch_rows(database,actions,{'expires_at':'2020-01-01T00:00:00+09:00'})
    await service.handle_postback_event(admin_event(data=tokens[0]),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='provisional'
    await service.handle_text_message(admin_event('承認待ち'),user())
    token=json.loads(service.reply_flex.call_args.args[2]['contents'][0]['footer']['contents'][0]['action']['data'])
    await database.cancel_booking(row['public_id'],'u')
    await service.handle_postback_event(admin_event(data=token),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='cancelled'
    assert not any(n['recipient']=='u' for n in await database.notification_backlog())


async def test_calendar_registration_does_not_confirm_until_review(service,database):
    row,tokens,_=await request(database)
    calendar(service)
    entries=await user_bookings(service,'u',user())
    assert len(entries)==1 and entries[0]['status']=='provisional'
    await service.handle_postback_event(admin_event(data=tokens[0]),user())
    entries=await user_bookings(service,'u',user())
    assert len(entries)==1 and entries[0]['status']=='confirmed'


async def test_duplicate_calendar_matches_block_approval(service,database):
    row,tokens,_=await request(database)
    a=calendar(service)
    b=Booking('other',a.start_dt,a.end_dt,a.store,a.title,source='work')
    service._get_bookings=AsyncMock(return_value=BookingData([],[],[a,b]))
    await service.handle_postback_event(admin_event(data=tokens[0]),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='provisional'


async def test_calendar_failure_does_not_approve(service,database):
    row,tokens,_=await request(database)
    service._get_bookings=AsyncMock(side_effect=CalendarUnavailable('offline'))
    with pytest.raises(CalendarUnavailable):
        await service.handle_postback_event(admin_event(data=tokens[0]),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='provisional'


async def test_admin_pending_pagination_and_no_customer_exposure(service,database):
    for i in range(11):
        await database.save_booking('u','ebisu',(future()+timedelta(days=i)).isoformat())
    await service.handle_text_message(admin_event('承認待ち'),user())
    cards=service.reply_flex.call_args.args[2]['contents']
    assert len(cards)==10
    token=json.loads(cards[-1]['footer']['contents'][0]['action']['data'])
    await service.handle_postback_event(admin_event(data=token),user())
    assert len(service.reply_flex.call_args.args[2]['contents'])==2
    service.reply_flex.reset_mock()
    await service.handle_text_message(event('承認待ち'),user())
    service.reply_flex.assert_not_awaited()


async def test_receipt_retry_uses_stable_key(service,database):
    row,tokens,_=await request(database);calendar(service)
    await service.handle_postback_event(admin_event(data=tokens[0]),user())
    await patch_rows(database,outbox,{'state':'sent'},'recipient',settings.ADMIN_USER_ID)
    api=AsyncMock();api.push_message.side_effect=RuntimeError('temporary')
    await flush_notifications(api)
    key=api.push_message.call_args.kwargs['x_line_retry_key']
    await patch_rows(database,outbox,{'lease_until':None})
    api.push_message.side_effect=None
    await flush_notifications(api)
    assert api.push_message.call_args.kwargs['x_line_retry_key']==key
    assert await database.notification_backlog()==[]

async def test_review_and_receipt_roll_back_together(service,database,monkeypatch):
    row,tokens,_=await request(database);calendar(service)
    monkeypatch.setattr(database,'_enqueue',AsyncMock(side_effect=RuntimeError('write failed')))
    with pytest.raises(RuntimeError):
        await service.handle_postback_event(admin_event(data=tokens[0]),user())
    assert (await database.get_booking(row['public_id'],'u'))['status']=='provisional'
    assert not any(n['recipient']=='u' for n in await database.notification_backlog())

async def test_change_rejected_keeps_original_and_sends_clear_receipt(service,database):
    old=await database.save_booking('u','ebisu',future().isoformat())
    original=await database.get_booking(old,'u')
    new=await database.save_booking('u','ebisu',(future()+timedelta(days=1)).isoformat(),metadata={'change_from':{'type':'db','id':original['public_id']}})
    row=await database.get_booking(new,'u')
    assert await database.review_booking(row['public_id'],'rejected')
    assert (await database.get_booking(old,'u'))['status']=='provisional'
    receipt=next(n for n in await database.notification_backlog() if n['recipient']=='u')
    assert '元の予約はそのまま' in receipt['body']
