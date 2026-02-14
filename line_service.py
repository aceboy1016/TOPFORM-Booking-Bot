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


class LINEService:
    """LINE Messaging API サービス"""

    def __init__(self):
        self._api_client: Optional[AsyncApiClient] = None
        self._api: Optional[AsyncMessagingApi] = None
        self._handler: Optional[WebhookHandler] = None
        self._cached_bookings: Optional[BookingData] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)  # 5分キャッシュ

    def initialize(self):
        """Initialize LINE API clients."""
        config = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
        self._api_client = AsyncApiClient(config)
        self._api = AsyncMessagingApi(self._api_client)
        self._handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)
        print("✅ LINE Service initialized")

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
        message = TextMessage(text=text, quickReply=quick_reply)
        await self._api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token, messages=[message]
            )
        )

    async def reply_flex(
        self, reply_token: str, alt_text: str, flex_content: dict
    ):
        """Send a Flex Message reply."""
        message = FlexMessage(
            altText=alt_text,
            contents=FlexContainer.from_dict(flex_content),
        )
        await self._api.reply_message(
            ReplyMessageRequest(replyToken=reply_token, messages=[message])
        )

    async def reply_messages(self, reply_token: str, messages: list):
        """Send multiple messages."""
        await self._api.reply_message(
            ReplyMessageRequest(replyToken=reply_token, messages=messages)
        )

    async def push_text(self, user_id: str, text: str):
        """Send a push message."""
        await self._api.push_message(
            PushMessageRequest(
                to=user_id, messages=[TextMessage(text=text)]
            )
        )

    # ============================================================
    # Postback handler
    # ============================================================
    async def handle_postback_event(self, event, user: dict):
        """Handle postback events (button clicks)."""
        data = json.loads(event.postback.data)
        action = data.get("action")
        user_id = event.source.user_id
        reply_token = event.reply_token

        # Enrich user info from Sheets
        customer = sheets_service.get_customer_by_line_id(user_id)
        if customer:
            user["display_name"] = customer["name"]
            user["store_pref"] = customer.get("store_pref")
            user["room_pref"] = customer.get("room_pref")

        if action == "cancel_request":
            booking_id = data.get("booking_id")
            booking_date = data.get("date")
            store_name = data.get("store")
            
            # Cancel in DB
            success = await db.cancel_booking(booking_id, user_id)
            
            if success:
                # Notify User
                await self.reply_text(
                    reply_token,
                    f"✅ 予約のキャンセル申請を受け付けました。\n\n"
                    f"📅 {booking_date}\n"
                    f"📍 {store_name}\n\n"
                    f"またのご予約をお待ちしております！👋"
                )
                
                # Notify Admin
                if settings.ADMIN_USER_ID:
                    display_name = user.get("display_name", "Unknown")
                    admin_msg = (
                        f"🗑️ 予約キャンセル申請\n"
                        f"👤 {display_name}\n"
                        f"📅 {booking_date}\n"
                        f"📍 {store_name}\n"
                        f"🎫 No. {booking_id}\n\n"
                        f"⚠️ hacomono/カレンダーの予定を削除してください！"
                    )
                    try:
                        await self.push_text(settings.ADMIN_USER_ID, admin_msg)
                    except Exception as e:
                        print(f"Admin notification failed: {e}")
                
                self._invalidate_cache()
            else:
                await self.reply_text(
                    reply_token,
                    "⚠️ すでにキャンセルされているか、予約が見つかりませんでした。"
                )

    # ============================================================
    # Main message handler
    # ============================================================
    async def handle_text_message(self, event, user: dict):
        """Handle incoming text message."""
        text = event.message.text.strip()
        user_id = event.source.user_id
        reply_token = event.reply_token

        # Enrich user info from Sheets
        customer = sheets_service.get_customer_by_line_id(user_id)
        if customer:
            user["display_name"] = customer["name"]
            user["store_pref"] = customer.get("store_pref")
            user["room_pref"] = customer.get("room_pref")

        # Check for active session
        session = await db.get_session(user_id)

        # ---- Rich Menu / Command triggers ----
        if text in ["予約する", "予約", "booking"]:
            await self._start_booking_flow(reply_token, user_id)
            return

        if text in ["予約確認", "予約一覧", "マイ予約"]:
            await self._show_user_bookings(reply_token, user_id, user)
            return

        if text in ["早見表", "スケジュール", "空き状況"]:
            await self._show_hayamihyo_link(reply_token)
            return

        if text.lower() in ["id", "id確認", "user_id"]:
            await self.reply_text(reply_token, f"あなたのUser ID:\n{user_id}")
            print(f"🆔 User ID: {user_id}")
            return

        if text == "キャンセル" or text == "やめる":
            await db.clear_session(user_id)
            await self.reply_text(reply_token, "操作をキャンセルしました。\n何かあればいつでもどうぞ！👋")
            return

        # ---- Active session flow ----
        if session:
            flow_type = session.get("flow_type")
            if flow_type == "booking":
                await self._handle_booking_flow(reply_token, user_id, user, session, text)
                return

        # ---- Natural language: 「○日空いてる？」----
        date_match = self._parse_date_query(text)
        if date_match:
            await self._handle_date_query(reply_token, user_id, date_match)
            return

        # ---- Default response ----
        await self._handle_default(reply_token)

    # ============================================================
    # Follow event
    # ============================================================
    async def handle_follow_event(self, event):
        """Handle new user follow."""
        user_id = event.source.user_id
        display_name = await self.get_user_profile(user_id)
        await db.get_or_create_user(user_id, display_name)

        welcome = (
            f"{display_name}さん、友だち追加ありがとうございます！🎉\n\n"
            f"TOPFORMの予約Bot（石原担当）です💪\n\n"
            f"📋 早見表 → スケジュールの確認\n"
            f"📅 予約する → チャットで簡単予約\n"
            f"📖 予約確認 → あなたの予約一覧\n\n"
            f"下のメニューからお選びください！"
        )
        await self.reply_text(event.reply_token, welcome)

    # ============================================================
    # Date query parsing
    # ============================================================
    def _parse_date_query(self, text: str) -> Optional[datetime]:
        """
        Parse natural language date queries.
        Examples:
          「2/20空いてる？」「2月20日は？」「明日空き」「来週月曜」
        """
        now = datetime.now(JST)

        # Pattern: 明日 / 明後日 / 今日
        if "今日" in text:
            return now
        if "明日" in text:
            return now + timedelta(days=1)
        if "明後日" in text or "あさって" in text:
            return now + timedelta(days=2)

        # Pattern: 来週[曜日]
        weekday_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
        m = re.search(r"来週\s*([月火水木金土日])", text)
        if m:
            target_wd = weekday_map[m.group(1)]
            days_ahead = (7 - now.weekday() + target_wd) % 7
            if days_ahead == 0:
                days_ahead = 7
            days_ahead += 7  # 来週
            # Adjust: 来週 means next week, so add enough days
            current_wd = now.weekday()
            days_ahead = (target_wd - current_wd) % 7 + 7
            return now + timedelta(days=days_ahead)

        # Pattern: [曜日] (this week / next occurrence)
        m = re.search(r"(?:今週\s*)?([月火水木金土日])曜", text)
        if m:
            target_wd = weekday_map[m.group(1)]
            days_ahead = (target_wd - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # 今日の曜日なら来週
            return now + timedelta(days=days_ahead)

        # Pattern: M/D or M月D日
        m = re.search(r"(\d{1,2})[/月](\d{1,2})", text)
        if m:
            month = int(m.group(1))
            day = int(m.group(2))
            year = now.year
            try:
                target = JST.localize(datetime(year, month, day))
                # If the date is in the past, assume next year
                if target.date() < now.date():
                    target = target.replace(year=year + 1)
                return target
            except ValueError:
                return None

        # Pattern: D日
        m = re.search(r"(\d{1,2})日", text)
        if m:
            day = int(m.group(1))
            year = now.year
            month = now.month
            try:
                target = JST.localize(datetime(year, month, day))
                if target.date() < now.date():
                    # Next month
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1
                    target = JST.localize(datetime(year, month, day))
                return target
            except ValueError:
                return None

        # Check if text contains availability keywords without a date
        availability_keywords = ["空い", "空き", "予約したい", "取りたい"]
        if any(kw in text for kw in availability_keywords):
            # No specific date found, but user is asking about availability
            return None  # Will be handled differently

        return None

    # ============================================================
    # Date query handler
    # ============================================================
    async def _handle_date_query(
        self, reply_token: str, user_id: str, target_date: datetime
    ):
        """Handle a date availability query."""
        bookings = await self._get_bookings()

        date_str = target_date.strftime("%m月%d日")
        wd = WEEKDAY_JP[target_date.weekday()]

        # Check both stores
        ebisu_slots = get_available_slots(target_date, "ebisu", bookings)
        hanzomon_slots = get_available_slots(target_date, "hanzoomon", bookings)

        if not ebisu_slots and not hanzomon_slots:
            await self.reply_text(
                reply_token,
                f"😔 {date_str}（{wd}）は空きがありません。\n\n別の日を教えてくれれば確認しますよ！📅",
            )
            return

        # Build Flex Message with available slots
        flex = self._build_availability_flex(
            target_date, ebisu_slots, hanzomon_slots
        )
        await self.reply_flex(
            reply_token,
            f"{date_str}（{wd}）の空き状況",
            flex,
        )

    # ============================================================
    # Booking flow
    # ============================================================
    async def _start_booking_flow(self, reply_token: str, user_id: str):
        """Start the interactive booking flow."""
        await db.set_session(
            user_id, "booking", "select_store", json.dumps({})
        )

        quick_reply = QuickReply(
            items=[
                QuickReplyItem(
                    action=MessageAction(label="📍 恵比寿店", text="恵比寿店")
                ),
                QuickReplyItem(
                    action=MessageAction(label="📍 半蔵門店", text="半蔵門店")
                ),
            ]
        )

        await self.reply_text(
            reply_token,
            "📅 予約を始めます！\n\nまず、店舗を選んでください👇",
            quick_reply=quick_reply,
        )

    async def _handle_booking_flow(
        self,
        reply_token: str,
        user_id: str,
        user: dict,
        session: dict,
        text: str,
    ):
        """Handle the booking conversation flow."""
        state = session.get("flow_state", "")
        data = json.loads(session.get("flow_data", "{}"))

        if state == "select_store":
            store = None
            if "恵比寿" in text:
                store = "ebisu"
            elif "半蔵門" in text:
                store = "hanzoomon"

            if not store:
                await self.reply_text(
                    reply_token,
                    "店舗を選んでください👇\n「恵比寿店」か「半蔵門店」",
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(
                                action=MessageAction(
                                    label="📍 恵比寿店", text="恵比寿店"
                                )
                            ),
                            QuickReplyItem(
                                action=MessageAction(
                                    label="📍 半蔵門店", text="半蔵門店"
                                )
                            ),
                        ]
                    ),
                )
                return

            data["store"] = store
            await db.set_session(
                user_id, "booking", "select_date", json.dumps(data)
            )

            await self.reply_text(
                reply_token,
                f"📍 {STORE_NAMES[store]}ですね！\n\n希望の日にちを教えてください。\n例：「2/20」「明日」「来週水曜」",
            )

        elif state == "select_date":
            target_date = self._parse_date_query(text)
            if not target_date:
                await self.reply_text(
                    reply_token,
                    "📅 日にちがわかりませんでした。\n例：「2/20」「明日」「来週の水曜」\n\nもう一度教えてください！",
                )
                return

            store = data.get("store", "ebisu")
            bookings = await self._get_bookings()
            slots = get_available_slots(target_date, store, bookings)

            date_str = target_date.strftime("%m月%d日")
            wd = WEEKDAY_JP[target_date.weekday()]

            if not slots:
                await self.reply_text(
                    reply_token,
                    f"😔 {date_str}（{wd}）の{STORE_NAMES[store]}は空きがありません。\n\n別の日を教えてください📅",
                )
                return

            data["date"] = target_date.strftime("%Y-%m-%d")
            await db.set_session(
                user_id, "booking", "select_time", json.dumps(data)
            )

            # Build quick reply with time slots
            items = []
            for slot in slots[:13]:  # LINE Quick Reply max 13 items
                time_str = slot.strftime("%H:%M")
                items.append(
                    QuickReplyItem(
                        action=MessageAction(label=f"🕐 {time_str}", text=time_str)
                    )
                )

            slot_list = "\n".join(
                [f"  ✅ {s.strftime('%H:%M')}〜{(s + timedelta(hours=1)).strftime('%H:%M')}" for s in slots]
            )

            await self.reply_text(
                reply_token,
                f"📅 {date_str}（{wd}）{STORE_NAMES[store]}の空き状況：\n\n{slot_list}\n\n希望の時間を選んでください👇",
                quick_reply=QuickReply(items=items),
            )

        elif state == "select_time":
            # Parse time
            m = re.match(r"(\d{1,2}):(\d{2})", text)
            if not m:
                await self.reply_text(
                    reply_token,
                    "🕐 時間の形式がわかりませんでした。\n「10:00」のように入力してください。",
                )
                return

            hour = int(m.group(1))
            minute = int(m.group(2))
            date_str = data.get("date")
            store = data.get("store", "ebisu")

            target_date = datetime.strptime(date_str, "%Y-%m-%d")
            slot_time = JST.localize(
                target_date.replace(hour=hour, minute=minute, second=0)
            )

            # Verify availability one more time
            bookings = await self._get_bookings()
            result = check_availability(slot_time, store, bookings)

            if not result["is_available"]:
                self._invalidate_cache()
                await self.reply_text(
                    reply_token,
                    f"😔 申し訳ありません、{slot_time.strftime('%H:%M')}はもう埋まってしまいました。\n\n別の時間を選んでください。",
                )
                return

            data["time"] = f"{hour:02d}:{minute:02d}"
            await db.set_session(
                user_id, "booking", "confirm", json.dumps(data)
            )

            display_date = slot_time.strftime("%m月%d日")
            wd = WEEKDAY_JP[slot_time.weekday()]
            time_range = f"{hour:02d}:{minute:02d}〜{hour + 1:02d}:{minute:02d}"

            confirm_msg = (
                f"📋 予約内容の確認\n\n"
                f"📅 {display_date}（{wd}）\n"
                f"🕐 {time_range}\n"
                f"📍 {STORE_NAMES[store]}\n\n"
                f"この内容でよろしいですか？"
            )

            await self.reply_text(
                reply_token,
                confirm_msg,
                quick_reply=QuickReply(
                    items=[
                        QuickReplyItem(
                            action=MessageAction(label="✅ 確定する", text="確定する")
                        ),
                        QuickReplyItem(
                            action=MessageAction(label="🔄 変更する", text="変更する")
                        ),
                        QuickReplyItem(
                            action=MessageAction(label="❌ キャンセル", text="キャンセル")
                        ),
                    ]
                ),
            )

        elif state == "confirm":
            if "確定" in text or "はい" in text or "OK" in text.upper():
                store = data.get("store", "ebisu")
                date_str = data.get("date")
                time_str = data.get("time")

                slot_datetime = f"{date_str}T{time_str}:00+09:00"

                # Save booking as provisional (仮予約)
                booking_id = await db.save_booking(
                    user_id, store, slot_datetime, "provisional"
                )

                # Clear session
                await db.clear_session(user_id)
                self._invalidate_cache()

                # Parse for display
                dt = datetime.fromisoformat(slot_datetime)
                display_date = dt.strftime("%m月%d日")
                wd = WEEKDAY_JP[dt.weekday()]
                hour = dt.hour
                time_range = f"{hour:02d}:00〜{hour + 1:02d}:00"

                success_msg = (
                    f"📩 仮予約を受け付けました！\n\n"
                    f"📅 {display_date}（{wd}）\n"
                    f"🕐 {time_range}\n"
                    f"📍 {STORE_NAMES[store]}\n"
                    f"🎫 受付No. {booking_id}\n\n"
                    f"⚠️ まだ予約は確定ではありません。\n\n"
                    f"管理者がhacomonoの空き状況を確認し、"
                    f"正式に予約を確定してからご連絡いたします。\n"
                    f"今しばらくお待ちください🙇‍♂️"
                )

                await self.reply_text(event_reply_token_unused := reply_token, success_msg)

                # Notify admin
                if settings.ADMIN_USER_ID:
                    display_name = user.get("display_name", "Unknown")
                    admin_msg = (
                        f"📢 新規・仮予約申請\n"
                        f"👤 {display_name}\n"
                        f"📅 {display_date}（{wd}）{time_range}\n"
                        f"📍 {STORE_NAMES[store]}\n"
                        f"🎫 No. {booking_id}\n\n"
                        f"⚠️ hacomonoで予約枠を確保し、\n"
                        f"ユーザーへ確定連絡をしてください！"
                    )
                    try:
                        await self.push_text(settings.ADMIN_USER_ID, admin_msg)
                    except Exception as e:
                        print(f"Admin notification failed: {e}")

            elif "変更" in text:
                data.pop("time", None)
                await db.set_session(
                    user_id, "booking", "select_date", json.dumps(data)
                )
                await self.reply_text(
                    reply_token,
                    "🔄 変更しますね。\n\n希望の日にちを教えてください📅\n例：「2/20」「明日」「来週水曜」",
                )

            elif "キャンセル" in text or "やめ" in text:
                await db.clear_session(user_id)
                await self.reply_text(reply_token, "予約をキャンセルしました。\nまたいつでもどうぞ！👋")

            else:
                await self.reply_text(
                    reply_token,
                    "「確定する」「変更する」「キャンセル」から選んでください👇",
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(
                                action=MessageAction(label="✅ 確定する", text="確定する")
                            ),
                            QuickReplyItem(
                                action=MessageAction(label="🔄 変更する", text="変更する")
                            ),
                            QuickReplyItem(
                                action=MessageAction(label="❌ キャンセル", text="キャンセル")
                            ),
                        ]
                    ),
                )

    # ============================================================
    # Show user bookings (Flex Message)
    # ============================================================
    async def _show_user_bookings(
        self, reply_token: str, user_id: str, user: dict
    ):
        """Show the user's upcoming bookings with cancel options."""
        # Get from local DB (Provisional/Confirmed)
        upcoming = await db.get_user_bookings(user_id, include_past=False)
        
        # Calendar bookings (Legacy/Manual)
        display_name = user.get("display_name", "")
        cal_bookings = []
        if display_name and display_name != "Unknown":
            bookings = await self._get_bookings()
            cal_bookings = find_user_bookings(display_name, bookings)
            # Filter future only
            now = datetime.now(JST)
            cal_bookings = [b for b in cal_bookings if b.start_dt > now]

        if not upcoming and not cal_bookings:
            await self.reply_text(
                reply_token,
                "📖 現在の予約はありません。\n\n「予約する」で新しい予約を入れましょう！📅",
            )
            return

        # Build Flex Message Bubble for each booking
        bubbles = []

        # 1. DB Bookings
        for b in upcoming:
            dt = datetime.fromisoformat(b["slot_datetime"])
            date_s = dt.strftime("%m/%d")
            wd = WEEKDAY_JP[dt.weekday()]
            time_s = dt.strftime("%H:%M")
            store_name = STORE_NAMES.get(b["store"], b["store"])
            status_text = "仮予約" if b.get("status") == "provisional" else "予約中"
            status_color = "#ff9f1c" if b.get("status") == "provisional" else "#2ec4b6"
            
            bubbles.append({
                "type": "bubble",
                "size": "mega",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": status_text,
                            "color": "#ffffff",
                            "weight": "bold",
                            "size": "xs",
                            "backgroundColor": status_color,
                            "paddingAll": "3px",
                            "cornerRadius": "sm",
                            "align": "start",
                            "flex": 0,
                            "offsetTop": "-5px"
                        },
                        {
                            "type": "text",
                            "text": f"{date_s} ({wd})",
                            "weight": "bold",
                            "size": "xl",
                            "color": "#1a1a2e",
                            "margin": "sm"
                        },
                        {
                            "type": "text",
                            "text": f"{time_s} 〜",
                            "size": "lg",
                            "color": "#1a1a2e",
                        }
                    ],
                    "backgroundColor": "#f8f9fa"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "baseline",
                            "contents": [
                                {"type": "text", "text": "📍", "flex": 1, "size": "sm"},
                                {"type": "text", "text": store_name, "flex": 8, "size": "sm", "weight": "bold"}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "baseline",
                            "margin": "md",
                            "contents": [
                                {"type": "text", "text": "🎫", "flex": 1, "size": "sm"},
                                {"type": "text", "text": f"No. {b['id']}", "flex": 8, "size": "xs", "color": "#aaaaaa"}
                            ]
                        }
                    ],
                    "paddingAll": "20px"
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "キャンセル申請",
                                "data": json.dumps({
                                    "action": "cancel_request",
                                    "booking_id": b["id"],
                                    "date": f"{date_s} {time_s}",
                                    "store": store_name
                                })
                            },
                            "style": "secondary",
                            "color": "#e63946",
                            "height": "sm"
                        }
                    ],
                    "paddingAll": "15px"
                }
            })

        # 2. Calendar Bookings (Cannot cancel automatically, show distinct)
        for b in cal_bookings:
            dt = b.start_dt
            date_s = dt.strftime("%m/%d")
            wd = WEEKDAY_JP[dt.weekday()]
            time_s = dt.strftime("%H:%M")
            store_name = STORE_NAMES.get(b.store, "")
            
            bubbles.append({
                "type": "bubble",
                "size": "mega",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "カレンダー同期",
                            "color": "#ffffff",
                            "weight": "bold",
                            "size": "xs",
                            "backgroundColor": "#cccccc",
                            "paddingAll": "3px",
                            "cornerRadius": "sm",
                            "align": "start",
                            "flex": 0,
                            "offsetTop": "-5px"
                        },
                        {
                            "type": "text",
                            "text": f"{date_s} ({wd})",
                            "weight": "bold",
                            "size": "xl",
                            "color": "#1a1a2e",
                            "margin": "sm"
                        },
                        {
                            "type": "text",
                            "text": f"{time_s} 〜",
                            "size": "lg",
                            "color": "#1a1a2e",
                        }
                    ],
                    "backgroundColor": "#f0f0f0"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "baseline",
                            "contents": [
                                {"type": "text", "text": "📍", "flex": 1, "size": "sm"},
                                {"type": "text", "text": store_name, "flex": 8, "size": "sm", "weight": "bold"}
                            ]
                        }
                    ],
                    "paddingAll": "20px"
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                         {
                            "type": "text",
                            "text": "※変更は直接ご連絡ください",
                            "size": "xs",
                            "color": "#aaaaaa",
                            "align": "center"
                        }
                    ],
                    "paddingAll": "15px"
                }
            })

        # Create Carousel
        carousel = {
            "type": "carousel",
            "contents": bubbles
        }

        await self.reply_flex(reply_token, "あなたの予約一覧", carousel)

    # ============================================================
    # Hayamihyo link
    # ============================================================
    async def _show_hayamihyo_link(self, reply_token: str):
        """Show link to the booking web page (早見表)."""
        flex = {
            "type": "bubble",
            "size": "kilo",
            "hero": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "📋 石原早見表",
                        "weight": "bold",
                        "size": "xl",
                        "color": "#1a1a2e",
                        "align": "center",
                    },
                    {
                        "type": "text",
                        "text": "予約状況をWebで確認",
                        "size": "sm",
                        "color": "#666666",
                        "align": "center",
                        "margin": "sm",
                    },
                ],
                "paddingAll": "20px",
                "backgroundColor": "#f0f4ff",
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "恵比寿店・半蔵門店の空き状況を\nカレンダー形式で確認できます。",
                        "wrap": True,
                        "size": "sm",
                        "color": "#444444",
                    },
                ],
                "paddingAll": "15px",
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "早見表を開く 🔗",
                            "uri": settings.HAYAMIHYO_URL,
                        },
                        "style": "primary",
                        "color": "#1a1a2e",
                    },
                ],
                "paddingAll": "15px",
            },
        }

        await self.reply_flex(reply_token, "石原早見表", flex)

    # ============================================================
    # Availability Flex Message builder
    # ============================================================
    def _build_availability_flex(
        self,
        target_date: datetime,
        ebisu_slots: list[datetime],
        hanzomon_slots: list[datetime],
    ) -> dict:
        """Build a Flex Message showing available slots for both stores."""
        date_str = target_date.strftime("%m月%d日")
        wd = WEEKDAY_JP[target_date.weekday()]

        contents = []

        # Header
        contents.append(
            {
                "type": "text",
                "text": f"📅 {date_str}（{wd}）空き状況",
                "weight": "bold",
                "size": "lg",
                "color": "#1a1a2e",
            }
        )
        contents.append({"type": "separator", "margin": "md"})

        # Ebisu slots
        if ebisu_slots:
            contents.append(
                {
                    "type": "text",
                    "text": "📍 恵比寿店",
                    "weight": "bold",
                    "size": "md",
                    "margin": "lg",
                    "color": "#16213e",
                }
            )
            slot_texts = []
            for slot in ebisu_slots:
                time_str = slot.strftime("%H:%M")
                end_str = (slot + timedelta(hours=1)).strftime("%H:%M")
                slot_texts.append(f"✅ {time_str}〜{end_str}")
            contents.append(
                {
                    "type": "text",
                    "text": "\n".join(slot_texts),
                    "size": "sm",
                    "color": "#2d6a4f",
                    "wrap": True,
                    "margin": "sm",
                }
            )

        # Hanzoomon slots
        if hanzomon_slots:
            contents.append(
                {
                    "type": "text",
                    "text": "📍 半蔵門店",
                    "weight": "bold",
                    "size": "md",
                    "margin": "lg",
                    "color": "#16213e",
                }
            )
            slot_texts = []
            for slot in hanzomon_slots:
                time_str = slot.strftime("%H:%M")
                end_str = (slot + timedelta(hours=1)).strftime("%H:%M")
                slot_texts.append(f"✅ {time_str}〜{end_str}")
            contents.append(
                {
                    "type": "text",
                    "text": "\n".join(slot_texts),
                    "size": "sm",
                    "color": "#2d6a4f",
                    "wrap": True,
                    "margin": "sm",
                }
            )

        contents.append({"type": "separator", "margin": "lg"})
        contents.append(
            {
                "type": "text",
                "text": "💡 予約するには「予約する」と入力！",
                "size": "xs",
                "color": "#888888",
                "margin": "md",
            }
        )

        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": contents,
                "paddingAll": "20px",
            },
        }

    # ============================================================
    # Default message
    # ============================================================
    async def _handle_default(self, reply_token: str):
        """Handle unrecognized messages."""
        quick_reply = QuickReply(
            items=[
                QuickReplyItem(
                    action=MessageAction(label="📅 予約する", text="予約する")
                ),
                QuickReplyItem(
                    action=MessageAction(label="📖 予約確認", text="予約確認")
                ),
                QuickReplyItem(
                    action=MessageAction(label="📋 早見表", text="早見表")
                ),
            ]
        )

        await self.reply_text(
            reply_token,
            "TOPFORM予約Botです！💪\n\n以下からお選びください👇\n\n"
            "📅 予約する → 新しい予約\n"
            "📖 予約確認 → あなたの予約一覧\n"
            "📋 早見表 → Web版スケジュール\n\n"
            "💡 日にちを送ると空き状況も確認できます\n"
            "例：「2/20空いてる？」「明日空き」",
            quick_reply=quick_reply,
        )


# Singleton instance
line_service = LINEService()
