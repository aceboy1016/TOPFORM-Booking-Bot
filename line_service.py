"""
TOPFORM LINE Bot - LINE Service
LINEメッセージの処理と予約フローの管理
"""

import json
import re
from datetime import datetime, timedelta
from typing import Optional

import pytz
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    FlexContainer,
    QuickReply,
    QuickReplyItem,
    MessageAction,
    DatetimePickerAction,
    URIAction,
)

from config import settings, STORE_NAMES, BUSINESS_HOURS
from database import db
from calendar_service import (
    calendar_service,
    get_available_slots,
    check_availability,
    find_user_bookings,
    BookingData,
)
from sheets_service import sheets_service

JST = pytz.timezone("Asia/Tokyo")

# 曜日の日本語表記
WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]
WEEKDAY_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class LINEService:
    """LINE Messaging API サービス"""

    def __init__(self):
        self._api_client: Optional[AsyncApiClient] = None
        self._api: Optional[AsyncMessagingApi] = None
        self._handler: Optional[WebhookHandler] = None
        self._cached_bookings: Optional[BookingData] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=1)  # 1分キャッシュ (5分から短縮)

    async def initialize(self):
        """Initialize LINE API clients."""
        if self._api:
            return  # Already initialized

        config = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
        self._api_client = AsyncApiClient(config)
        self._api = AsyncMessagingApi(self._api_client)
        self._handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

    @property
    def handler(self):
        return self._handler

    async def _get_bookings(self) -> BookingData:
        """Get calendar bookings with caching."""
        now = datetime.now(JST)
        if (
            self._cached_bookings is None
            or self._cache_time is None
            or now - self._cache_time > self._cache_ttl
        ):
            self._cached_bookings = calendar_service.fetch_all_bookings()
            self._cache_time = now
        return self._cached_bookings

    def _invalidate_cache(self):
        """Invalidate the booking cache."""
        self._cached_bookings = None
        self._cache_time = None

    # ============================================================
    # User Profile
    # ============================================================
    async def get_user_profile(self, user_id: str) -> str:
        """Get user's display name from LINE."""
        try:
            profile = await self._api.get_profile(user_id)
            return profile.display_name
        except Exception:
            return "ゲスト"

    # ============================================================
    # Reply helpers
    # ============================================================
    async def reply_text(
        self,
        reply_token: str,
        text: str,
        quick_reply: Optional[QuickReply] = None,
    ):
        """Send a text reply."""
        message = TextMessage(text=text, quick_reply=quick_reply)
        await self._api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token, messages=[message]
            )
        )

    async def reply_flex(
        self, reply_token: str, alt_text: str, flex_content: dict
    ):
        """Send a Flex Message reply."""
        message = FlexMessage(
            alt_text=alt_text,
            contents=FlexContainer.from_dict(flex_content),
        )
        await self._api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[message])
        )

    async def reply_messages(self, reply_token: str, messages: list):
        """Send multiple messages."""
        await self._api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=messages)
        )

    async def push_text(self, to_user_id: str, text: str):
        """Send a push text message to a user."""
        message = TextMessage(text=text)
        from linebot.v3.messaging import PushMessageRequest
        
        await self._api.push_message(
            PushMessageRequest(to=to_user_id, messages=[message])
        )

    async def push_flex(self, to_user_id: str, alt_text: str, flex_content: dict):
        """Send a push Flex message to a user."""
        message = FlexMessage(
            altText=alt_text,
            contents=FlexContainer.from_dict(flex_content),
        )
        from linebot.v3.messaging import PushMessageRequest
        await self._api.push_message(
            PushMessageRequest(to=to_user_id, messages=[message])
        )

PLACEHOLDER_REST_OF_FILE_TOO_RISKY