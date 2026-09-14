import os
for key in ['LINE_CHANNEL_ACCESS_TOKEN','LINE_CHANNEL_SECRET','GOOGLE_CREDENTIALS_JSON','ADMIN_USER_ID','DATABASE_URL','K_SERVICE','DATABASE_BACKEND','FIRESTORE_PROJECT','FIRESTORE_PREFIX']:
    os.environ.pop(key,None)
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from unittest.mock import AsyncMock
from config import settings
from database import Database, metadata

@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(settings,'ADMIN_USER_ID','audit-admin')
    monkeypatch.setattr(settings,'ADMIN_API_TOKEN','x'*64)

@pytest.fixture
async def database(tmp_path,monkeypatch):
    url=os.getenv('TEST_DATABASE_URL')
    if url and not url.endswith('/topform_test'):
        raise ValueError('Integration tests require a dedicated topform_test database')
    if os.getenv('TEST_FIRESTORE'):
        host=os.getenv('FIRESTORE_EMULATOR_HOST','')
        if not host.startswith(('127.0.0.1:', 'localhost:')):
            raise ValueError('Firestore tests require a local emulator')
        import uuid
        from firestore_database import FirestoreDatabase
        store=FirestoreDatabase(project='topform-test',prefix='test_'+uuid.uuid4().hex)
    else:
        store=Database(url or 'sqlite+aiosqlite:///'+str(tmp_path/'test.db'))
        if url:
            async with store.engine.begin() as conn: await conn.run_sync(metadata.drop_all)
    await store.init_db()
    import database, line_service, booking_actions, booking_view, notifications, waitlist_service, main, conversation, conversation_extras, admin_review
    for module in (database,line_service,booking_actions,booking_view,notifications,waitlist_service,main,conversation,conversation_extras,admin_review):
        monkeypatch.setattr(module,'db',store)
    yield store
    if hasattr(store,'collection'):
        for table in store.TABLES:
            async for snap in store.collection(table).stream():
                await snap.reference.delete()
    await store.close()

@pytest.fixture
def service(monkeypatch):
    from line_service import LINEService
    from calendar_service import BookingData
    s=LINEService()
    s.reply_text=AsyncMock();s.reply_flex=AsyncMock();s.reply_messages=AsyncMock();s.push_text=AsyncMock()
    s._get_bookings=AsyncMock(return_value=BookingData([],[],[]))
    return s
