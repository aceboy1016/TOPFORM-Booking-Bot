"""Transactional booking requests, expiring sessions and retryable notifications.

SQLite is for local development; production uses shared Firestore or PostgreSQL.
"""
import json
import uuid
import hashlib
from datetime import datetime, timedelta
from contextvars import ContextVar
from sqlalchemy import (MetaData, Table, Column, Integer, Text, select, update, delete,
                        and_, or_, inspect, text, Index)
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from config import settings
from booking_rules import JST, as_jst

current_event = ContextVar('current_event', default='')
metadata = MetaData()
users = Table('users', metadata, Column('id',Integer,primary_key=True),
    Column('line_user_id',Text,unique=True,nullable=False), Column('display_name',Text),
    Column('preferred_store',Text),Column('created_at',Text),Column('updated_at',Text))
bookings = Table('bookings',metadata,Column('id',Integer,primary_key=True),
    Column('line_user_id',Text,nullable=False),Column('store',Text,nullable=False),
    Column('slot_datetime',Text,nullable=False),Column('status',Text),Column('created_at',Text),
    Column('confirmed_at',Text),Column('cancelled_at',Text),Column('metadata',Text),
    Column('request_key',Text),Column('public_id',Text))
Index('booking_request_key',bookings.c.request_key,unique=True)
Index('booking_public_id',bookings.c.public_id,unique=True)
sessions = Table('sessions',metadata,Column('id',Integer,primary_key=True),
    Column('line_user_id',Text,unique=True,nullable=False),Column('flow_type',Text),
    Column('flow_state',Text),Column('flow_data',Text),Column('updated_at',Text))
outbox = Table('notification_outbox',metadata,Column('id',Text,primary_key=True),
    Column('recipient',Text,nullable=False),Column('body',Text,nullable=False),
    Column('kind',Text,nullable=False),Column('state',Text,nullable=False),
    Column('attempts',Integer,nullable=False),Column('created_at',Text),
    Column('lease_until',Text),Column('last_error',Text))
claims = Table('operation_claims',metadata,Column('id',Text,primary_key=True),
    Column('owner',Text),Column('expires_at',Text),Column('done',Integer,nullable=False))
actions = Table('action_tokens',metadata,Column('id',Text,primary_key=True),
    Column('line_user_id',Text,nullable=False),Column('payload',Text),Column('expires_at',Text))
waitlist = Table('waitlist_requests',metadata,Column('id',Text,primary_key=True),
    Column('line_user_id',Text),Column('payload',Text),Column('state',Text),Column('updated_at',Text))


def now_iso(): return datetime.now(JST).isoformat()
def decode(row):
    result=dict(row)
    if 'metadata' in result:
        try: result['metadata']=json.loads(result['metadata'] or '{}')
        except (ValueError,TypeError): result['metadata']={}
    return result

class Database:
    def __init__(self, url=None):
        self._db_path=settings.DATABASE_PATH
        self._url=url
        self._engine=None

    @property
    def engine(self):
        if self._engine is None:
            url=self._url or settings.DATABASE_URL or 'sqlite+aiosqlite:///'+self._db_path
            # Cloud SQL shared-core has 25 connections; three app instances
            # may use at most 15, leaving room for reserved/admin connections.
            options = {'pool_size': 2, 'max_overflow': 3, 'pool_timeout': 15} if url.startswith('postgresql') else {}
            self._engine=create_async_engine(url,pool_pre_ping=True,**options)
        return self._engine

    def insert(self,table):
        return pg_insert(table) if self.engine.dialect.name=='postgresql' else sqlite_insert(table)

    async def init_db(self):
        async with self.engine.begin() as conn:
            if self.engine.dialect.name == 'postgresql':
                await conn.execute(text('SELECT pg_advisory_xact_lock(861401)'))
            await conn.run_sync(metadata.create_all)
            columns=await conn.run_sync(lambda c:{x['name'] for x in inspect(c).get_columns('bookings')})
            for name in ('metadata','request_key','public_id'):
                if name not in columns: await conn.execute(text(f'ALTER TABLE bookings ADD COLUMN {name} TEXT'))
            rows=(await conn.execute(select(bookings.c.id).where(bookings.c.public_id.is_(None)))).all()
            for (bid,) in rows:
                await conn.execute(update(bookings).where(bookings.c.id==bid).values(public_id=str(uuid.uuid4())))
            for index in bookings.indexes:
                await conn.run_sync(lambda c,index=index:index.create(c,checkfirst=True))

    async def close(self):
        if self._engine: await self._engine.dispose()

    async def health(self):
        async with self.engine.connect() as conn: await conn.execute(text('SELECT 1'))
        return True

    async def get_or_create_user(self,line_user_id,display_name=None):
        async with self.engine.begin() as conn:
            stmt=self.insert(users).values(line_user_id=line_user_id,display_name=display_name or 'ゲスト',created_at=now_iso(),updated_at=now_iso())
            stmt=stmt.on_conflict_do_update(index_elements=['line_user_id'],set_={'display_name':display_name,'updated_at':now_iso()}) if display_name else stmt.on_conflict_do_nothing(index_elements=['line_user_id'])
            await conn.execute(stmt)
            return dict((await conn.execute(select(users).where(users.c.line_user_id==line_user_id))).mappings().one())

    async def _enqueue(self,conn,key,recipient,body,kind='text'):
        if not recipient: raise ValueError('通知先が未設定です')
        ident=str(uuid.uuid5(uuid.NAMESPACE_URL,key))
        await conn.execute(self.insert(outbox).values(id=ident,recipient=recipient,body=body,kind=kind,state='pending',attempts=0,created_at=now_iso()).on_conflict_do_nothing(index_elements=['id']))
        return ident

    async def enqueue(self,key,recipient,body,kind='text'):
        async with self.engine.begin() as conn: return await self._enqueue(conn,key,recipient,body,kind)

    async def save_booking(self,line_user_id,store,slot_datetime,status='provisional',metadata=None):
        slot_datetime=as_jst(datetime.fromisoformat(slot_datetime)).isoformat()
        extra=metadata or {}
        fingerprint=json.dumps([line_user_id,store,slot_datetime,extra.get('change_from')],sort_keys=True)
        key=hashlib.sha256((current_event.get() or str(uuid.uuid4())).encode()+fingerprint.encode()).hexdigest()
        async with self.engine.begin() as conn:
            stmt=self.insert(bookings).values(line_user_id=line_user_id,store=store,slot_datetime=slot_datetime,status=status,metadata=json.dumps(extra,ensure_ascii=False),created_at=now_iso(),request_key=key,public_id=str(uuid.uuid4())).on_conflict_do_nothing(index_elements=['request_key'])
            await conn.execute(stmt)
            row=(await conn.execute(select(bookings).where(bookings.c.request_key==key))).mappings().one()
            summary=f"予約リクエスト No.{row['id']}\nお名前: {extra.get('customer_name',line_user_id)}\n日時: {slot_datetime}\n店舗: {store}\n個室希望: {extra.get('room','指定なし')}"
            if extra.get('change_from'): summary+=f"\n変更前: {extra['change_from']}\n旧予約は本変更完了まで保持しています。"
            summary+='\nスタッフ確認後、カレンダー登録・承認をお願いします。'
            await self._enqueue(conn,'booking:'+key,settings.ADMIN_USER_ID,summary)
            return row['id']

    async def get_user_bookings(self,line_user_id,include_past=False):
        query=select(bookings).where(bookings.c.line_user_id==line_user_id,bookings.c.status.not_in(['cancelled','superseded','rejected']))
        if not include_past: query=query.where(bookings.c.slot_datetime>=now_iso())
        async with self.engine.connect() as conn:
            return [decode(r) for r in (await conn.execute(query.order_by(bookings.c.slot_datetime))).mappings()]

    async def get_booking(self,booking_id,line_user_id):
        # Prefer immutable UUID; integers accepted only by internal migration tools.
        condition=bookings.c.id==booking_id if isinstance(booking_id,int) else bookings.c.public_id==str(booking_id)
        async with self.engine.connect() as conn:
            row=(await conn.execute(select(bookings).where(condition,bookings.c.line_user_id==line_user_id))).mappings().first()
            return decode(row) if row else None

    async def cancel_booking(self,booking_id,line_user_id,notice=''):
        async with self.engine.begin() as conn:
            condition=bookings.c.id==booking_id if isinstance(booking_id,int) else bookings.c.public_id==str(booking_id)
            row=(await conn.execute(select(bookings).where(condition,bookings.c.line_user_id==line_user_id))).mappings().first()
            if not row: return False
            result=await conn.execute(update(bookings).where(bookings.c.id==row['id'],bookings.c.status.in_(['provisional','confirmed'])).values(status='cancelled',cancelled_at=now_iso()))
            if not result.rowcount: return False
            await self._enqueue(conn,'cancel:'+row['public_id'],settings.ADMIN_USER_ID,notice or f"取消申請 No.{row['id']}\n{row['slot_datetime']} {row['store']}\nカレンダー側の取消確認をお願いします。")
            return True

    async def get_session(self,line_user_id):
        async with self.engine.begin() as conn:
            row=(await conn.execute(select(sessions).where(sessions.c.line_user_id==line_user_id))).mappings().first()
            if not row: return None
            updated=as_jst(datetime.fromisoformat(row['updated_at']))
            if datetime.now(JST)-updated>timedelta(minutes=settings.SESSION_TTL_MINUTES):
                await conn.execute(delete(sessions).where(sessions.c.line_user_id==line_user_id));return None
            return dict(row)

    async def set_session(self,line_user_id,flow_type,flow_state,flow_data='{}'):
        values=dict(line_user_id=line_user_id,flow_type=flow_type,flow_state=flow_state,flow_data=flow_data,updated_at=now_iso())
        async with self.engine.begin() as conn: await conn.execute(self.insert(sessions).values(**values).on_conflict_do_update(index_elements=['line_user_id'],set_=values))

    async def clear_session(self,line_user_id):
        async with self.engine.begin() as conn: await conn.execute(delete(sessions).where(sessions.c.line_user_id==line_user_id))

    async def get_all_users(self):
        async with self.engine.connect() as conn: return [dict(r) for r in (await conn.execute(select(users).order_by(users.c.created_at.desc()))).mappings()]

    async def claim(self,key,ttl=120):
        owner=str(uuid.uuid4());now=now_iso();end=(datetime.now(JST)+timedelta(seconds=ttl)).isoformat()
        async with self.engine.begin() as conn:
            result=await conn.execute(self.insert(claims).values(id=key,owner=owner,expires_at=end,done=0).on_conflict_do_update(index_elements=['id'],set_={'owner':owner,'expires_at':end},where=and_(claims.c.done==0,claims.c.expires_at<now)).returning(claims.c.owner))
            return owner if result.first() else None

    async def is_done(self,key):
        async with self.engine.connect() as conn: return (await conn.execute(select(claims.c.done).where(claims.c.id==key))).scalar()==1

    async def release(self,key,owner,done=False):
        async with self.engine.begin() as conn:
            if done: await conn.execute(update(claims).where(claims.c.id==key,claims.c.owner==owner).values(done=1))
            else: await conn.execute(delete(claims).where(claims.c.id==key,claims.c.owner==owner,claims.c.done==0))

    async def pending_notifications(self,limit=50):
        async with self.engine.begin() as conn:
            rows=(await conn.execute(select(outbox).where(outbox.c.state=='pending',or_(outbox.c.lease_until.is_(None),outbox.c.lease_until<now_iso())).order_by(outbox.c.created_at).limit(limit))).mappings().all()
            claimed=[]
            for r in rows:
                lease=(datetime.now(JST)+timedelta(minutes=2)).isoformat()
                res=await conn.execute(update(outbox).where(outbox.c.id==r['id'],outbox.c.state=='pending',or_(outbox.c.lease_until.is_(None),outbox.c.lease_until<now_iso())).values(lease_until=lease,attempts=outbox.c.attempts+1))
                if res.rowcount: claimed.append(dict(r))
            return claimed

    async def notification_result(self,ident,error=None,manual=False):
        async with self.engine.begin() as conn:
            values={'state':'sent','lease_until':None,'last_error':None} if error is None else {'last_error':type(error).__name__,'lease_until':(datetime.now(JST)+timedelta(minutes=2)).isoformat()}
            if manual: values['state']='review'
            await conn.execute(update(outbox).where(outbox.c.id==ident).values(**values))
            if error is None:
                row=(await conn.execute(select(outbox).where(outbox.c.id==ident))).mappings().first()
                if row and row['kind'].startswith('flex:'):
                    entry_id=row['kind'].split(':',1)[1]
                    stored=(await conn.execute(select(waitlist.c.payload).where(waitlist.c.id==entry_id))).scalar()
                    if not stored or json.loads(stored).get('source')!='chat':
                        await self._enqueue(conn,'sheet-offer:'+entry_id,'sheets',json.dumps({'id':entry_id,'status':'通知済み'}),'sheet')

    async def notification_backlog(self):
        async with self.engine.connect() as conn:
            return [dict(r) for r in (await conn.execute(select(outbox).where(outbox.c.state!='sent').order_by(outbox.c.created_at).limit(100))).mappings()]

    async def make_action(self,user_id,payload,ttl=30):
        ident=str(uuid.uuid4())
        async with self.engine.begin() as conn: await conn.execute(self.insert(actions).values(id=ident,line_user_id=user_id,payload=json.dumps(payload),expires_at=(datetime.now(JST)+timedelta(minutes=ttl)).isoformat()))
        return json.dumps({'a':'action','id':ident},separators=(',',':'))

    async def get_action(self,ident,user_id):
        async with self.engine.connect() as conn:
            row=(await conn.execute(select(actions).where(actions.c.id==ident,actions.c.line_user_id==user_id,actions.c.expires_at>=now_iso()))).mappings().first()
            return json.loads(row['payload']) if row else None

    async def user_waitlists(self,uid):
        async with self.engine.connect() as conn:
            return [dict(r) for r in (await conn.execute(select(waitlist).where(waitlist.c.line_user_id==uid,waitlist.c.state.in_(['waiting','offered'])).limit(100))).mappings()]

    async def withdraw_waitlist(self,ident,uid):
        async with self.engine.begin() as conn:
            res=await conn.execute(update(waitlist).where(waitlist.c.id==ident,waitlist.c.line_user_id==uid,waitlist.c.state.in_(['waiting','offered'])).values(state='cancelled',updated_at=now_iso()))
            if not res.rowcount: return False
            await self._enqueue(conn,'waitlist-withdraw:'+ident,settings.ADMIN_USER_ID,'🔔 キャンセル待ちの取り下げ\n受付番号: '+ident)
            return True

    async def request_waitlist(self,ident,user_id,payload,notice):
        async with self.engine.begin() as conn:
            res=await conn.execute(self.insert(waitlist).values(id=ident,line_user_id=user_id,payload=json.dumps(payload),state='waiting',updated_at=now_iso()).on_conflict_do_nothing(index_elements=['id']).returning(waitlist.c.id))
            if not res.first(): return False
            await self._enqueue(conn,'waitlist-request:'+ident,settings.ADMIN_USER_ID,notice)
            return True

    async def waiting_requests(self):
        async with self.engine.begin() as conn:
            rows=[dict(r) for r in (await conn.execute(select(waitlist).where(waitlist.c.state=='waiting'))).mappings()]
            valid=[]
            for row in rows:
                dates=json.loads(row['payload']).get('dates',[])
                if dates and max(dates)<datetime.now(JST).strftime('%Y-%m-%d'):
                    await conn.execute(update(waitlist).where(waitlist.c.id==row['id'],waitlist.c.state=='waiting').values(state='expired'))
                else: valid.append(row)
            return valid[:100]

    async def save_waitlist_offer(self,ident,user_id,payload,flex):
        async with self.engine.begin() as conn:
            res=await conn.execute(self.insert(waitlist).values(id=ident,line_user_id=user_id,payload=json.dumps(payload),state='offered',updated_at=now_iso()).on_conflict_do_nothing(index_elements=['id']).returning(waitlist.c.id))
            if not res.first():
                changed=await conn.execute(update(waitlist).where(waitlist.c.id==ident,waitlist.c.line_user_id==user_id,waitlist.c.state=='waiting').values(payload=json.dumps(payload),state='offered',updated_at=now_iso()))
                if not changed.rowcount: return False
            await self._enqueue(conn,'waitlist-offer:'+ident,user_id,json.dumps(flex),'flex:'+ident)
            return True

    async def get_waitlist(self,ident,user_id):
        async with self.engine.connect() as conn:
            row=(await conn.execute(select(waitlist).where(waitlist.c.id==ident,waitlist.c.line_user_id==user_id))).mappings().first()
            return dict(row) if row else None

    async def waitlist_state(self,ident):
        async with self.engine.connect() as conn:
            return (await conn.execute(select(waitlist.c.state).where(waitlist.c.id==ident))).scalar()

    async def waitlist_overview(self):
        async with self.engine.connect() as conn:
            return [dict(r) for r in (await conn.execute(select(waitlist).order_by(waitlist.c.updated_at.desc()).limit(100))).mappings()]

    async def respond_waitlist(self,ident,user_id,state,notice):
        async with self.engine.begin() as conn:
            res=await conn.execute(update(waitlist).where(waitlist.c.id==ident,waitlist.c.line_user_id==user_id,waitlist.c.state=='offered').values(state=state,updated_at=now_iso()))
            if not res.rowcount: return False
            await self._enqueue(conn,'waitlist-response:'+ident,settings.ADMIN_USER_ID,notice)
            stored=(await conn.execute(select(waitlist.c.payload).where(waitlist.c.id==ident))).scalar()
            if json.loads(stored).get('source')!='chat':
                await self._enqueue(conn,'sheet-response:'+ident,'sheets',json.dumps({'id':ident,'status':'承諾' if state=='accepted' else '辞退'}),'sheet')
            return True

    async def review_booking(self,public_id,state,calendar_id=''):
        if state not in ('confirmed','rejected'): raise ValueError('Invalid state')
        if state=='confirmed' and not calendar_id: raise ValueError('Calendar event ID required')
        async with self.engine.begin() as conn:
            row=(await conn.execute(select(bookings).where(bookings.c.public_id==public_id))).mappings().first()
            if not row: return False
            extra=json.loads(row['metadata'] or '{}');extra['calendar_id']=calendar_id
            res=await conn.execute(update(bookings).where(bookings.c.public_id==public_id,bookings.c.status=='provisional').values(status=state,metadata=json.dumps(extra),confirmed_at=now_iso() if state=='confirmed' else None))
            if not res.rowcount: return False
            # Supersede a DB request only after the replacement has been confirmed.
            original=extra.get('change_from',{})
            if state=='confirmed' and original.get('type')=='db':
                await conn.execute(update(bookings).where(bookings.c.public_id==original['id'],bookings.c.line_user_id==row['line_user_id']).values(status='superseded'))
            await self._enqueue(conn,'review:'+public_id,row['line_user_id'],f"予約{'が確定しました' if state=='confirmed' else 'をお取りできませんでした'}。\n{row['slot_datetime']} {row['store']}")
            return True

    async def pending_bookings(self):
        async with self.engine.connect() as conn:
            return [decode(r) for r in (await conn.execute(select(bookings).where(bookings.c.status=='provisional').order_by(bookings.c.created_at))).mappings()]


if settings.DATABASE_BACKEND == 'firestore':
    from firestore_database import FirestoreDatabase
    db = FirestoreDatabase()
else:
    db = Database()
