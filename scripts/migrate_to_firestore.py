"""Import a quiesced SQL snapshot into an EMPTY Firestore prefix.

The caller must fence SQL writers before exporting. Raw backups stay outside Git.
No notifications are sent by migration. Pending leases are released because the
old workers have been stopped; accepted LINE deliveries keep the same retry key.
"""
import copy
import hashlib
import json

TABLES = ('users', 'bookings', 'sessions', 'notification_outbox',
          'operation_claims', 'action_tokens', 'waitlist_requests')

def key_for(table, row):
    if table in ('users', 'sessions'):
        return row['line_user_id']
    return row['public_id'] if table == 'bookings' else row['id']

def normalize(snapshot):
    if set(snapshot) != set(TABLES):
        raise ValueError('Snapshot must include every table')
    result = copy.deepcopy(snapshot)
    for table, rows in result.items():
        keys = [str(key_for(table, row)) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate source identities')
    for row in result['operation_claims']:
        if not row['done']:
            row['expires_at'] = '1970-01-01T00:00:00+09:00'
    for row in result['notification_outbox']:
        if row['state'] == 'pending':
            row['lease_until'] = None
    return result

def digest(snapshot):
    canonical={table: sorted(rows,key=lambda row:str(key_for(table,row))) for table,rows in snapshot.items()}
    return hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

async def import_snapshot(store, snapshot):
    expected=normalize(snapshot)
    for table in TABLES:
        if [s async for s in store.collection(table).limit(1).stream()]:
            raise ValueError('Firestore target is not empty')
    batch=store.client.batch(); count=0
    for table,rows in expected.items():
        for row in rows:
            batch.set(store.ref(table,key_for(table,row)),row)
            count+=1
            if count==400:
                await batch.commit();batch=store.client.batch();count=0
    if count: await batch.commit()
    actual={table:[s.to_dict() async for s in store.collection(table).stream()] for table in TABLES}
    if digest(actual)!=digest(expected):
        raise RuntimeError('Migration verification failed; do not promote the target')
    return {'counts':{table:len(rows) for table,rows in actual.items()},'sha256':digest(actual)}
