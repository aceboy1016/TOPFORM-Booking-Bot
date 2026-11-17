"""Both storage backends must answer the same calls.

Production runs Firestore while the default test run uses SQLite, so a method
added to one backend alone passes every test here and then fails in production
on the first call. Compare the surfaces directly instead.
"""
import inspect
from database import Database
from firestore_database import FirestoreDatabase


# SQL-dialect helper used only inside database.py; callers never reach for it.
SQL_ONLY = {'insert'}


def api(cls):
    return {name for name, value in inspect.getmembers(cls, inspect.isfunction)
            if not name.startswith('_')} - SQL_ONLY


def test_firestore_implements_every_sql_method():
    missing = api(Database) - api(FirestoreDatabase)
    assert not missing, 'Firestore backend is missing: ' + ', '.join(sorted(missing))


def test_shared_methods_take_the_same_arguments():
    mismatched = []
    for name in sorted(api(Database) & api(FirestoreDatabase)):
        sql = inspect.signature(getattr(Database, name)).parameters
        store = inspect.signature(getattr(FirestoreDatabase, name)).parameters
        if list(sql) != list(store):
            mismatched.append(f'{name}: {list(sql)} vs {list(store)}')
    assert not mismatched, 'Signatures differ: ' + '; '.join(mismatched)
