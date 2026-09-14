from unittest.mock import AsyncMock, Mock
import pytest
from google.api_core.exceptions import Aborted, ServiceUnavailable
import firestore_database as fd

@pytest.mark.parametrize('wrapped',[False,True])
async def test_aborted_transaction_retries_with_new_transaction(monkeypatch,wrapped):
    error=Aborted('conflict')
    if wrapped:
        wrapped_error=ValueError('commit exhausted');wrapped_error.__cause__=error;error=wrapped_error
    apply=AsyncMock(side_effect=[error,'saved'])
    monkeypatch.setattr(fd.firestore,'async_transactional',lambda fn:apply)
    sleep=AsyncMock();monkeypatch.setattr(fd.asyncio,'sleep',sleep)
    client=Mock();client.transaction.side_effect=[object(),object()]
    store=fd.FirestoreDatabase(client=client)
    assert await store._run(AsyncMock())=='saved'
    assert apply.await_count==2 and sleep.await_count==1
    assert apply.call_args_list[0].args[0] is not apply.call_args_list[1].args[0]

@pytest.mark.parametrize('error',[ValueError('invalid booking'),ServiceUnavailable('unknown commit result')])
async def test_unrelated_or_uncertain_failure_is_not_replayed(monkeypatch,error):
    apply=AsyncMock(side_effect=error)
    monkeypatch.setattr(fd.firestore,'async_transactional',lambda fn:apply)
    with pytest.raises(type(error)):
        await fd.FirestoreDatabase(client=Mock())._run(AsyncMock())
    assert apply.await_count==1

async def test_abort_retry_is_bounded(monkeypatch):
    apply=AsyncMock(side_effect=Aborted('conflict'))
    monkeypatch.setattr(fd.firestore,'async_transactional',lambda fn:apply)
    monkeypatch.setattr(fd.asyncio,'sleep',AsyncMock())
    with pytest.raises(Aborted):
        await fd.FirestoreDatabase(client=Mock())._run(AsyncMock())
    assert apply.await_count==5
