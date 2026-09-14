import json,hmac,hashlib,base64
from unittest.mock import AsyncMock
import httpx
import pytest
import main
from config import settings

@pytest.fixture
async def client(database):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c: yield c

async def test_booking_api_requires_auth(client):
    assert (await client.get('/api/bookings/u')).status_code==401
    assert (await client.get('/api/bookings/u',headers={'Authorization':'Bearer '+settings.ADMIN_API_TOKEN})).status_code==200

async def test_waitlist_get_disabled(client): assert (await client.get('/api/check-waitlist')).status_code==405
async def test_waitlist_post_requires_auth(client): assert (await client.post('/api/check-waitlist')).status_code==401
async def test_health_does_not_lie(client): assert (await client.get('/health')).status_code==503
async def test_bad_signature(client,monkeypatch):
    monkeypatch.setattr(settings,'LINE_CHANNEL_SECRET','test-secret')
    assert (await client.post('/webhook',content='{}',headers={'X-Line-Signature':'bad'})).status_code==400

def signed_body():
    body=json.dumps({'destination':'bot','events':[{'type':'message','webhookEventId':'event-1','timestamp':1,'mode':'active','source':{'type':'user','userId':'u'},'replyToken':'token','deliveryContext':{'isRedelivery':False},'message':{'type':'text','id':'m','text':'test','quoteToken':'quote'}}]})
    signature=base64.b64encode(hmac.new(b'secret',body.encode(),hashlib.sha256).digest()).decode()
    return body,{'X-Line-Signature':signature}

async def test_webhook_failure_is_retryable(client,monkeypatch):
    monkeypatch.setattr(settings,'LINE_CHANNEL_SECRET','secret')
    monkeypatch.setattr(main.line_service,'handle_text_message',AsyncMock(side_effect=RuntimeError()))
    monkeypatch.setattr(main,'flush_notifications',AsyncMock())
    body,headers=signed_body()
    assert (await client.post('/webhook',content=body,headers=headers)).status_code==503

async def test_webhook_deduplication(client,monkeypatch):
    monkeypatch.setattr(settings,'LINE_CHANNEL_SECRET','secret')
    handler=AsyncMock();monkeypatch.setattr(main.line_service,'handle_text_message',handler)
    monkeypatch.setattr(main,'flush_notifications',AsyncMock())
    body,headers=signed_body()
    assert (await client.post('/webhook',content=body,headers=headers)).status_code==200
    assert (await client.post('/webhook',content=body,headers=headers)).status_code==200
    assert handler.await_count==1

async def test_public_schema_disabled(client):
    assert (await client.get('/openapi.json')).status_code==404
