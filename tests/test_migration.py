import sqlite3
import pytest
from scripts.migrate_database import read_source

def source_file(tmp_path, slot='2026-09-20T09:00:00'):
    path = tmp_path/'legacy.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE bookings(id INTEGER PRIMARY KEY, line_user_id TEXT, store TEXT, slot_datetime TEXT, metadata TEXT)')
        conn.execute('INSERT INTO bookings VALUES(1, ?, ?, ?, ?)', ('test-user', 'ebisu', slot, '{}'))
    return path

def test_source_normalizes_without_modifying_file(tmp_path):
    path=source_file(tmp_path)
    before=path.read_bytes()
    rows=read_source(path)
    assert rows['bookings'][0]['slot_datetime']=='2026-09-20T09:00:00+09:00'
    assert rows['bookings'][0]['public_id']
    assert path.read_bytes()==before

def test_source_rejects_invalid_datetime(tmp_path):
    with pytest.raises(ValueError): read_source(source_file(tmp_path,'2026-09-20T99:99:00'))

def test_source_does_not_create_missing_db(tmp_path):
    path=tmp_path/'missing.db'
    with pytest.raises(sqlite3.OperationalError): read_source(path)
    assert not path.exists()

async def test_postgres_import_is_atomic_and_refuses_nonempty_target(database,tmp_path):
    from scripts.migrate_database import migrate
    from database import bookings, outbox
    from sqlalchemy import select, func
    if database.engine.dialect.name!='postgresql':
        pytest.skip('Requires dedicated PostgreSQL integration database')
    path=source_file(tmp_path)
    result=await migrate(path,database._url)
    assert result['bookings']==1
    async with database.engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(outbox))).scalar()==0
    with pytest.raises(ValueError,match='empty'):
        await migrate(path,database._url)
    async with database.engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(bookings))).scalar()==1
