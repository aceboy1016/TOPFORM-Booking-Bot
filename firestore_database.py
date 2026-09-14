"""Firestore persistence with atomic requests/outbox and no always-on DB cost.

Queries use one indexed field; sorting small per-user result sets happens locally.
No paid TTL, PITR or managed backup features are enabled by this adapter.
"""
import asyncio
import random
import copy
import hashlib
import inspect
import json
import uuid
from datetime import datetime, timedelta
from google.api_core.exceptions import Aborted
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from config import settings
from booking_rules import JST, as_jst
from database import current_event, now_iso, decode


class _Unit:
    """Buffer writes so Firestore always performs all reads before writes."""
    def __init__(self, transaction):
        self.transaction = transaction
        self.reads = {}
        self.writes = {}

    async def get(self, ref):
        if ref.path in self.writes:
            return copy.deepcopy(self.writes[ref.path][1])
        if ref.path not in self.reads:
            snapshot = await ref.get(transaction=self.transaction)
            self.reads[ref.path] = snapshot.to_dict() if snapshot.exists else None
        return copy.deepcopy(self.reads[ref.path])

    def put(self, ref, value):
        self.writes[ref.path] = (ref, copy.deepcopy(value))

    def delete(self, ref):
        self.writes[ref.path] = (ref, None)

    def flush(self):
        for ref, value in self.writes.values():
            if value is None:
                self.transaction.delete(ref)
            else:
                self.transaction.set(ref, value)


class FirestoreDatabase:
    TABLES = ('users', 'bookings', 'sessions', 'notification_outbox',
              'operation_claims', 'action_tokens', 'waitlist_requests')

    def __init__(self, project=None, prefix=None, client=None):
        self.project = project or settings.FIRESTORE_PROJECT
        self.prefix = prefix or settings.FIRESTORE_PREFIX
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = firestore.AsyncClient(project=self.project, database='(default)')
        return self._client

    def collection(self, table):
        if table not in self.TABLES and table != 'system':
            raise ValueError('Unknown collection')
        return self.client.collection(self.prefix + '_' + table)

    def ref(self, table, key):
        return self.collection(table).document(hashlib.sha256(str(key).encode()).hexdigest())

    async def _run(self, operation):
        @firestore.async_transactional
        async def apply(transaction):
            unit = _Unit(transaction)
            result = await operation(unit)
            unit.flush()
            return result
        # Retry only explicit aborts (nothing committed), with jitter so competing
        # workers do not repeatedly restart in lockstep. Other errors propagate.
        for attempt in range(5):
            try:
                return await apply(self.client.transaction(max_attempts=1))
            except (Aborted, ValueError) as exc:
                aborted = isinstance(exc, Aborted) or isinstance(exc.__cause__, Aborted)
                if not aborted or attempt == 4:
                    raise
                await asyncio.sleep(random.uniform(0.05, 0.2) * (2 ** attempt))

    async def _rows(self, table, field=None, value=None, limit=None):
        query = self.collection(table)
        if field is not None:
            query = query.where(filter=FieldFilter(field, '==', value))
        if limit is not None:
            query = query.limit(limit)
        return [snap.to_dict() async for snap in query.stream()]

    async def _get(self, table, key):
        snap = await self.ref(table, key).get()
        return snap.to_dict() if snap.exists else None

    async def init_db(self):
        await self.health()

    async def health(self):
        await self.ref('system', 'health').get()
        return True

    async def close(self):
        if self._client is not None:
            result = self._client._firestore_api.transport.close()
            if inspect.isawaitable(result):
                await result
            self._client = None

    async def get_or_create_user(self, line_user_id, display_name=None):
        async def operation(unit):
            ref = self.ref('users', line_user_id)
            row = await unit.get(ref)
            if row is None:
                row = dict(id=line_user_id, line_user_id=line_user_id,
                           display_name=display_name or 'ゲスト', preferred_store=None,
                           created_at=now_iso(), updated_at=now_iso())
                unit.put(ref, row)
            elif display_name is not None:
                row.update(display_name=display_name, updated_at=now_iso())
                unit.put(ref, row)
            return row
        return await self._run(operation)

    async def _enqueue(self, unit, key, recipient, body, kind='text'):
        if not recipient:
            raise ValueError('通知先が未設定です')
        ident = str(uuid.uuid5(uuid.NAMESPACE_URL, key))
        ref = self.ref('notification_outbox', ident)
        if await unit.get(ref) is None:
            unit.put(ref, dict(id=ident, recipient=recipient, body=body, kind=kind,
                              state='pending', attempts=0, created_at=now_iso(),
                              lease_until=None, last_error=None))
        return ident

    async def enqueue(self, key, recipient, body, kind='text'):
        return await self._run(lambda unit: self._enqueue(unit, key, recipient, body, kind))

    async def save_booking(self, line_user_id, store, slot_datetime, status='provisional', metadata=None):
        slot_datetime = as_jst(datetime.fromisoformat(slot_datetime)).isoformat()
        extra = metadata or {}
        fingerprint = json.dumps([line_user_id, store, slot_datetime, extra.get('change_from')], sort_keys=True)
        key = hashlib.sha256((current_event.get() or str(uuid.uuid4())).encode() + fingerprint.encode()).hexdigest()
        # SQL migrations retain their original random public IDs. A redelivered
        # event must find those rows before choosing a new deterministic ID.
        existing = await self._rows('bookings', 'request_key', key, limit=2)
        if len(existing) > 1:
            raise ValueError('Duplicate request identity')
        ident = existing[0]['public_id'] if existing else str(uuid.uuid5(uuid.NAMESPACE_URL, 'booking:' + key))
        async def operation(unit):
            ref = self.ref('bookings', ident)
            row = await unit.get(ref)
            if row is None:
                row = dict(id=ident, public_id=ident, request_key=key, line_user_id=line_user_id,
                           store=store, slot_datetime=slot_datetime, status=status,
                           metadata=json.dumps(extra, ensure_ascii=False), created_at=now_iso(),
                           confirmed_at=None, cancelled_at=None)
                unit.put(ref, row)
            summary = (f"予約リクエスト No.{row['id']}\nお名前: {extra.get('customer_name', line_user_id)}"
                       f"\n日時: {slot_datetime}\n店舗: {store}\n個室希望: {extra.get('room', '指定なし')}")
            if extra.get('change_from'):
                summary += f"\n変更前: {extra['change_from']}\n旧予約は本変更完了まで保持しています。"
            await self._enqueue(unit, 'booking:' + key, settings.ADMIN_USER_ID,
                                summary + '\nスタッフ確認後、カレンダー登録・承認をお願いします。')
            return row['id']
        return await self._run(operation)

    async def get_user_bookings(self, line_user_id, include_past=False):
        rows = await self._rows('bookings', 'line_user_id', line_user_id)
        return sorted([decode(r) for r in rows
                       if r['status'] not in ('cancelled', 'superseded', 'rejected')
                       and (include_past or r['slot_datetime'] >= now_iso())], key=lambda r: r['slot_datetime'])

    async def _booking_ref(self, booking_id):
        if isinstance(booking_id, int):
            rows = await self._rows('bookings', 'id', booking_id, limit=2)
            return self.ref('bookings', rows[0]['public_id']) if len(rows) == 1 else None
        return self.ref('bookings', booking_id)

    async def get_booking(self, booking_id, line_user_id):
        ref = await self._booking_ref(booking_id)
        if ref is None:
            return None
        snap = await ref.get()
        row = snap.to_dict() if snap.exists else None
        return decode(row) if row and row['line_user_id'] == line_user_id else None

    async def cancel_booking(self, booking_id, line_user_id, notice=''):
        ref = await self._booking_ref(booking_id)
        if ref is None:
            return False
        async def operation(unit):
            row = await unit.get(ref)
            if not row or row['line_user_id'] != line_user_id or row['status'] not in ('provisional', 'confirmed'):
                return False
            row.update(status='cancelled', cancelled_at=now_iso())
            unit.put(ref, row)
            await self._enqueue(unit, 'cancel:' + row['public_id'], settings.ADMIN_USER_ID,
                                notice or f"取消申請 No.{row['id']}\n{row['slot_datetime']} {row['store']}\nカレンダー側の取消確認をお願いします。")
            return True
        return await self._run(operation)

    async def get_session(self, line_user_id):
        async def operation(unit):
            ref = self.ref('sessions', line_user_id)
            row = await unit.get(ref)
            if row and datetime.now(JST) - as_jst(datetime.fromisoformat(row['updated_at'])) > timedelta(minutes=settings.SESSION_TTL_MINUTES):
                unit.delete(ref)
                return None
            return row
        return await self._run(operation)

    async def set_session(self, line_user_id, flow_type, flow_state, flow_data='{}'):
        await self.ref('sessions', line_user_id).set(dict(line_user_id=line_user_id,
            flow_type=flow_type, flow_state=flow_state, flow_data=flow_data, updated_at=now_iso()))

    async def clear_session(self, line_user_id):
        await self.ref('sessions', line_user_id).delete()

    async def get_all_users(self):
        return sorted(await self._rows('users'), key=lambda r: r['created_at'], reverse=True)

    async def claim(self, key, ttl=120):
        owner = str(uuid.uuid4())
        async def operation(unit):
            ref = self.ref('operation_claims', key)
            row = await unit.get(ref)
            if row and (row['done'] or row['expires_at'] >= now_iso()):
                return None
            unit.put(ref, dict(id=key, owner=owner, expires_at=(datetime.now(JST) + timedelta(seconds=ttl)).isoformat(), done=0))
            return owner
        return await self._run(operation)

    async def is_done(self, key):
        row = await self._get('operation_claims', key)
        return bool(row and row['done'])

    async def release(self, key, owner, done=False):
        async def operation(unit):
            ref = self.ref('operation_claims', key)
            row = await unit.get(ref)
            if row and row['owner'] == owner:
                if done:
                    row['done'] = 1
                    unit.put(ref, row)
                elif not row['done']:
                    unit.delete(ref)
        await self._run(operation)

    async def pending_notifications(self, limit=50):
        # Bounded scans keep a failed-notification backlog from exhausting free reads.
        rows = await self._rows('notification_outbox', 'state', 'pending', limit=100)
        candidates = sorted(rows, key=lambda r: r['created_at'])
        claimed = []
        for candidate in candidates:
            if candidate.get('lease_until') and candidate['lease_until'] >= now_iso():
                continue
            async def operation(unit):
                ref = self.ref('notification_outbox', candidate['id'])
                row = await unit.get(ref)
                if not row or row['state'] != 'pending' or (row.get('lease_until') and row['lease_until'] >= now_iso()):
                    return None
                previous = dict(row)
                row.update(lease_until=(datetime.now(JST) + timedelta(minutes=2)).isoformat(), attempts=row['attempts'] + 1)
                unit.put(ref, row)
                return previous
            result = await self._run(operation)
            if result:
                claimed.append(result)
            if len(claimed) >= limit:
                break
        return claimed

    async def notification_result(self, ident, error=None, manual=False):
        async def operation(unit):
            ref = self.ref('notification_outbox', ident)
            row = await unit.get(ref)
            if not row:
                return
            if error is None:
                row.update(state='sent', lease_until=None, last_error=None)
            else:
                row.update(last_error=type(error).__name__, lease_until=(datetime.now(JST) + timedelta(minutes=2)).isoformat())
            if manual:
                row['state'] = 'review'
            unit.put(ref, row)
            if error is None and row['kind'].startswith('flex:'):
                wid = row['kind'].split(':', 1)[1]
                request=await unit.get(self.ref('waitlist_requests',wid))
                if not request or json.loads(request['payload']).get('source')!='chat':
                    await self._enqueue(unit, 'sheet-offer:' + wid, 'sheets', json.dumps({'id': wid, 'status': '通知済み'}), 'sheet')
        await self._run(operation)

    async def notification_backlog(self):
        rows = await self._rows('notification_outbox', 'state', 'pending', limit=100)
        rows += await self._rows('notification_outbox', 'state', 'review', limit=100)
        return sorted(rows, key=lambda r: r['created_at'])[:100]

    async def make_action(self, user_id, payload, ttl=30):
        ident = str(uuid.uuid4())
        await self.ref('action_tokens', ident).set(dict(id=ident, line_user_id=user_id,
            payload=json.dumps(payload), expires_at=(datetime.now(JST) + timedelta(minutes=ttl)).isoformat()))
        return json.dumps({'a': 'action', 'id': ident}, separators=(',', ':'))

    async def get_action(self, ident, user_id):
        row = await self._get('action_tokens', ident)
        return json.loads(row['payload']) if row and row['line_user_id'] == user_id and row['expires_at'] >= now_iso() else None

    async def user_waitlists(self,uid):
        return [r for r in await self._rows('waitlist_requests','line_user_id',uid) if r['state'] in ('waiting','offered')][:100]

    async def withdraw_waitlist(self,ident,uid):
        async def operation(unit):
            ref=self.ref('waitlist_requests',ident)
            row=await unit.get(ref)
            if not row or row['line_user_id']!=uid or row['state'] not in ('waiting','offered'): return False
            row.update(state='cancelled',updated_at=now_iso());unit.put(ref,row)
            await self._enqueue(unit,'waitlist-withdraw:'+ident,settings.ADMIN_USER_ID,'🔔 キャンセル待ちの取り下げ\n受付番号: '+ident)
            return True
        return await self._run(operation)

    async def request_waitlist(self,ident,user_id,payload,notice):
        async def operation(unit):
            ref=self.ref('waitlist_requests',ident)
            if await unit.get(ref): return False
            unit.put(ref,dict(id=ident,line_user_id=user_id,payload=json.dumps(payload),state='waiting',updated_at=now_iso()))
            await self._enqueue(unit,'waitlist-request:'+ident,settings.ADMIN_USER_ID,notice)
            return True
        return await self._run(operation)

    async def waiting_requests(self):
        rows=await self._rows('waitlist_requests','state','waiting',limit=100)
        valid=[]
        for row in rows:
            dates=json.loads(row['payload']).get('dates',[])
            if dates and max(dates)<datetime.now(JST).strftime('%Y-%m-%d'):
                async def expire(unit):
                    ref=self.ref('waitlist_requests',row['id'])
                    current=await unit.get(ref)
                    if current and current['state']=='waiting':
                        current['state']='expired';unit.put(ref,current)
                await self._run(expire)
            else: valid.append(row)
        return valid

    async def save_waitlist_offer(self, ident, user_id, payload, flex):
        async def operation(unit):
            ref = self.ref('waitlist_requests', ident)
            current=await unit.get(ref)
            if current and (current['state']!='waiting' or current['line_user_id']!=user_id):
                return False
            unit.put(ref, dict(id=ident, line_user_id=user_id, payload=json.dumps(payload), state='offered', updated_at=now_iso()))
            await self._enqueue(unit, 'waitlist-offer:' + ident, user_id, json.dumps(flex), 'flex:' + ident)
            return True
        return await self._run(operation)

    async def get_waitlist(self, ident, user_id):
        row = await self._get('waitlist_requests', ident)
        return row if row and row['line_user_id'] == user_id else None

    async def waitlist_state(self, ident):
        row = await self._get('waitlist_requests', ident)
        return row['state'] if row else None

    async def waitlist_overview(self):
        return sorted(await self._rows('waitlist_requests', limit=100), key=lambda r: r['updated_at'], reverse=True)

    async def respond_waitlist(self, ident, user_id, state, notice):
        if state not in ('accepted', 'declined'):
            raise ValueError('Invalid waitlist state')
        async def operation(unit):
            ref = self.ref('waitlist_requests', ident)
            row = await unit.get(ref)
            if not row or row['line_user_id'] != user_id or row['state'] != 'offered':
                return False
            row.update(state=state, updated_at=now_iso())
            unit.put(ref, row)
            await self._enqueue(unit, 'waitlist-response:' + ident, settings.ADMIN_USER_ID, notice)
            if json.loads(row['payload']).get('source')!='chat':
                await self._enqueue(unit, 'sheet-response:' + ident, 'sheets', json.dumps({'id': ident, 'status': '承諾' if state == 'accepted' else '辞退'}), 'sheet')
            return True
        return await self._run(operation)

    async def review_booking(self, public_id, state, calendar_id=''):
        if state not in ('confirmed', 'rejected') or (state == 'confirmed' and not calendar_id):
            raise ValueError('Invalid review')
        async def operation(unit):
            ref = self.ref('bookings', public_id)
            row = await unit.get(ref)
            if not row or row['status'] != 'provisional':
                return False
            extra = json.loads(row.get('metadata') or '{}')
            extra['calendar_id'] = calendar_id
            row.update(status=state, metadata=json.dumps(extra), confirmed_at=now_iso() if state == 'confirmed' else None)
            unit.put(ref, row)
            original = extra.get('change_from', {})
            if state == 'confirmed' and original.get('type') == 'db':
                old_ref = self.ref('bookings', original['id'])
                old = await unit.get(old_ref)
                if old and old['line_user_id'] == row['line_user_id']:
                    old['status'] = 'superseded'
                    unit.put(old_ref, old)
            await self._enqueue(unit, 'review:' + public_id, row['line_user_id'],
                                f"予約{'が確定しました' if state == 'confirmed' else 'をお取りできませんでした'}。\n{row['slot_datetime']} {row['store']}")
            return True
        return await self._run(operation)

    async def pending_bookings(self):
        return sorted([decode(r) for r in await self._rows('bookings', 'status', 'provisional')], key=lambda r: r['created_at'])
