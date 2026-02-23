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
        self._cache_ttl = timedelta(minutes=5)  # 5分キャッシュ

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

    async def push_text(self, to_user_id: str, text: str):
        """Send a push text message to a user."""
        message = TextMessage(text=text)
        from linebot.v3.messaging import PushMessageRequest
        
        await self._api.push_message(
            PushMessageRequest(to=to_user_id, messages=[message])
        )

    # ============================================================
    # Postback handler
    # ============================================================
    def _build_confirm_flex(self, title, message, ok_label, ok_data, ok_color):
        """Build a confirmation Flex Message"""
        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": title,
                        "weight": "bold",
                        "color": "#ff0000",
                        "size": "md"
                    },
                    {
                        "type": "text",
                        "text": message,
                        "wrap": True,
                        "size": "sm",
                        "margin": "md"
                    }
                ],
                "paddingAll": "20px"
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "はい",
                            "data": ok_data,
                            "displayText": ok_label
                        },
                        "style": "primary",
                        "color": ok_color
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "message",
                            "label": "いいえ",
                            "text": "操作をやめる"
                        },
                        "style": "secondary"
                    }
                ],
                "paddingAll": "20px"
            }
        }

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

        # --- 共通処理: 残り時間計算用関数 ---
        def get_hours_remaining(booking_dt_iso: str) -> float:
            if not booking_dt_iso:
                return 999.0
            try:
                booking_dt = datetime.fromisoformat(booking_dt_iso)
                if booking_dt.tzinfo is None:
                    booking_dt = JST.localize(booking_dt)
                
                now = datetime.now(JST)
                diff = booking_dt - now
                return diff.total_seconds() / 3600.0
            except Exception:
                return 999.0

        # --- Action Handlers ---

        if action == "force_cancel_confirm" or action == "ticket_consume_confirm":
            # 最終確認「はい」が押された場合
            # force_cancel_confirm: 3時間未満（直前キャンセル・管理者通知）
            # ticket_consume_confirm: 12時間未満（1回消化キャンセル）
            
            booking_id = data.get("booking_id")
            booking_date = data.get("date")
            store_name = data.get("store")
            old_dt_iso = data.get("dt_iso") 

            # Cancel in DB
            success = await db.cancel_booking(booking_id, user_id)
            
            if success:
                # Notify User
                msg_user = ""
                if action == "force_cancel_confirm":
                    msg_user = (
                        f"承知いたしました。\n"
                        f"直前キャンセルの旨、担当（石原）に通知いたしました。\n"
                        f"またのご予約をお待ちしております。"
                    )
                else:
                     msg_user = (
                        f"✅ 予約のキャンセル申請を受け付けました。\n"
                        f"（規定により1回分消化扱いとなります）\n\n"
                        f"📅 {booking_date}\n"
                        f"📍 {store_name}\n\n"
                        f"またのご予約をお待ちしております！👋"
                    )
                
                await self.reply_text(reply_token, msg_user)
                
                # Notify Admin
                if settings.ADMIN_USER_ID:
                    display_name = user.get("display_name", "Unknown")
                    admin_msg = ""
                    
                    if action == "force_cancel_confirm":
                         admin_msg = (
                            f"🚨 直前キャンセル連絡\n"
                            f"From: {display_name} 様\n"
                            f"予約: {booking_date}\n"
                            f"店舗: {store_name}\n"
                            f"------------------\n"
                            f"※{settings.URGENT_CONTACT_DEADLINE_HOURS}時間以内の操作のため、\n"
                            f"キャンセル扱いとして通知されました。"
                        )
                    else:
                        admin_msg = (
                            f"🎫 1回消化キャンセル\n"
                            f"From: {display_name} 様\n"
                            f"予約: {booking_date}\n"
                            f"店舗: {store_name}\n"
                            f"------------------\n"
                            f"※{settings.BOOKING_DEADLINE_HOURS}時間以内のキャンセルのため、\n"
                            f"チケット1回分消化扱いとなります。"
                        )

                    try:
                        await self.push_text(settings.ADMIN_USER_ID, admin_msg)
                    except Exception as e:
                        print(f"Admin notification failed: {e}")
                
                self._invalidate_cache()
            else:
                await self.reply_text(
                    reply_token,
                    "⚠️ エラーが発生しました。すでにキャンセルされている可能性があります。"
                )


        elif action == "cancel_request":
            booking_id = data.get("booking_id")
            booking_date = data.get("date") 
            store_name = data.get("store")
            booking_dt_iso = data.get("dt_iso") 

            hours_remain = get_hours_remaining(booking_dt_iso)

            # Case A: 3時間未満 (直前キャンセル)
            if hours_remain < settings.URGENT_CONTACT_DEADLINE_HOURS:
                confirm_data = json.dumps({
                    "action": "force_cancel_confirm",
                    "booking_id": booking_id,
                    "date": booking_date,
                    "store": store_name,
                    "dt_iso": booking_dt_iso
                })
                
                msg = (
                    f"⚠️ 予約時間の{settings.URGENT_CONTACT_DEADLINE_HOURS}時間を切っています。\n\n"
                    f"これ以降の変更はキャンセル扱いとなります。\n"
                    f"その旨、担当（石原）に通知しますがよろしいでしょうか？"
                )
                
                flex = self._build_confirm_flex(
                    "⚠️ 直前キャンセルの確認", 
                    msg, 
                    "はい、連絡する", 
                    confirm_data,
                    "#cc0000"
                )
                await self.reply_flex(reply_token, "直前キャンセルの確認", flex)
                return

            # Case B: 12時間未満 (チケット消化)
            elif hours_remain < settings.BOOKING_DEADLINE_HOURS:
                confirm_data = json.dumps({
                    "action": "ticket_consume_confirm",
                    "booking_id": booking_id,
                    "date": booking_date,
                    "store": store_name,
                    "dt_iso": booking_dt_iso
                })
                
                msg = (
                    f"大変心苦しいのですが、予約時間の{settings.BOOKING_DEADLINE_HOURS}時間を切っておりますため、\n"
                    f"今回のキャンセルは規定により\n"
                    f"**【チケット1回分の消化】** となってしまいます🥺\n\n"
                    f"それでもよろしいでしょうか？\n"
                    f"（よろしければキャンセル手続きを進めます）"
                )

                flex = self._build_confirm_flex(
                    "⚠️ チケット消化の確認", 
                    msg, 
                    "はい、キャンセルする", 
                    confirm_data,
                    "#FF9800" # Orange
                )
                await self.reply_flex(reply_token, "チケット消化の確認", flex)
                return

            # Case C: 12時間以上 (通常キャンセル)
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
                        f"🎫 No. {booking_id}\n"
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
                

        if action == "change_list_more":
            offset = data.get("offset", 0)
            await self._show_booking_change_list(reply_token, user_id, user, offset)

        if action == "select_change_booking":
            # 予約変更ボタンが押されたとき
            booking_id = data.get("booking_id")
            b_type = data.get("type")
            original_dt_iso = data.get("dt") # ISO format
            original_store = data.get("store")
            
            hours_remain = get_hours_remaining(original_dt_iso)
            
            # Case A: 3時間未満
            if hours_remain < settings.URGENT_CONTACT_DEADLINE_HOURS:
                # Format date for display
                dt_display = original_dt_iso
                try:
                    dt_obj = datetime.fromisoformat(original_dt_iso)
                    dt_display = dt_obj.strftime('%m/%d %H:%M')
                except: pass

                confirm_data = json.dumps({
                    "action": "force_cancel_confirm",
                    "booking_id": booking_id,
                    "date": dt_display,
                    "store": original_store,
                    "dt_iso": original_dt_iso
                })

                msg = (
                    f"⚠️ 予約時間の{settings.URGENT_CONTACT_DEADLINE_HOURS}時間を切っているため、日時の変更はできません。\n\n"
                    f"このまま手続きを進めると「キャンセル扱い」となります。\n"
                    f"その旨、担当（石原）に通知しますがよろしいでしょうか？"
                )
                
                flex = self._build_confirm_flex(
                    "⚠️ 変更不可・キャンセル確認", 
                    msg, 
                    "はい、連絡する", 
                    confirm_data,
                    "#cc0000"
                )
                await self.reply_flex(reply_token, "直前キャンセルの確認", flex)
                return

            # Case B: 12時間未満 (変更でも1回消化になるのか？ → 変更なら消化しない？それとも変更もキャンセル＆新規？)
            # 一般的に「変更」はキャンセル料かからないケースが多いですが、
            # 12時間切ってからの変更を許すと、キャンセル逃れに使われる可能性があります。
            # ここでは「12時間切ったら変更も不可（キャンセル扱い）」とするのが安全です。
            
            elif hours_remain < settings.BOOKING_DEADLINE_HOURS:
                # Format date for display
                dt_display = original_dt_iso
                try:
                    dt_obj = datetime.fromisoformat(original_dt_iso)
                    dt_display = dt_obj.strftime('%m/%d %H:%M')
                except: pass

                confirm_data = json.dumps({
                    "action": "ticket_consume_confirm",
                    "booking_id": booking_id,
                    "date": dt_display,
                    "store": original_store,
                    "dt_iso": original_dt_iso
                })

                msg = (
                    f"⚠️ 予約時間の{settings.BOOKING_DEADLINE_HOURS}時間を切っているため、予約変更はできません。\n\n"
                    f"一度キャンセル（1回分消化）してから取り直す形になりますが、よろしいでしょうか？"
                )
                
                flex = self._build_confirm_flex(
                    "⚠️ 変更不可・チケット消化", 
                    msg, 
                    "はい、キャンセルする", 
                    confirm_data,
                    "#FF9800"
                )
                await self.reply_flex(reply_token, "チケット消化の確認", flex)
                return

            # Normal Change Flow
            original_dt = data.get("dt")
            
            # Format original date/time for display
            dt_display = ""
            if original_dt:
                try:
                    dt_obj = datetime.fromisoformat(original_dt)
                    wd = WEEKDAY_JP[dt_obj.weekday()]
                    dt_display = f"{dt_obj.strftime('%m/%d')}（{wd}） {dt_obj.strftime('%H:%M')}"
                except:
                    dt_display = original_dt

            session_data = {
                "mode": "change",
                "target_booking_id": booking_id,
                "target_booking_type": b_type,
                # Carry over user preferences
                "room_pref": user.get("room_pref"),
                "original_booking_info": {
                    "dt": original_dt,
                    "store": original_store
                }
            }
            
            await db.set_session(user_id, "booking", "select_store", json.dumps(session_data))
            
            # Store selection QuickReply
            quick_reply = QuickReply(
                items=[
                    QuickReplyItem(
                        action=MessageAction(label="恵比寿", text="恵比寿")
                    ),
                    QuickReplyItem(
                        action=MessageAction(label="半蔵門", text="半蔵門")
                    ),
                    QuickReplyItem(
                        action=MessageAction(label="両店舗", text="両店舗")
                    ),
                ]
            )
            
            # Create messages
            messages = []
            
            # 1. Confirmation Message
            confirm_text = "承知しました。以下の予約を変更しますね。\n"
            if dt_display:
                confirm_text += f"\n📅 {dt_display}"
                if original_store:
                    confirm_text += f"\n ・{original_store}"
                
                confirm_text += "\n\n↓↓↓↓↓"
            
            # 2. Prompt for new store (or same store)
            prompt_text = "変更後の店舗を選んでください！\n（日時だけ変更する場合も、店舗を選んでください）"
            messages.append(TextMessage(text=prompt_text, quick_reply=quick_reply))
            
            await self.reply_messages(reply_token, messages)

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

        # Priority Commands (Always available)
        if text.lower() in ["id", "id確認", "user_id", "admin_id"]:
            await self.reply_text(reply_token, f"あなたのUser ID:\n{user_id}")
            print(f"🆔 User ID: {user_id}")
            return

        if text == "キャンセル" or text == "やめる":
            await db.clear_session(user_id)
            await self.reply_text(reply_token, "操作をキャンセルしました。")
            return

        # Check for active session
        session = await db.get_session(user_id)

        # ---- Rich Menu / Command triggers ----
        if "予約確認" in text or "予約一覧" in text or "マイ予約" in text:
            await self._show_user_bookings_simple(reply_token, user_id, user)
            return

        if "早見表" in text or "スケジュール" in text or "空き状況" in text:
            await self._show_hayamihyo_link(reply_token)
            return

        if "予約変更" in text:
            await db.clear_session(user_id)  # Clear any active session first
            await self._show_booking_change_list(reply_token, user_id, user)
            return

        if "予約" in text or "booking" in text.lower():
            force_select = "店舗変更" in text or "変更" in text
            await self._start_booking_flow(reply_token, user_id, user, force_store_select=force_select)
            return
            
        # (Old ID check removed from here)

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
            f"【 WELCOME 】\n"
            f"{display_name}様、友だち追加ありがとうございます。\n\n"
            f"TOPFORM 予約Bot\n"
            f"(担当: 石原)\n\n"
            f"※ Botでの予約は「仮予約」です。\n"
            f"スタッフが確認後、確定メッセージをお送りします。\n\n"
            f"以下よりメニューをお選びください。"
        )
        await self.reply_text(event.reply_token, welcome)

    # ============================================================
    # Date query parsing
    # ============================================================
    def _parse_multiple_dates(self, text: str) -> list[datetime]:
        """
        Parse natural language text for multiple dates.
        Examples:
          「2/20, 2/21空いてる？」「2日と23日」「3月の土曜日」「3月」
        """
        found_dates = []
        now = datetime.now(JST)
        import calendar

        # 0. Detect explicit Month context (e.g. "3月")
        target_month_context = None
        target_year_context = now.year
        
        m_month = re.search(r"(\d{1,2})月", text)
        if m_month:
            try:
                m_val = int(m_month.group(1))
                if 1 <= m_val <= 12:
                    target_month_context = m_val
                    if target_month_context < now.month:
                        target_year_context += 1
            except:
                pass

        # 1. Keywords
        if "今日" in text: found_dates.append(now)
        if "明日" in text: found_dates.append(now + timedelta(days=1))
        if "明後日" in text or "あさって" in text: found_dates.append(now + timedelta(days=2))

        # 2. Weekdays
        weekday_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
        
        # If month context exists, search for "X曜" in that month
        if target_month_context:
            detected_wds = []
            for wd_char, wd_idx in weekday_map.items():
                if f"{wd_char}曜" in text:
                    detected_wds.append(wd_idx)
            
            if detected_wds:
                _, last_day = calendar.monthrange(target_year_context, target_month_context)
                for day in range(1, last_day + 1):
                    dt = JST.localize(datetime(target_year_context, target_month_context, day))
                    if dt.date() >= now.date() and dt.weekday() in detected_wds:
                        found_dates.append(dt)

        # "来週X曜" (Relative)
        for m in re.finditer(r"来週\s*([月火水木金土日])", text):
            target_wd = weekday_map[m.group(1)]
            days_ahead = (7 - now.weekday() + target_wd) % 7
            if days_ahead == 0: days_ahead = 7
            days_ahead += 7
            found_dates.append(now + timedelta(days=days_ahead))

        # "[今週]X曜" - Only if NO month context
        if not target_month_context:
            text_no_next = re.sub(r"来週\s*[月火水木金土日]", "", text)
            for m in re.finditer(r"(?:今週\s*)?([月火水木金土日])曜", text_no_next):
                target_wd = weekday_map[m.group(1)]
                days_ahead = (target_wd - now.weekday()) % 7
                if days_ahead == 0: days_ahead = 7
                found_dates.append(now + timedelta(days=days_ahead))

        # 3. M/D pattern
        for m in re.finditer(r"(\d{1,2})[/月](\d{1,2})", text):
            try:
                month = int(m.group(1))
                day = int(m.group(2))
                year = now.year
                target = JST.localize(datetime(year, month, day))
                if target.date() < now.date():
                    target = target.replace(year=year + 1)
                found_dates.append(target)
            except:
                pass

        # 4. D日 pattern
        text_temp = re.sub(r"\d{1,2}[/月]\d{1,2}", "", text)
        for m in re.finditer(r"(\d{1,2})日", text_temp):
            try:
                day = int(m.group(1))
                year = now.year
                month = now.month
                target = JST.localize(datetime(year, month, day))
                if target.date() < now.date():
                    month += 1
                    if month > 12: month = 1; year += 1
                    target = JST.localize(datetime(year, month, day))
                found_dates.append(target)
            except:
                pass
        
        # 5. Month only fallback
        if target_month_context and not found_dates:
            _, last_day = calendar.monthrange(target_year_context, target_month_context)
            for day in range(1, last_day + 1):
                dt = JST.localize(datetime(target_year_context, target_month_context, day))
                if dt.date() >= now.date():
                    found_dates.append(dt)

        # Sort and unique
        unique_map = {}
        for d in found_dates:
            unique_map[d.date()] = d
        
        return sorted(list(unique_map.values()))

    async def _process_select_date(self, reply_token, user_id, session, text, data):
        """Handle date selection logic, supporting multiple dates."""
        target_dates = self._parse_multiple_dates(text)
        
        if not target_dates:
            await self.reply_text(
                reply_token,
                """日時が正しくありません。
もう一度入力してください
(例: 2.20, 明日, 土曜)""",
            )
            return

        store = data.get("store", "ebisu")
        bookings = await self._get_bookings()
        
        # --- Suggestion Logic ---
        # If multiple dates found, save them as suggestions
        if len(target_dates) > 1:
            data["suggested_dates"] = [d.strftime("%Y-%m-%d") for d in target_dates]
        
        # If single date found, remove it from suggestions if exists
        if len(target_dates) == 1:
            td_str = target_dates[0].strftime("%Y-%m-%d")
            sug = data.get("suggested_dates", [])
            if td_str in sug:
                sug.remove(td_str)
                data["suggested_dates"] = sug
        # ------------------------

        # ========== BOTH STORES MODE ==========
        if store == "both":
            if len(target_dates) == 1:
                target_date = target_dates[0]
                date_str = target_date.strftime("%m/%d")
                wd = WEEKDAY_JP[target_date.weekday()]

                ebisu_slots = get_available_slots(target_date, "ebisu", bookings)
                hanzomon_slots = get_available_slots(target_date, "hanzoomon", bookings)

                if not ebisu_slots and not hanzomon_slots:
                    await self.reply_text(
                        reply_token,
                        f"😔 {date_str}（{wd}）は両店舗とも空きがありません。\n\n別の日時を入力してください📅",
                    )
                    return

                # Build combined display
                msg_parts = [f"📅 {date_str}（{wd}）の空き状況\n"]

                if ebisu_slots:
                    e_list = "\n".join([f"  🕐 {s.strftime('%H:%M')}" for s in ebisu_slots])
                    msg_parts.append(f"🏢 恵比寿店\n{e_list}")
                else:
                    msg_parts.append("🏢 恵比寿店: 満席 🈵")

                if hanzomon_slots:
                    h_list = "\n".join([f"  🕐 {s.strftime('%H:%M')}" for s in hanzomon_slots])
                    msg_parts.append(f"🏯 半蔵門店\n{h_list}")
                else:
                    msg_parts.append("🏯 半蔵門店: 満席 🈵")

                msg_parts.append("どちらの店舗で予約しますか？👇")

                data["date"] = target_date.strftime("%Y-%m-%d")
                await db.set_session(
                    user_id, "booking", "select_store_after_date", json.dumps(data)
                )

                # QuickReply to pick store
                qr_items = []
                if ebisu_slots:
                    qr_items.append(QuickReplyItem(action=MessageAction(label="恵比寿で予約", text="恵比寿で予約")))
                if hanzomon_slots:
                    qr_items.append(QuickReplyItem(action=MessageAction(label="半蔵門で予約", text="半蔵門で予約")))

                await self.reply_text(
                    reply_token,
                    "\n\n".join(msg_parts),
                    quick_reply=QuickReply(items=qr_items) if qr_items else None,
                )
                return

            # Multiple dates + both stores
            msg_lines = []
            for td in target_dates:
                d_str = td.strftime("%m/%d")
                wd = WEEKDAY_JP[td.weekday()]
                e_slots = get_available_slots(td, "ebisu", bookings)
                h_slots = get_available_slots(td, "hanzoomon", bookings)

                e_count = len(e_slots)
                h_count = len(h_slots)

                if e_count == 0 and h_count == 0:
                    msg_lines.append(f"📅 {d_str}（{wd}）: 両店舗満席 🈵")
                else:
                    e_info = f"恵比寿{e_count}枠" if e_count > 0 else "恵比寿✕"
                    h_info = f"半蔵門{h_count}枠" if h_count > 0 else "半蔵門✕"
                    msg_lines.append(f"📅 {d_str}（{wd}）: {e_info} / {h_info}")

            if not msg_lines:
                msg_lines.append("ご希望の日程に空きは見つかりませんでした🙇‍♂️")

            final_msg = "\n".join(msg_lines)
            if len(final_msg) > 1000:
                final_msg = final_msg[:1000] + "\n..."

            await self.reply_text(
                reply_token,
                f"""■ 両店舗の空き状況

{final_msg}

ご希望の日時（1日）を指定してください！"""
            )
            await db.set_session(user_id, "booking", "select_date", json.dumps(data))
            return
        # ========== END BOTH STORES MODE ==========

        # If single date found
        if len(target_dates) == 1:
            target_date = target_dates[0]
            slots = get_available_slots(target_date, store, bookings)

            date_str = target_date.strftime("%m/%d")
            wd = WEEKDAY_JP[target_date.weekday()]
            store_name = STORE_NAMES.get(store, store)

            if not slots:
                await self.reply_text(
                    reply_token,
                    f"""😔 {date_str}（{wd}）は{store_name}の空きがありません。

別の日時を入力してください📅""",
                )
                return

            # --- One-shot DateTime Check (案1: 日時一発指定) ---
            # Check if time is also provided in text (e.g. "10:00")
            m_time = re.search(r"(\d{1,2})[:：](\d{2})", text)
            if m_time:
                hour = int(m_time.group(1))
                minute = int(m_time.group(2))
                
                # Check availability for this specific time
                is_available = False
                for s in slots:
                    if s.hour == hour and s.minute == minute:
                        is_available = True
                        break
                
                if is_available:
                    # Move state to select_time, effectively pre-selecting date
                    data["date"] = target_date.strftime("%Y-%m-%d")
                    await db.set_session(
                        user_id, "booking", "select_time", json.dumps(data)
                    )
                    
                    # Confirm with user
                    time_str = f"{hour:02d}:{minute:02d}"
                    confirm_text = (
                        f"📅 {date_str}（{wd}） {time_str}\n"
                        f"📍 {store_name}\n\n"
                        f"こちらの内容で予約手続きを進めますか？"
                    )
                    
                    # Button sends the time string back, triggering select_time logic
                    yes_action = MessageAction(label="はい、予約する", text=time_str)
                    
                    # "Show other times" button sends the DATE string back, triggering select_date logic (fallback in select_time)
                    other_action = MessageAction(label="他の時間を見る", text=date_str)

                    await self.reply_text(
                        reply_token,
                        confirm_text,
                        quick_reply=QuickReply(items=[
                            QuickReplyItem(action=yes_action),
                            QuickReplyItem(action=other_action)
                        ])
                    )
                    return
            # -------------------------------------

            data["date"] = target_date.strftime("%Y-%m-%d")
            await db.set_session(
                user_id, "booking", "select_time", json.dumps(data)
            )

            # Build quick reply with time slots
            items = []
            for slot in slots[:13]:
                time_str = slot.strftime("%H:%M")
                items.append(
                    QuickReplyItem(
                        action=MessageAction(label=f"{time_str}", text=time_str)
                    )
                )

            slot_list = "\n".join(
                [f"🕐 {s.strftime('%H:%M')} - {(s + timedelta(hours=1)).strftime('%H:%M')}" for s in slots]
            )

            await self.reply_text(
                reply_token,
                f"""📅 {date_str}（{wd}） {store_name}

{slot_list}

こちらはいかがでしょうか？
時間を選択してください👇""",
                quick_reply=QuickReply(items=items),
            )
            return

        # Multiple dates found: Show availability for all
        msg_lines = []
        store_name = STORE_NAMES.get(store, store)
        
        # --- Time Filter Logic (案2: 時間帯検索) ---
        filter_start_hour = None
        filter_end_hour = None
        filter_note = ""
        
        if "午前" in text or "朝" in text:
            filter_end_hour = 12
            filter_note = "（午前中）"
        elif "午後" in text:
            filter_start_hour = 12
            filter_note = "（午後）"
        elif "夜" in text or "夕方" in text:
            filter_start_hour = 17
            filter_note = "（17時以降）"
            
        m_after = re.search(r"(\d{1,2})時以降", text)
        if m_after:
            filter_start_hour = int(m_after.group(1))
            filter_note = f"（{filter_start_hour}時以降）"

        for td in target_dates:
            open_slots = get_available_slots(td, store, bookings)
            
            # Apply Filter
            filtered_slots = open_slots
            if filter_start_hour is not None:
                filtered_slots = [s for s in filtered_slots if s.hour >= filter_start_hour]
            if filter_end_hour is not None:
                filtered_slots = [s for s in filtered_slots if s.hour < filter_end_hour]

            d_str = td.strftime("%m/%d")
            wd = WEEKDAY_JP[td.weekday()]
            
            if filtered_slots:
                slot_strs = [s.strftime("%H:%M") for s in filtered_slots]
                if len(slot_strs) > 6:
                    slot_strs = slot_strs[:6] + ["..."]
                msg_lines.append(f"📅 {d_str}（{wd}）\n" + "  " + ", ".join(slot_strs))
            else:
                # If filtered out completely, don't shown
                # only show if NO filter was applied and it was full
                if not (filter_start_hour or filter_end_hour):
                    msg_lines.append(f"📅 {d_str}（{wd}）: 満席 🈵")
        
        if not msg_lines:
             if filter_start_hour or filter_end_hour:
                 msg_lines.append("ご希望の時間帯に空きは見つかりませんでした🙇‍♂️")
             else:
                 msg_lines.append("ご希望の日程に空きは見つかりませんでした🙇‍♂️")

        final_msg = "\n\n".join(msg_lines)
        if len(final_msg) > 1000:
            final_msg = final_msg[:1000] + "\n..."
            
        await self.reply_text(
             reply_token,
             f"""■ {store_name} の空き状況 {filter_note}

{final_msg}

ご希望の日時（1日）を指定してください！"""
        )
        # Ensure session is in select_date
        bookings_data = bookings # keep reference if needed
        await db.set_session(user_id, "booking", "select_date", json.dumps(data))    # ============================================================
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
    async def _start_booking_flow(self, reply_token: str, user_id: str, user: dict, force_store_select: bool = False):
        """Start the interactive booking flow."""
        # Pre-fill data with user preferences
        initial_data = {}
        store_pref = user.get("store_pref")
        
        # Check if we can skip store selection
        if store_pref and not force_store_select:
             store_code = "ebisu" if "恵比寿" in store_pref else "hanzomon"
             initial_data["store"] = store_code
             if user.get("room_pref"):
                 initial_data["room_pref"] = user.get("room_pref")
             
             # Skip to date selection
             await db.set_session(
                 user_id, "booking", "select_date", json.dumps(initial_data)
             )
             
             store_display = "恵比寿店" if store_code == "ebisu" else "半蔵門店"
             
             await self.reply_text(
                reply_token,
                f"""いつもの {store_display} ですね！🏢
ご希望の日時を入力してください📅
(例: 2/20, 明日, 来週の土曜)

※店舗を変更したい場合は「店舗変更」と入力してください。""",
                quick_reply=QuickReply(items=[
                    QuickReplyItem(action=MessageAction(label="店舗を変更する", text="予約 店舗変更"))
                ])
             )
             return

        # Normal Flow: Select Store
        if user.get("room_pref"):
            initial_data["room_pref"] = user["room_pref"]

        await db.set_session(
            user_id, "booking", "select_store", json.dumps(initial_data)
        )

        quick_reply = QuickReply(
            items=[
                QuickReplyItem(
                    action=MessageAction(label="恵比寿", text="恵比寿店")
                ),
                QuickReplyItem(
                    action=MessageAction(label="半蔵門", text="半蔵門店")
                ),
                QuickReplyItem(
                    action=MessageAction(label="両店舗", text="両店舗")
                ),
            ]
        )

        await self.reply_text(
            reply_token,
            "店舗を選択してください",
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
            if "両店舗" in text:
                store = "both"
            elif "恵比寿" in text:
                store = "ebisu"
            elif "半蔵門" in text:
                store = "hanzoomon"

            if not store:
                await self.reply_text(
                    reply_token,
                    "店舗を選択してください",
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(
                                action=MessageAction(
                                    label="恵比寿", text="恵比寿店"
                                )
                            ),
                            QuickReplyItem(
                                action=MessageAction(
                                    label="半蔵門", text="半蔵門店"
                                )
                            ),
                            QuickReplyItem(
                                action=MessageAction(
                                    label="両店舗", text="両店舗"
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

            if store == "both":
                await self.reply_text(
                    reply_token,
                    "■ 両店舗（恵比寿 & 半蔵門）\n\n希望日時を入力してください\n(例: 2.20, 明日, 土曜)\n\n両店舗の空き状況を同時にお見せします！",
                )
            else:
                store_name = STORE_NAMES.get(store, store)
                await self.reply_text(
                    reply_token,
                    f"■ {store_name}\n\n希望日時を入力してください\n(例: 2.20, 明日, 土曜)",
                )

        elif state == "select_store_after_date":
            # User selected a store after viewing both stores' availability
            store = None
            if "恵比寿" in text:
                store = "ebisu"
            elif "半蔵門" in text:
                store = "hanzoomon"

            if not store:
                await self.reply_text(
                    reply_token,
                    "店舗を選んでください👇",
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(action=MessageAction(label="恵比寿で予約", text="恵比寿で予約")),
                            QuickReplyItem(action=MessageAction(label="半蔵門で予約", text="半蔵門で予約")),
                        ]
                    ),
                )
                return

            data["store"] = store
            date_str = data.get("date")

            if not date_str:
                # Fallback: go to date selection
                await db.set_session(user_id, "booking", "select_date", json.dumps(data))
                store_name = STORE_NAMES.get(store, store)
                await self.reply_text(
                    reply_token,
                    f"■ {store_name}\n\n希望日時を入力してください\n(例: 2.20, 明日, 土曜)",
                )
                return

            # We have a date already, show time slots for the chosen store
            target_date = datetime.strptime(date_str, "%Y-%m-%d")
            bookings = await self._get_bookings()
            slots = get_available_slots(target_date, store, bookings)

            d_str = target_date.strftime("%m/%d")
            wd = WEEKDAY_JP[target_date.weekday()]
            store_name = STORE_NAMES.get(store, store)

            if not slots:
                await self.reply_text(
                    reply_token,
                    f"😔 {d_str}（{wd}）は{store_name}の空きがありません。\n\n別の日時を入力してください📅",
                )
                await db.set_session(user_id, "booking", "select_date", json.dumps(data))
                return

            await db.set_session(
                user_id, "booking", "select_time", json.dumps(data)
            )

            items = []
            for slot in slots[:13]:
                time_str = slot.strftime("%H:%M")
                items.append(
                    QuickReplyItem(
                        action=MessageAction(label=f"{time_str}", text=time_str)
                    )
                )

            slot_list = "\n".join(
                [f"🕐 {s.strftime('%H:%M')} - {(s + timedelta(hours=1)).strftime('%H:%M')}" for s in slots]
            )

            await self.reply_text(
                reply_token,
                f"""📅 {d_str}（{wd}） {store_name}

{slot_list}

時間を選択してください👇""",
                quick_reply=QuickReply(items=items),
            )

        elif state == "select_date":
            await self._process_select_date(reply_token, user_id, session, text, data)

        elif state == "select_time":
            m = re.match(r"(\d{1,2}):(\d{2})", text)
            if not m:
                # Fallback: check if it matches a date
                dates = self._parse_multiple_dates(text)
                if dates:
                    await self._process_select_date(reply_token, user_id, session, text, data)
                    return

                await self.reply_text(
                    reply_token,
                    "時間の形式が正しくありません。\n例: 10:00\n\n別の日時なら「2/20」のように入力してね！",
                )
                return

            hour = int(m.group(1))
            minute = int(m.group(2))
            date_str = data.get("date")
            store = data.get("store", "ebisu")
            room_pref = data.get("room_pref")

            target_date = datetime.strptime(date_str, "%Y-%m-%d")
            slot_time = JST.localize(
                target_date.replace(hour=hour, minute=minute, second=0)
            )

            bookings = await self._get_bookings()
            result = check_availability(slot_time, store, bookings)

            if not result["is_available"]:
                self._invalidate_cache()
                await self.reply_text(
                    reply_token,
                    f"{slot_time.strftime('%H:%M')} は埋まってしまいました。\n別の時間を選択してください。",
                )
                return

            # Room Preference Logic
            selected_room = None
            rooms_avail = result.get("rooms_available", [])
            
            if store == "ebisu":
                if room_pref:
                    if room_pref in rooms_avail:
                        selected_room = room_pref
                    else:
                        # Conflict
                        avail_rooms = [r for r in rooms_avail]
                        avail_str = "、".join([f"個室{r}" for r in avail_rooms])
                        
                        data["pending_time"] = f"{hour:02d}:{minute:02d}"
                        await db.set_session(
                            user_id, "booking", "resolve_room_conflict", json.dumps(data)
                        )
                        
                        await self.reply_text(
                            reply_token,
                            f"⚠️ 個室{room_pref}は埋まっています。\n"
                            f"{avail_str}なら空いています。",
                            quick_reply=QuickReply(
                                items=[
                                    QuickReplyItem(
                                        action=MessageAction(label=f"個室{avail_rooms[0]}で予約", text=f"個室{avail_rooms[0]}で予約")
                                    ),
                                    QuickReplyItem(
                                        action=MessageAction(label="時間を変更", text="時間を変更する")
                                    )
                                ]
                            )
                        )
                        return
                
                if not selected_room and rooms_avail:
                    selected_room = rooms_avail[0]

            data["time"] = f"{hour:02d}:{minute:02d}"
            if selected_room:
                 data["room"] = selected_room

            await db.set_session(
                user_id, "booking", "confirm", json.dumps(data)
            )

            # Confirmation Message
            display_date = slot_time.strftime("%m/%d")
            wd = WEEKDAY_JP[slot_time.weekday()]
            time_range = f"{hour:02d}:{minute:02d} - {hour + 1:02d}:{minute:02d}"
            store_display = STORE_NAMES.get(store, store)
            if selected_room:
                store_display += f"（個室{selected_room}）"

            confirm_msg = (
                f"📋 以下の内容で予約しますか？\n\n"
                f"📅 {display_date}（{wd}）\n"
                f"🕐 {time_range}\n"
                f"📍 {store_display}\n\n"
                f"よろしければ「確定」を押してください👇"
            )

            await self.reply_text(
                reply_token,
                confirm_msg,
                quick_reply=QuickReply(
                    items=[
                        QuickReplyItem(
                            action=MessageAction(label="✅ 予約する", text="確定する")
                        ),
                        QuickReplyItem(
                            action=MessageAction(label="❌ やめる", text="キャンセル")
                        ),
                    ]
                ),
            )

        elif state == "resolve_room_conflict":
            if "変更する" in text:
                target_date = datetime.strptime(data["date"], "%Y-%m-%d")
                bookings = await self._get_bookings()
                slots = get_available_slots(target_date, data["store"], bookings)

                items = []
                for slot in slots[:13]:
                    time_str = slot.strftime("%H:%M")
                    items.append(
                        QuickReplyItem(action=MessageAction(label=f"{time_str}", text=time_str))
                    )
                
                await db.set_session(user_id, "booking", "select_time", json.dumps(data))
                await self.reply_text(
                    reply_token, 
                    "🕐 時間を選択してください👇",
                    quick_reply=QuickReply(items=items)
                )
                return

            elif "で予約" in text:
                pending_time_str = data.get("pending_time")
                data["time"] = pending_time_str
                
                # Extract room "個室A" -> "A"
                room_match = re.search(r"個室([AB])", text)
                selected_room = room_match.group(1) if room_match else None
                if selected_room:
                    data["room"] = selected_room
                
                await db.set_session(user_id, "booking", "confirm", json.dumps(data))
                
                # Show confirmation
                h, m = map(int, pending_time_str.split(":"))
                target_date = datetime.strptime(data["date"], "%Y-%m-%d")
                slot_time = JST.localize(target_date.replace(hour=h, minute=m, second=0))
                
                display_date = slot_time.strftime("%m/%d")
                wd = WEEKDAY_JP[slot_time.weekday()]
                time_range = f"{h:02d}:{m:02d} - {h + 1:02d}:{m:02d}"
                
                store_display = STORE_NAMES.get(data["store"], data["store"])
                if selected_room:
                    store_display += f"（個室{selected_room}）"

                confirm_msg = (
                    f"📋 以下の内容で予約しますか？\n\n"
                    f"📅 {display_date}（{wd}）\n"
                    f"🕐 {time_range}\n"
                    f"📍 {store_display}\n\n"
                    f"よろしければ「確定」を押してください👇"
                )
                
                await self.reply_text(
                    reply_token,
                    confirm_msg,
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(
                                action=MessageAction(label="✅ 確定", text="確定する")
                            ),
                            QuickReplyItem(
                                action=MessageAction(label="❌ キャンセル", text="キャンセル")
                            ),
                        ]
                    ),
                )

        elif state == "confirm":
            if "確定" in text or "はい" in text or "OK" in text.upper():
                mode = data.get("mode", "booking")
                target_id = data.get("target_booking_id")
                target_type = data.get("target_booking_type")

                store = data.get("store", "ebisu")
                date_str = data.get("date")
                time_str = data.get("time")
                
                # Format datetime
                if len(time_str) == 5:
                    slot_datetime = f"{date_str}T{time_str}:00+09:00"
                else:
                    slot_datetime = f"{date_str}T{time_str}+09:00"

                # Save booking as provisional (仮予約)
                room_info = data.get("room") or data.get("room_pref")
                metadata = {"room": room_info} if room_info else None
                
                # 1. Cancel old booking if in change mode
                if mode == "change" and target_type == "db" and target_id:
                    try:
                        await db.cancel_booking(target_id)
                    except Exception as e:
                        print(f"Failed to cancel old booking: {e}")

                # 2. Save new booking
                booking_id = await db.save_booking(
                    user_id, store, slot_datetime, "provisional", metadata
                )

                # Clear session
                await db.clear_session(user_id)
                self._invalidate_cache()

                # Parse for display
                dt = datetime.fromisoformat(slot_datetime)
                display_date = dt.strftime("%m/%d")
                wd = WEEKDAY_JP[dt.weekday()]
                hour = dt.hour
                minute = dt.minute
                time_range = f"{hour:02d}:{minute:02d} - {hour + 1:02d}:{minute:02d}"
                
                # Check for room selection
                selected_room = data.get("room") or data.get("room_pref")
                store_display = STORE_NAMES.get(store, store)
                if selected_room:
                    store_display += f"（個室{selected_room}）"

                # 3. Success Message
                if mode == "change":
                    original_info = data.get("original_booking_info", {})
                    orig_dt_str = original_info.get("dt", "")
                    orig_store = original_info.get("store", "")
                    
                    orig_text_user = ""
                    if orig_dt_str:
                        try:
                            odt = datetime.fromisoformat(orig_dt_str)
                            owd = WEEKDAY_JP[odt.weekday()]
                            orig_text_user = (
                                f"▼ 変更前\n"
                                f" ・{odt.strftime('%m/%d')}（{owd}） {odt.strftime('%H:%M')}-\n"
                                f" ・{orig_store}\n\n"
                                f"↓↓↓↓↓\n\n"
                                f"▼ 変更後\n"
                            )
                        except:
                            pass

                    success_msg = (
                        f"🔄 変更リクエストを受け付けました！\n\n"
                        f"{orig_text_user}"
                        f" ・{display_date}（{wd}）{hour:02d}:{minute:02d}-\n"
                        f" ・{store_display}\n\n"
                        f"スタッフが確認後、確定のご連絡をいたします📩"
                    )
                else:
                    success_msg = (
                        f"✅ 仮予約を受け付けました！\n\n"
                        f"↓↓↓↓↓\n\n"
                        f"▼ 予約内容\n"
                        f" ・{display_date}（{wd}） {hour:02d}:{minute:02d}-\n"
                        f" ・{store_display}\n"
                        f" ・受付No. {booking_id}\n\n"
                        f"※ まだ予約は確定ではありません。\n"
                        f"スタッフが確認後、確定のご連絡をいたします📩"
                    )

                # Check for suggested dates to prompt next booking
                quick_reply = None
                suggested_dates = data.get("suggested_dates", [])
                if suggested_dates:
                    current_date = data.get("date")
                    valid_suggestions = []
                    seen = set()
                    for d in suggested_dates:
                        if d != current_date and d not in seen:
                            valid_suggestions.append(d)
                            seen.add(d)
                    
                    if valid_suggestions:
                        success_msg += """

━━━━━━━━━━━━━━━

💡 続けて他の日程も予約しますか？
（候補日をタップですぐ確認できます）"""
                        items = []
                        for sd_str in valid_suggestions[:10]:
                            try:
                                dt = datetime.strptime(sd_str, "%Y-%m-%d")
                                label = dt.strftime("%-m/%-d")
                                items.append(
                                    QuickReplyItem(
                                        action=MessageAction(label=label, text=label)
                                    )
                                )
                            except:
                                pass
                        if items:
                            quick_reply = QuickReply(items=items)

                await self.reply_text(reply_token, success_msg, quick_reply=quick_reply)
                
                # Notify Admin (single notification)
                if settings.ADMIN_USER_ID:
                    display_name = user.get("display_name", "Unknown")
                    
                    if mode == "change":
                        original_info = data.get("original_booking_info", {})
                        print(f"DEBUG: original_info from session: {original_info}") # Debug log
                        orig_dt_str = original_info.get("dt", "")
                        orig_store = original_info.get("store", "")
                        
                        orig_text = ""
                        if orig_dt_str:
                            try:
                                odt = datetime.fromisoformat(orig_dt_str)
                                owd = WEEKDAY_JP[odt.weekday()]
                                orig_text = (
                                    f"\n▼ 変更前\n"
                                    f" ・{odt.strftime('%m/%d')}（{owd}） {odt.strftime('%H:%M')}-\n"
                                    f" ・{orig_store}\n\n"
                                    f"↓↓↓↓↓\n\n"
                                    f"▼ 変更後"
                                )
                            except:
                                pass

                        admin_msg = (
                            f"🔄 予約変更リクエスト\n"
                            f"👤 {display_name}\n"
                            f"{orig_text}\n"
                            f" ・{display_date}（{wd}）{hour:02d}:{minute:02d}-\n"
                            f" ・{store_display}\n\n"
                            f"⚠️ カレンダーを確認して更新してください！"
                        )
                    elif mode == "change_OLD_UNUSED":

                        admin_msg = (
                            f"🔄 予約変更リクエスト\n"
                            f"👤 {display_name}\n"
                            f"📅 {display_date}（{wd}）\n"
                            f"� {time_range}\n"
                            f"📍 {store_display}\n\n"
                            f"⚠️ カレンダーを確認して更新してください！"
                        )
                    else:
                        admin_msg = (
                            f"🆕 新規予約リクエスト\n"
                            f"👤 {display_name}\n\n"
                            f"↓↓↓↓↓\n\n"
                            f"▼ 予約内容\n"
                            f" ・{display_date}（{wd}）{hour:02d}:{minute:02d}-\n"
                            f" ・{store_display}\n"
                            f" ・No. {booking_id}\n\n"
                            f"⚠️ hacomono/カレンダーに登録してください！"
                        )
                        
                    try:
                        await self.push_text(settings.ADMIN_USER_ID, admin_msg)
                    except Exception as e:
                        print(f"Admin notification failed: {e}")

            elif "キャンセル" in text or "やめ" in text:
                await db.clear_session(user_id)
                await self.reply_text(reply_token, "予約をキャンセルしました。\nまたいつでもどうぞ！👋")

            else:
                await self.reply_text(
                    reply_token,
                    "「予約する」または「やめる」を選んでください👇",
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(
                                action=MessageAction(label="✅ 予約する", text="確定する")
                            ),
                            QuickReplyItem(
                                action=MessageAction(label="❌ やめる", text="キャンセル")
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
            
            # Metadata parsing
            metadata = b.get("metadata", {})
            room = metadata.get("room") if metadata else None
            store_name = STORE_NAMES.get(b["store"], b["store"])
            if room:
                store_name += f" [個室{room}]"
                
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
            if b.room:
                store_name += f" [個室{b.room}]"
            
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
            "【 TOPFORM BOT 】\n\n"
            "以下のメニューからお選びください。\n\n"
            "■ 予約する\n"
            "■ 予約確認\n"
            "■ 早見表\n\n"
            "※ 日時を入力すると空き状況も確認できます。\n"
            "(例:「2.20空いてる？」「明日空き」)",
            quick_reply=quick_reply,
        )


    # ============================================================
    # Show user bookings (Simple Text)
    # ============================================================
    async def _show_user_bookings_simple(
        self, reply_token: str, user_id: str, user: dict
    ):
        """Show the user's upcoming bookings in a simple text list."""
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

        # Build text list
        msg_lines = ["📖 予約一覧\n"]
        
        # Merge and sort all bookings
        all_display_bookings = []
        
        # 1. DB Bookings
        for b in upcoming:
            dt = datetime.fromisoformat(b["slot_datetime"])
            metadata = b.get("metadata", {})
            room = metadata.get("room") if metadata else None
            store_name = STORE_NAMES.get(b["store"], b["store"])
            if room:
                store_name += f"（個室{room}）"
            
            status_mark = "【仮】" if b.get("status") == "provisional" else ""
            all_display_bookings.append({
                "dt": dt,
                "text": f"📅 {dt.strftime('%m/%d')}（{WEEKDAY_JP[dt.weekday()]}）{dt.strftime('%H:%M')} | {store_name}{status_mark}"
            })

        # 2. Calendar Bookings
        for b in cal_bookings:
            dt = b.start_dt
            store_name = STORE_NAMES.get(b.store, "")
            if b.room:
                store_name += f"（個室{b.room}）"
            
            all_display_bookings.append({
                "dt": dt,
                "text": f"📅 {dt.strftime('%m/%d')}（{WEEKDAY_JP[dt.weekday()]}）{dt.strftime('%H:%M')} | {store_name}"
            })

        # Sort by date
        all_display_bookings.sort(key=lambda x: x["dt"])

        # Limit to prevent message too long
        display_limit = 15
        for item in all_display_bookings[:display_limit]:
            msg_lines.append(item["text"])
        
        if len(all_display_bookings) > display_limit:
            msg_lines.append(f"\n...他 {len(all_display_bookings) - display_limit}件")

        msg_lines.append("\n変更する場合は「予約変更」と入力してください🔄")

        await self.reply_text(reply_token, "\n".join(msg_lines))

    # ============================================================
    # Show booking list for modification (Carousel with Pagination)
    # ============================================================
    async def _show_booking_change_list(
        self, reply_token: str, user_id: str, user: dict, offset: int = 0
    ):
        """Show future bookings in a carousel to select which one to change."""
        
        # 1. Fetch ALL future bookings (DB + Calendar)
        upcoming = await db.get_user_bookings(user_id, include_past=False)
        
        display_name = user.get("display_name", "")
        cal_bookings = []
        if display_name and display_name != "Unknown":
            bookings = await self._get_bookings()
            cal_bookings = find_user_bookings(display_name, bookings)
            # Filter future only
            now = datetime.now(JST)
            cal_bookings = [b for b in cal_bookings if b.start_dt > now]

        # 2. Unify format
        all_bookings = []
        
        # DB
        for b in upcoming:
            dt = datetime.fromisoformat(b["slot_datetime"])
            metadata = b.get("metadata", {})
            room = metadata.get("room") if metadata else None
            store_name = STORE_NAMES.get(b["store"], b["store"])
            if room:
                store_name += f"（個室{room}）"
            
            all_bookings.append({
                "type": "db",
                "id": b["id"],
                "dt": dt,
                "store": store_name,
                "status": b.get("status")
            })
            
        # Calendar
        for b in cal_bookings:
            dt = b.start_dt
            store_name = STORE_NAMES.get(b.store, "")
            if b.room:
                store_name += f"（個室{b.room}）"
                
            all_bookings.append({
                "type": "cal",
                "id": b.id or "cal",
                "dt": dt,
                "store": store_name,
                "status": "confirmed"
            })
            
        # Sort
        all_bookings.sort(key=lambda x: x["dt"])
        
        if not all_bookings:
             await self.reply_text(reply_token, "変更可能な予約はありません。")
             return

        # 3. Pagination Logic
        # Max bubbles = 12 (Official Line limit)
        # If we have more items than fit in one carousel, we use the last bubble for "More"
        CAROUSEL_MAX = 12
        
        has_more = False
        end_idx = offset + CAROUSEL_MAX
        
        if len(all_bookings) > end_idx:
            # Need "More" button, so effectively use MAX-1 bubbles for content
            end_idx = offset + (CAROUSEL_MAX - 1)
            has_more = True
            
        current_batch = all_bookings[offset : end_idx]
        
        # 4. Build Bubbles
        bubbles = []
        for b in current_batch:
            date_s = b["dt"].strftime("%m/%d")
            wd = WEEKDAY_JP[b["dt"].weekday()]
            time_s = b["dt"].strftime("%H:%M")
            
            bubble = {
                "type": "bubble",
                "size": "kilo",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{date_s}（{wd}）{time_s}",
                            "weight": "bold",
                            "color": "#000000",
                            "size": "md"
                        }
                    ],
                    "backgroundColor": "#ffffff",
                    "paddingTop": "20px",
                    "paddingStart": "20px",
                    "paddingBottom": "0px"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{b['store']}",
                            "size": "sm",
                            "color": "#666666",
                            "wrap": True
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
                                "label": "🔄 変更",
                                "data": json.dumps({
                                    "action": "select_change_booking",
                                    "booking_id": b["id"],
                                    "type": b["type"],
                                    "dt": b["dt"].isoformat(),
                                    "store": b["store"]
                                })
                            },
                            "style": "secondary",
                            "height": "sm"
                        }
                    ],
                    "paddingAll": "10px"
                }
            }
            bubbles.append(bubble)
            
        # 5. Add "More" Bubble if needed
        if has_more:
            bubbles.append({
                "type": "bubble",
                "size": "kilo",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "もっと見る...",
                                "data": json.dumps({
                                    "action": "change_list_more",
                                    "offset": end_idx
                                })
                            },
                            "style": "link",
                            "height": "sm"
                        }
                    ],
                    "justifyContent": "center",
                    "height": "150px"
                }
            })
            
        carousel = {
            "type": "carousel",
            "contents": bubbles
        }
        
        await self.reply_flex(reply_token, "予約変更：予約を選択", carousel)


# Singleton instance
line_service = LINEService()
