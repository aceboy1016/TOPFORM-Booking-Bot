"""Read-only SQLite export/validation, optional import into an EMPTY PostgreSQL DB.

No notifications are enqueued or sent during migration. Credentials are read from
an environment variable, never command-line arguments or logs.
"""
import argparse,asyncio,json,os,sqlite3,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import datetime
from sqlalchemy import select,func,text
from database import Database,users,bookings,sessions
from booking_rules import as_jst

def read_source(path):
    source=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    try:
        names={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows={name:[dict(r) for r in source.execute('SELECT * FROM '+name)] if name in names else [] for name in ('users','bookings','sessions')}
    finally: source.close()
    for row in rows['bookings']:
        # Invalid legacy values must be reviewed, not silently altered.
        row['slot_datetime']=as_jst(datetime.fromisoformat(row['slot_datetime'])).isoformat()
        row['public_id']=row.get('public_id') or str(uuid.uuid4())
        if row.get('metadata'): json.loads(row['metadata'])
    return rows

async def migrate(source,url):
    if not url.startswith('postgresql+asyncpg://'): raise ValueError('Target must be PostgreSQL')
    rows=read_source(source)
    target=Database(url)
    try:
        await target.init_db()
        async with target.engine.begin() as conn:
            for table in (users,bookings,sessions):
                if (await conn.execute(select(func.count()).select_from(table))).scalar():
                    raise ValueError('Target must be empty; no records were imported')
            for table in (users,bookings,sessions):
                allowed=set(table.c.keys())
                values=[{k:v for k,v in row.items() if k in allowed} for row in rows[table.name]]
                for row in values: await conn.execute(table.insert().values(**row))
                await conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), COALESCE((SELECT MAX(id) FROM {table.name}), 1), EXISTS(SELECT 1 FROM {table.name}))"))
    finally: await target.close()
    return {name:len(value) for name,value in rows.items()}

def cli():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    try:
        if args.apply: counts=asyncio.run(migrate(args.source,os.environ.get('DATABASE_URL','')))
        else: counts={name:len(value) for name,value in read_source(args.source).items()}
        print(json.dumps({'validated':True,'imported':args.apply,'counts':counts}))
    except Exception as exc:
        # Exception text from SQL clients may include customer records/URLs.
        print('Migration failed ('+type(exc).__name__+'). Check the source format and target configuration.',file=sys.stderr)
        sys.exit(1)

if __name__=='__main__': cli()
