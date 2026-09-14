import pytest
from scripts.migrate_to_firestore import TABLES,normalize,import_snapshot

def test_migration_releases_workers_but_keeps_retry_identity():
    snapshot={name:[] for name in TABLES}
    snapshot['operation_claims']=[{'id':'event:1','done':0,'expires_at':'future'}]
    snapshot['notification_outbox']=[{'id':'retry-key','state':'pending','lease_until':'future'}]
    new=normalize(snapshot)
    assert new['operation_claims'][0]['expires_at'].startswith('1970')
    assert new['notification_outbox'][0]=={'id':'retry-key','state':'pending','lease_until':None}
    assert snapshot['notification_outbox'][0]['lease_until']=='future'

async def test_import_preserves_legacy_integer_id_and_rejects_overwrite(database):
    if not hasattr(database,'collection'):pytest.skip('Firestore migration contract')
    snapshot={name:[] for name in TABLES}
    snapshot['bookings']=[{'id':17,'public_id':'legacy-uuid','line_user_id':'u','store':'ebisu','slot_datetime':'2026-10-01T10:00:00+09:00','status':'provisional','metadata':'{}'}]
    result=await import_snapshot(database,snapshot)
    assert result['counts']['bookings']==1
    assert (await database.get_booking(17,'u'))['public_id']=='legacy-uuid'
    with pytest.raises(ValueError,match='not empty'):await import_snapshot(database,snapshot)

async def test_redelivery_after_sql_migration_reuses_request_and_outbox(database,tmp_path):
    if not hasattr(database,'collection'):pytest.skip('Firestore migration contract')
    from database import Database,current_event,metadata
    from tests.storage_helpers import records
    source=Database('sqlite+aiosqlite:///'+str(tmp_path/'source.db'))
    await source.init_db()
    token=current_event.set('event-before-migration')
    try:
        ident=await source.save_booking('u','ebisu','2026-10-01T10:00:00+09:00')
        snapshot={name:await records(source,metadata.tables[name]) for name in TABLES}
        await import_snapshot(database,snapshot)
        repeated=await database.save_booking('u','ebisu','2026-10-01T10:00:00+09:00')
        assert repeated==ident
        assert len(await database.get_user_bookings('u',include_past=True))==1
        assert len(await database.notification_backlog())==1
    finally:
        current_event.reset(token)
        await source.close()
