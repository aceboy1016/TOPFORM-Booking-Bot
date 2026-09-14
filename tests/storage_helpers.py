from sqlalchemy import select, update

async def records(store, table):
    if hasattr(store, 'collection'):
        return [s.to_dict() async for s in store.collection(table.name).stream()]
    async with store.engine.connect() as conn:
        return [dict(r) for r in (await conn.execute(select(table))).mappings()]

async def patch_rows(store, table, values, field=None, value=None, negate=False):
    if hasattr(store, 'collection'):
        async for snap in store.collection(table.name).stream():
            row=snap.to_dict()
            if field is None or ((row[field] != value) if negate else (row[field] == value)):
                await snap.reference.update(values)
    else:
        statement=update(table).values(**values)
        if field is not None:
            statement=statement.where(table.c[field]!=value if negate else table.c[field]==value)
        async with store.engine.begin() as conn:
            await conn.execute(statement)
