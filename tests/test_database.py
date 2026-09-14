import asyncio,json
from datetime import datetime,timedelta
import pytest
from sqlalchemy import select,update
from database import current_event,bookings,outbox,sessions
from booking_rules import JST

async def test_event_idempotent_save_and_outbox(database):
    token=current_event.set('same-event')
    try:
        a=await database.save_booking('u','ebisu','2026-10-01T10:00:00+09:00')
        b=await database.save_booking('u','ebisu','2026-10-01T10:00:00+09:00')
    finally: current_event.reset(token)
    assert a==b
    assert len(await database.pending_notifications())==1

async def test_cancellation_is_owned_and_once(database):
    ident=await database.save_booking('u','ebisu','2026-10-01T10:00:00+09:00')
    assert not await database.cancel_booking(ident,'other')
    assert await database.cancel_booking(ident,'u')
    assert not await database.cancel_booking(ident,'u')

async def test_failed_notification_remains(database):
    await database.enqueue('key','u','test')
    row=(await database.pending_notifications())[0]
    await database.notification_result(row['id'],RuntimeError())
    async with database.engine.connect() as c:
        saved=(await c.execute(select(outbox))).mappings().one()
    assert saved['state']=='pending' and saved['last_error']=='RuntimeError'

async def test_session_expiry(database):
    await database.set_session('u','booking','confirm','{}')
    async with database.engine.begin() as c:
        await c.execute(update(sessions).values(updated_at=(datetime.now(JST)-timedelta(hours=1)).isoformat()))
    assert await database.get_session('u') is None

async def test_action_belongs_to_user(database):
    action=json.loads(await database.make_action('u',{'a':'cancel'}))
    assert await database.get_action(action['id'],'u')=={'a':'cancel'}
    assert await database.get_action(action['id'],'other') is None

async def test_claim_excludes_parallel_requests(database):
    results=await asyncio.gather(database.claim('same'),database.claim('same'))
    assert sum(bool(r) for r in results)==1
    owner=next(r for r in results if r)
    await database.release('same',owner,done=True)
    assert await database.is_done('same')
    assert await database.claim('same') is None

async def test_waitlist_answer_saved_once(database):
    await database.save_waitlist_offer('id','u',{'date':'x'},{'type':'bubble'})
    assert await database.respond_waitlist('id','u','accepted','notice')
    assert not await database.respond_waitlist('id','u','declined','notice')
    assert (await database.get_waitlist('id','u'))['state']=='accepted'

async def test_review_supersedes_only_after_approval(database):
    old=await database.save_booking('u','ebisu','2026-10-01T10:00:00+09:00')
    row=await database.get_booking(old,'u')
    new=await database.save_booking('u','ebisu','2026-10-02T10:00:00+09:00',metadata={'change_from':{'id':row['public_id'],'type':'db'}})
    assert (await database.get_booking(old,'u'))['status']=='provisional'
    replacement=await database.get_booking(new,'u')
    assert await database.review_booking(replacement['public_id'],'confirmed','calendar-id')
    assert (await database.get_booking(old,'u'))['status']=='superseded'
    assert not await database.review_booking(replacement['public_id'],'confirmed','calendar-id')
