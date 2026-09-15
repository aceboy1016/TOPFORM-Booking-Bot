"""
TOPFORM LINE Bot - LINE Service
LINEメッセージの処理と予約フローの管理
"""

import asyncio
import uuid
from availability_search import filters_from, matching, filter_label
import json
from async_services import google_call
from booking_rules import parse_slot, REASONS
from date_parser import parse_dates

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
        self._bookings_lock = asyncio.Lock()
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

    async def _get_bookings(self, force=False) -> BookingData:
        async with self._bookings_lock:
            now = datetime.now(JST)
            if force or self._cached_bookings is None or self._cache_time is None or now-self._cache_time>self._cache_ttl:
                snapshot = await google_call(calendar_service.fetch_all_bookings)
                self._cached_bookings = snapshot
                self._cache_time = datetime.now(JST)
            return self._cached_bookings

    async def close(self):
        if self._api_client: await self._api_client.close()

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
            profile = await self._api.get_profile(user_id, _request_timeout=20)
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
            ), _request_timeout=20
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
            ReplyMessageRequest(reply_token=reply_token, messages=[message]), _request_timeout=20
        )

    async def reply_messages(self, reply_token: str, messages: list):
        """Send multiple messages."""
        await self._api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=messages), _request_timeout=20
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
                        "color": "#92400E",
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
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": ok_label,
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
                            "label": "↩️ やめて戻る",
                            "text": "操作をやめる"
                        },
                        "style": "secondary"
                    }
                ],
                "paddingAll": "20px"
            }
        }

    async def handle_postback_event(self,event,user):
        from booking_actions import handle_action
        await handle_action(self,event,user)

    async def handle_text_message(self, event, user: dict):
        """Handle incoming text message."""
        text = event.message.text.strip()
        user_id = event.source.user_id
        reply_token = event.reply_token

        if text.lower() in ["id", "id確認", "user_id", "admin_id", "uid"]:
            await self.reply_text(reply_token, f"あなたのUser ID:\n{user_id}")

            return

        # --- Gatekeeper Check (Check if registered in Spreadsheet) ---
        customer = await google_call(sheets_service.get_customer_by_line_id,user_id)
        is_admin = (user_id == settings.ADMIN_USER_ID)

        if not customer and not is_admin:
            await self.reply_text(reply_token,"登録が完了してからご利用ください。ID確認は「ID確認」と送信してください。")
            return

        if customer:
            user["display_name"] = customer["name"]
            user["store_pref"] = customer.get("store_pref")
            user["room_pref"] = customer.get("room_pref")
            user["ambiguous_name"] = customer.get("ambiguous_name",False)

        if is_admin and text in ('承認待ち','予約受付一覧','管理メニュー'):
            from admin_review import show_pending
            await show_pending(self,reply_token,user_id)
            return

        # 管理者専用コマンド
        if user_id == settings.ADMIN_USER_ID:
            if text in ["ユーザー一覧", "顧客一覧", "user_list"]:
                users = await db.get_all_users()
                if not users:
                    await self.reply_text(reply_token, "登録ユーザーはまだいません。")
                    return
                
                # For admin list, a Flex Message carousel with buttons
                bubbles = []
                for u in users[:10]: # Limit for Flex Carousel
                    name = u.get("display_name", "Unknown")
                    uid = u.get("line_user_id", "")
                    customer = await google_call(sheets_service.get_customer_by_line_id,uid)
                    status = "✅ 登録済" if customer else "⚠️ 未登録"
                    
                    bubble = {
                        "type": "bubble",
                        "size": "micro",
                        "body": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": name, "weight": "bold", "size": "sm"},
                                {"type": "text", "text": status, "size": "xs", "color": "#888888"},
                                {"type": "text", "text": uid[:12] + "...", "size": "xxs", "margin": "xs"}
                            ]
                        },
                        "footer": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "button",
                                    "action": {
                                        "type": "postback",
                                        "label": "通知を送る",
                                        "data": json.dumps({"a": "activate_user", "uid": uid}),
                                        "displayText": f"{name}さんに完了通知を送る"
                                    },
                                    "style": "primary",
                                    "height": "sm",
                                    "color": "#1DB446" if not customer else "#888888" 
                                }
                            ]
                        }
                    }
                    bubbles.append(bubble)

                if bubbles:
                    flex_data = {"type": "carousel", "contents": bubbles}
                    await self.reply_flex(reply_token, "ユーザー一覧", flex_data)
                return

            if text in ["キャッシュ更新", "更新", "reload", "refresh"]:
                count = await google_call(sheets_service.force_refresh)
                await self.reply_text(
                    reply_token,
                    f"✅ 顧客マスタを再読み込みしました。\n登録済み顧客数: {count}名"
                )
                return

        session = await db.get_session(user_id)
        from conversation import route, normalize
        text = normalize(text)
        if await route(self, event, user, session):
            return

        if "店舗変更" in text:
            if session and session.get('flow_type')=='booking':
                data=json.loads(session.get('flow_data','{}'))
                for key in ('store','date','time','room','pending_time','was_both'):
                    data.pop(key,None)
                await db.set_session(user_id,'booking','select_store',json.dumps(data))
                await self.reply_text(reply_token,'店舗を選択してください。恵比寿店・半蔵門店・両店舗から選べます。')
            else:
                await self._start_booking_flow(reply_token,user_id,user,force_store_select=True)
            return

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

        # ---- 早見表フォーマットの一括予約 ----
        # Pattern: 2026/04/01(水) 10:30〜11:30 @恵比寿
        bulk_entries = self._parse_hayamihyo_bulk(text)
        if bulk_entries:
            await self._handle_bulk_booking(reply_token, user_id, user, bulk_entries)
            return

        in_active_booking_flow = bool(session) and session.get("flow_type") == "booking"
        if not in_active_booking_flow and ("予約" in text or "booking" in text.lower()):
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

        # ---- 自然言語解析: 「○日空いてる？」----
        dates = self._parse_multiple_dates(text)
        if dates:
            stores = [key for key, name in STORE_NAMES.items() if name.replace("店", "") in text]
            data = {"store": stores[0] if len(stores) == 1 else "both", "room_pref": user.get("room_pref")}
            await self._process_select_date(reply_token, user_id, {}, text, data)
            return

        # ---- 挨拶・労いへの返信 ----
        pleasantries = ["お疲れ", "おつかれ", "こんにちは", "おはよう", "ありがとう", "宜しく", "よろしく"]
        if any(p in text for p in pleasantries) and len(text) < 15:
            await self.reply_text(reply_token, f"{user.get('display_name', 'お客様')}さん、お疲れ様です！💪\n何かお手伝いできることはありますでしょうか？\n(例:「明日空いてる？」など)")
            return

        # ---- デフォルトレスポンス ----
        from conversation_extras import clarify
        await clarify(self,reply_token)

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
        if settings.ADMIN_USER_ID and user_id != settings.ADMIN_USER_ID:
            await db.enqueue('follow:'+user_id, settings.ADMIN_USER_ID,
                f'新規友だち追加\n名前: {display_name}\nLINE ID: {user_id}\n顧客マスタへの登録を確認してください。')
        await self.reply_text(event.reply_token, welcome)

    # ============================================================
    # Date query parsing
    # ============================================================
    def _extract_time(self, text: str) -> Optional[tuple[int, int]]:
        """
        Extract a specific HH:MM time from natural language text.
        Supports: 19:00 / 19：00 / 19時 / 19時30分
        """
        import unicodedata
        text = unicodedata.normalize('NFKC', text)
        # Compact chat times, excluding years and substrings of dates/numbers.
        compact = re.search(r'(?<![\d/年-])(\d{3,4})(?![\d/年月日-])',text)
        if compact:
            value=compact[1];hour,minute=int(value[:-2]),int(value[-2:])
            if 0<=hour<=23 and 0<=minute<=59: return hour,minute
        span=re.search(r'(?<![\d/])(\d{1,2})[-〜~](\d{1,2})時',text)
        if span and 0<=int(span[1])<=23: return int(span[1]),0
        m = re.search(r"(\d{1,2})[:：](\d{2})", text)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute

        m = re.search(r"(\d{1,2})時(?:(\d{1,2})分)?(半)?", text)
        if m:
            hour = int(m.group(1))
            minute = 30 if m.group(3) else int(m.group(2)) if m.group(2) else 0
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute

        return None

    def _parse_multiple_dates(self,text):
        return parse_dates(text,datetime.now(JST))

    async def _process_select_date(self, reply_token, user_id, session, text, data):
        """Keep inquiries and booking selections in the same draft."""
        dates = self._parse_multiple_dates(text)
        if not dates:
            from conversation_extras import clarify
            await clarify(self,reply_token)
            return
        data = dict(data)
        prior=await db.get_session(user_id)
        prior_data=json.loads(prior['flow_data']) if prior and prior.get('flow_type')=='booking' else {}
        if prior_data.get('picker_dates'):
            history=list(data.get('search_history',[]))
            history.append({key:prior_data[key] for key in ('picker_dates','date','store','time','filters','preferred_stores') if key in prior_data})
            data['search_history']=history[-5:]
        data['filters']=filters_from(text,data.get('filters'))
        data['picker_id'] = uuid.uuid4().hex
        data['picker_filter'] = text
        data['picker_dates'] = [d.strftime('%Y-%m-%d') for d in dates[:63]]
        data['store'] = data.get('store') or 'both'
        for key in ('time', 'pending_time', 'room', 'requested_time'):
            data.pop(key, None)
        if len(dates) == 1:
            data['date'] = data['picker_dates'][0]
        else:
            data.pop('date', None)
        state = 'select_time' if len(dates) == 1 and data['store'] in STORE_NAMES else 'select_store_after_date'
        requested = self._extract_time(text)
        specific_time = requested and not any(word in text for word in ('以降', 'まで', '午前', '午後', '夕方', '夜')) and len(dates) == 1
        if specific_time: data['requested_time'] = '%02d:%02d' % requested
        await db.set_session(user_id, 'booking', state, json.dumps(data))
        exact_request = specific_time and data['store'] in STORE_NAMES
        if exact_request:
            data['filters']={}
            await db.set_session(user_id, 'booking', state, json.dumps(data))
            slots = get_available_slots(dates[0], data['store'], await self._get_bookings())
            if any((slot.hour, slot.minute) == requested for slot in slots):
                customer = await google_call(sheets_service.get_customer_by_line_id, user_id)
                user = {'display_name': customer['name'], 'room_pref': customer.get('room_pref')} if customer else {}
                await self._handle_booking_flow(reply_token, user_id, user, await db.get_session(user_id), '%02d:%02d' % requested)
                return
        await self._show_available_cards(reply_token, user_id, data, note='ご希望の時刻に空きがありません。こちらの時間はいかがですか？😊' if exact_request else '')

    async def _show_available_cards(self, token, uid, data, date_offset=0, slot_offset=0, only_store=None, note=''):
        snapshot = await self._get_bookings()
        stores = [only_store] if only_store else ([data['store']] if data['store'] in STORE_NAMES else list(STORE_NAMES))
        dates = data['picker_dates']
        cards = []
        displayed=[]
        displayed_slots=[]
        rows=[(date,store,note) for date in dates[date_offset:date_offset+(1 if only_store else 4)] for store in stores]
        def slots_for(date,store):
            return matching(get_available_slots(datetime.strptime(date,'%Y-%m-%d'),store,snapshot),data.get('filters',filters_from(data.get('picker_filter',''))))
        # Offer alternatives using this same Calendar snapshot; never reserve them.
        if len(dates)==1 and not only_store and not any(slots_for(date,store) for date,store,_ in rows):
            preferred=data.get('preferred_stores') or stores
            other=[s for s in STORE_NAMES if s not in stores]
            for store in other:
                if slots_for(dates[0],store): rows.append((dates[0],store,'💡 同じ日なら、こちらの店舗が空いています😊'))
            first=datetime.strptime(dates[0],'%Y-%m-%d')
            for offset in range(1,8):
                date=(first+timedelta(days=offset)).strftime('%Y-%m-%d')
                available=next((store for store in preferred if slots_for(date,store)),None)
                if available:
                    rows.append((date,available,'💡 別の日なら、こちらはいかがですか？😊'))
                    break
        if data.get('preferred_stores') and len(stores)==2:
            # The first preference wins whenever it has a matching slot that day.
            first,second=data['preferred_stores']
            rows=[r for r in rows if r[1]!=second or not slots_for(r[0],first)]
        async def button(label, payload):
            payload = dict(payload, picker_id=data['picker_id'])
            if payload['a'] == 'picker_page':
                payload['picker'] = {key: data[key] for key in ('picker_id', 'picker_dates', 'store', 'picker_filter','filters','preferred_stores','room_pref') if key in data}
                if payload.get('date'):
                    payload['picker']['picker_dates']=[payload['date']]
                    payload['date_offset']=0
            action = await db.make_action(uid, payload, ttl=7*24*60)
            return {'type': 'button', 'height': 'sm', 'style': 'secondary', 'action': {'type': 'postback', 'label': label, 'data': action}}
        for date,store,row_note in rows:
            day = datetime.strptime(date, '%Y-%m-%d')
            slots = slots_for(date,store)
            body = [{'type': 'text', 'text': '📅 '+day.strftime('%m/%d')+'（'+WEEKDAY_JP[day.weekday()]+'）', 'weight': 'bold', 'size': 'lg'},
                    {'type': 'text', 'text': '📍 '+STORE_NAMES[store], 'margin': 'md'},
                    {'type': 'text', 'text': row_note or ('空き時間をタップしてください👇'+('（'+filter_label(data.get('filters',{}))+'）' if data.get('filters') else '') if slots else '🌿 この日の空きはありません。別の日も聞いてくださいね。'), 'wrap': True, 'size': 'sm', 'margin': 'md'}]
            page=slots[slot_offset:slot_offset+10]
            preferred_room=data.get('room_pref') if store=='ebisu' else None
            groups=[(None,page)]
            if preferred_room in ('A','B'):
                alternative='B' if preferred_room=='A' else 'A'
                preferred_slots=[];alternative_slots=[]
                for slot in page:
                    available=check_availability(slot,store,snapshot).get('rooms_available',[])
                    if preferred_room in available: preferred_slots.append(slot)
                    elif alternative in available: alternative_slots.append(slot)
                groups=[(preferred_room,preferred_slots),(alternative,alternative_slots)]
            for room,room_slots in groups:
                if room and room_slots:
                    heading=f'🚪 ご希望の個室{room}はこちら😊' if room==preferred_room else f'💡 個室{preferred_room}が埋まっている時間も、個室{room}ならこちらが空いています😊'
                    body.append({'type':'text','text':heading,'wrap':True,'size':'sm','weight':'bold','margin':'lg'})
                for slot in room_slots:
                    displayed.append(slot.strftime('%H:%M'))
                    displayed_slots.append({'date':date,'store':store,'time':slot.strftime('%H:%M')})
                    payload={'a':'pick_slot','date':date,'store':store,'time':slot.strftime('%H:%M')}
                    if room: payload['room']=room
                    body.append(await button('🕐 '+slot.strftime('%H:%M'),payload))
            if len(slots) > slot_offset+10:
                body.append(await button('次の時間を見る ➡️', {'a':'picker_page', 'date_offset':0, 'date':date, 'slot_offset':slot_offset+10, 'store':store}))
            if slot_offset:
                body.append(await button('最初の時間へ ↩️', {'a':'picker_page', 'date_offset':0, 'date':date, 'slot_offset':0, 'store':store}))
            cards.append({'type':'bubble', 'body':{'type':'box','layout':'vertical','spacing':'sm','contents':body}})
        if not only_store and date_offset+4 < len(dates):
            cards.append({'type':'bubble','body':{'type':'box','layout':'vertical','contents':[await button('次の日程を見る ➡️', {'a':'picker_page','date_offset':date_offset+4,'slot_offset':0})]}})
        current=await db.get_session(uid)
        if current and current.get('flow_type')=='booking':
            current_data=json.loads(current['flow_data'])
            if current_data.get('picker_id')==data.get('picker_id'):
                current_data['last_shown']=sorted(set(displayed))
                current_data['shown_slots']=displayed_slots
                await db.set_session(uid,'booking',current['flow_state'],json.dumps(current_data))
        await self.reply_messages(token, [FlexMessage(alt_text='📅 空き時間を選んで仮予約へ😊', contents=FlexContainer.from_dict({'type':'carousel','contents':cards}))])

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
             store_code = "ebisu" if "ebisu" in store_pref else "hanzoomon"
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
                QuickReplyItem(
                    action=MessageAction(label="⬅️ 戻る", text="⬅️ 戻る")
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

        # --- Handle "Back" Button ---
        if text == "⬅️ 戻る" or text == "戻る":
            if state == "select_store":
                # Go back to main exit (Clear session and show welcome)
                await db.clear_session(user_id)
                await self.reply_text(reply_token, "予約を中断しました。メニューから新しく選んでください。")
                return
            elif state == "select_date":
                # Preserve date and target while stepping back to store selection.
                for key in ('time','room','pending_time','was_both'):
                    data.pop(key,None)
                await db.set_session(user_id,'booking','select_store',json.dumps(data))
                await self.reply_text(reply_token,'店舗を選択してください。恵比寿店・半蔵門店・両店舗から選べます。入力済みの日付は引き継ぎます。')
                return
            elif state == "select_store_after_date":
                # Back to Date Selection
                await db.set_session(user_id, "booking", "select_date", json.dumps(data))
                prompt = "希望日時を入力してください\n(例: 2/20, 明日, 土曜)"
                qr = QuickReply(items=[QuickReplyItem(action=MessageAction(label="⬅️ 戻る", text="⬅️ 戻る"))])
                await self.reply_text(reply_token, prompt, quick_reply=qr)
                return
            elif state == "select_time":
                # Back to Date selection OR Store selection after date
                if data.get("was_both"):
                    # Transition back to picking store after date
                    data["store"]="both"
                    await self._process_select_date(reply_token, user_id, session, data.get("date"), data)
                else:
                    await db.set_session(user_id, "booking", "select_date", json.dumps(data))
                    store_name = STORE_NAMES.get(data.get("store"), data.get("store"))
                    prompt = f"■ {store_name}\n\n希望日時を入力してください"
                    qr = QuickReply(items=[QuickReplyItem(action=MessageAction(label="⬅️ 戻る", text="⬅️ 戻る"))])
                    await self.reply_text(reply_token, prompt, quick_reply=qr)
                return
            elif state == "confirm":
                # Back to Time selection
                await db.set_session(user_id, "booking", "select_time", json.dumps(data))
                await self._process_select_date(reply_token, user_id, session, data.get("date"), data)
                return
            elif state == "resolve_room_conflict":
                 # Back to Time selection
                await db.set_session(user_id, "booking", "select_time", json.dumps(data))
                await self._process_select_date(reply_token, user_id, session, data.get("date"), data)
                return

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
                            QuickReplyItem(
                                action=MessageAction(
                                    label="⬅️ 戻る", text="⬅️ 戻る"
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
            if data.get('date'):
                await self._process_select_date(reply_token,user_id,session,data['date'],data)
                return

            if store == "both":
                await self.reply_text(
                    reply_token,
                    "■ 両店舗（恵比寿 & 半蔵門）\n\n希望日時を入力してください\n(例: 2/20, 明日, 土曜)\n\n両店舗の空き状況を同時にお見せします！",
                )
            else:
                store_name = STORE_NAMES.get(store, store)
                await self.reply_text(
                    reply_token,
                    f"■ {store_name}\n\n希望日時を入力してください\n(例: 2/21, 明日, 土曜)",
                )

        elif state == "select_store_after_date":
            # User selected a store after viewing both stores' availability
            store = None
            if "恵比寿" in text:
                store = "ebisu"
            elif "半蔵門" in text:
                store = "hanzoomon"

            if not store:
                requested = self._extract_time(text)
                if requested and data.get('date'):
                    data['pending_datetime_text'] = data['date'] + ' ' + ('%02d:%02d' % requested)
                    await db.set_session(user_id, 'booking', state, json.dumps(data))
                await self.reply_text(
                    reply_token,
                    "📍 ご希望の店舗はどちらですか？😊\n時間のボタンから選ぶこともできます👇",
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(action=MessageAction(label="恵比寿店", text="恵比寿店")),
                            QuickReplyItem(action=MessageAction(label="半蔵門店", text="半蔵門店")),
                            QuickReplyItem(action=MessageAction(label="⬅️ 戻る", text="⬅️ 戻る")),
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
                    f"■ {store_name}\n\n希望日時を入力してください\n(例: 2/21, 明日, 土曜)",
                )
                return

            await self._process_select_date(reply_token, user_id, session, date_str, data)

        elif state == "select_date":
            await self._process_select_date(reply_token, user_id, session, text, data)

        elif state == "select_time":
            t = self._extract_time(text)
            if not t:
                # Fallback: check if it matches a date
                dates = self._parse_multiple_dates(text)
                if dates:
                    await self._process_select_date(reply_token, user_id, session, text, data)
                    return

                from conversation_extras import clarify
                await clarify(self,reply_token)
                return

            hour, minute = t
            date_str = data.get("date")
            store = data.get("store", "ebisu")
            room_pref = data.pop("room_choice", None) or data.get("room_pref")

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

            data['confirmation_id'] = uuid.uuid4().hex
            await db.set_session(user_id, 'booking', 'confirm', json.dumps(data))
            action = await db.make_action(user_id, {'a':'picker_confirm','confirmation_id':data['confirmation_id']})
            confirm_msg = confirm_msg.replace('よろしければ「確定」を押してください👇', 'スタッフ確認前の仮予約です。\n内容がよければ下のボタンを押してください😊')
            card=self._build_confirm_flex('📋 仮予約の内容確認', confirm_msg, '✅ 仮予約を申し込む', action, '#15803D')
            for label,text in [('📅 日時を変更','日時を変更したい'),('📍 店舗を変更','店舗を変更したい')]:
                card['footer']['contents'].insert(-1,{'type':'button','height':'sm','action':{'type':'message','label':label,'text':text}})
            await self.reply_flex(reply_token, '📋 仮予約の内容確認', card)

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
                selected = re.search(r"個室([AB])",text)
                snapshot=await self._get_bookings(force=True)
                availability=check_availability(parse_slot(data['date'],data['pending_time']),data['store'],snapshot)
                if not selected or not availability['is_available'] or selected[1] not in availability.get('rooms_available',[]):
                    await self.reply_text(reply_token,'この個室は現在利用できません。別の日時を選んでください。')
                    return
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
            consent = re.sub(r'[\s!！。😊🙌🙏👍✅☺️]+$', '', text.strip()).upper()
            if consent in ("確定", "確定する", "はい", "OK", "予約する", "お願いします", "はい、お願いします", "はいお願いします"):
                mode = data.get("mode", "booking")
                target_id = data.get("target_booking_id")
                target_type = data.get("target_booking_type")

                store = data.get("store", "ebisu")
                date_str = data.get("date")
                time_str = data.get("time")
                
                slot=parse_slot(date_str,time_str)
                snapshot=await self._get_bookings(force=True)
                result=check_availability(slot,store,snapshot)
                if not result['is_available']:
                    await self.reply_text(reply_token,REASONS.get(result.get('reason'),'この枠は現在利用できません。'))
                    return
                room_info=data.get('room')
                if room_info and store=='ebisu' and room_info not in result.get('rooms_available',[]):
                    await self.reply_text(reply_token,'選択した個室が埋まりました。時間を選び直してください。')
                    return
                slot_datetime=slot.isoformat()
                metadata={'customer_name':user.get('display_name',''), 'room':room_info}
                if mode=='change':
                    from booking_actions import resolve_booking, cancel_band
                    original=await resolve_booking(self,user_id,user,target_type,target_id)
                    if not original or original['dt']<=datetime.now(JST) or cancel_band(original['dt'])!='normal':
                        await self.reply_text(reply_token,'元の予約の状態または変更期限が変わりました。予約変更の一覧からやり直してください。')
                        return
                    metadata['change_from']={'id':original['id'],'type':original['type'],'dt':original['dt'].isoformat(),'store':original['store']}
                from booking_view import user_bookings
                existing = [b for b in await user_bookings(self,user_id,user)
                            if b['dt']==slot and b['store']==store]
                if existing:
                    await self.reply_text(reply_token,'同じ日時・店舗の予約は受付済みです。新しい予約は追加していません。\n予約確認から内容をご確認ください。')
                    return
                booking_id=await db.save_booking(user_id,store,slot_datetime,'provisional',metadata)

                from conversation import remember
                await remember(user_id, booking_id, metadata)
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
                
                # The admin notification was committed atomically with the request.

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
    async def _show_user_bookings(self,reply_token,user_id,user):
        await self._show_user_bookings_simple(reply_token,user_id,user)

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
            "🤖 TOPFORM 予約Bot\n\n"
            "どんなご希望ですか？😊\n\n"
            "📅 予約する\n"
            "📖 予約確認\n"
            "📋 早見表\n\n"
            "※ 日時を入力すると空き状況も確認できます。\n"
            "(例:「2/20空いてる？」「明日空き」)",
            quick_reply=quick_reply,
        )


    # ============================================================
    # Show user bookings (Simple Text)
    # ============================================================
    async def _show_user_bookings_simple(self,reply_token,user_id,user):
        from booking_view import user_bookings, counted_reservations
        entries=await user_bookings(self,user_id,user,include_past=True)
        now=datetime.now(JST)
        counted=counted_reservations(entries,await db.get_user_bookings(user_id,include_past=True))
        month=[b for b in counted if (b['dt'].year,b['dt'].month)==(now.year,now.month)]
        provisional=sum(b['status']=='provisional' for b in month)
        future=[b for b in entries if b['dt']>now]
        lines=['📖 ご予約一覧', '', f'📊 今月の予約: {len(month)}件（うち仮予約 {provisional}件）', f'🗓️ これからのご予約: {sum(b["dt"]>now for b in counted)}件', '']
        for b in future[:20]:
            status='⏳ 仮予約・スタッフ確認待ち' if b['status']=='provisional' else '✅ 確定済み'
            lines.extend(['📅 '+b['dt'].strftime('%m/%d')+'（'+'月火水木金土日'[b['dt'].weekday()]+'）',
                '🕐 '+b['dt'].strftime('%H:%M')+'〜  📍 '+STORE_NAMES.get(b['store'],b['store']),status,''])
        if not future: lines.extend(['これからのご予約はまだありません🌱','「予約する」からお申し込みできます😊',''])
        if len(future)>20: lines.extend([f'ほか{len(future)-20}件あります。予約変更の一覧で確認できます🔎',''])
        lines.extend(['💡 今月の日付の予約を数えています。仮予約を含み、取消済みは除きます。変更前後はまとめて1件です。','', '🔄 変更・取消は「予約変更」と送ってくださいね😊'])
        await self.reply_text(reply_token,'\n'.join(lines))

    async def _show_booking_change_list(
        self, reply_token: str, user_id: str, user: dict, offset: int = 0
    ):
        """Show future bookings in a carousel to select which one to change."""
        
        from booking_view import user_bookings
        all_bookings=await user_bookings(self,user_id,user)
        if not all_bookings:
            await self.reply_text(reply_token,'変更可能な予約はありません。')
            return
        offset=max(0,min(offset,max(0,len(all_bookings)-1)))
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
                            "text": STORE_NAMES.get(b["store"],b["store"]),
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
                                "label": "🔄 該当する日時を変更",
                                "data": await db.make_action(user_id,{"a":"scb","bid":b["id"],"t":b["type"]})
                            },
                            "style": "secondary",
                            "height": "sm"
                        }
                    ],
                    "paddingAll": "10px"
                }
            }
            bubble['footer']['contents'].append({'type':'button','action':{'type':'postback','label':'予約を取り消す','data':await db.make_action(user_id,{'a':'cancel_request','bid':b['id'],'t':b['type']})},'style':'secondary','height':'sm'})
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
                                    "a": "change_list_more",
                                    "off": end_idx
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

    # ============================================================
    # 早見表一括予約パーサー＆ハンドラー
    # ============================================================
    def _parse_hayamihyo_bulk(self, text: str) -> list[dict]:
        """
        Parse bulk booking text from 早見表 format.
        
        Supported formats:
          ・2026/04/01(水) 10:30〜11:30 @恵比寿
          ・2026/04/05(日) 09:00〜10:00 @恵比寿店
          - 04/01(水) 10:30~11:30 @半蔵門
          2026/04/01 10:30-11:30 恵比寿
        
        Returns a list of dicts with keys: date_str, time_str, store, display
        """
        entries = []
        
        # Pattern: optional YYYY/ then MM/DD optional (曜) then HH:MM then 〜/~/- then HH:MM then optional @ then store
        pattern = re.compile(
            r'(\d{4}/)?(\d{1,2}/\d{1,2})'       # date (optional year + MM/DD)
            r'\s*(?:\([月火水木金土日]\)\s*)?'      # optional (曜)
            r'(\d{1,2}:\d{2})'                    # start time HH:MM
            r'\s*[〜~\-～]\s*'                      # separator 
            r'(\d{1,2}:\d{2})'                    # end time HH:MM
            r'\s*@?\s*(恵比寿|半蔵門|ebisu|hanzoomon|hanzomon)?', # optional store
            re.MULTILINE
        )
        
        for m in pattern.finditer(text):
            year_part = m.group(1)  # "2026/" or None
            md_part = m.group(2)    # "04/01"
            start_time = m.group(3) # "10:30"
            end_time = m.group(4)   # "11:30"
            store_raw = m.group(5)  # "恵比寿" or None
            
            # Determine year
            now = datetime.now(JST)
            if year_part:
                year = int(year_part.rstrip('/'))
            else:
                year = now.year
            
            # Parse date
            try:
                month, day = map(int, md_part.split('/'))
                target_date = datetime(year, month, day)
            except (ValueError, TypeError):
                continue
                
            date_str = target_date.strftime("%Y-%m-%d")
            
            # Determine store
            store = "ebisu"  # default
            if store_raw:
                if "半蔵門" in store_raw or store_raw.lower() in ("hanzomon","hanzoomon"):
                    store = "hanzoomon"
                else:
                    store = "ebisu"
            
            # Format for display
            wd = WEEKDAY_JP[target_date.weekday()]
            store_display = STORE_NAMES.get(store, store)
            display = f"{month:02d}/{day:02d}（{wd}）{start_time}〜{end_time} @{store_display}"
            
            entries.append({
                "date_str": date_str,
                "time_str": start_time,
                "end_time": end_time,
                "store_explicit": bool(store_raw),
                "store": store,
                "display": display,
            })
        
        return entries

    async def _handle_bulk_booking(self,reply_token,user_id,user,entries):
        if len(entries)>20:
            await self.reply_text(reply_token,'一度に指定できる予約は20件までです。');return
        session = await db.get_session(user_id)
        data = json.loads(session.get('flow_data','{}')) if session else {}
        if session and session.get('flow_type')=='booking' and data.get('mode')=='change':
            if len(entries)!=1:
                await self.reply_text(reply_token,'1件の予約変更には、変更後の日時を1つ指定してください。元の予約は残っています。')
                return
            entry=entries[0]
            try:
                slot=parse_slot(entry['date_str'],entry['time_str'])
                if parse_slot(entry['date_str'],entry['end_time'])-slot!=timedelta(hours=1):
                    raise ValueError('1枠60分で指定してください。')
            except (ValueError,TypeError):
                await self.reply_text(reply_token,'有効な日時を1枠60分で指定してください。元の予約は残っています。')
                return
            store=entry['store'] if entry.get('store_explicit',True) else data.get('store')
            if store not in STORE_NAMES:
                await self.reply_text(reply_token,'変更後の店舗を指定してください。恵比寿店・半蔵門店から選べます。')
                return
            data.update(store=store,date=entry['date_str'])
            for key in ('room','pending_time','time'):
                data.pop(key,None)
            await self._handle_booking_flow(reply_token,user_id,user,
                {'flow_state':'select_time','flow_data':json.dumps(data)},entry['time_str'])
            return
        from booking_view import user_bookings
        existing={(b['dt'],b['store']):b for b in await user_bookings(self,user_id,user)}
        snapshot=await self._get_bookings(force=True)
        results=[];seen=set();last=None

        for entry in entries:
            try:
                slot=parse_slot(entry['date_str'],entry['time_str'])
                end=parse_slot(entry['date_str'],entry['end_time'])
                if end-slot!=timedelta(hours=1): raise ValueError('1枠60分で指定してください。')
                key=(slot,entry['store'])
                if key in seen: continue
                seen.add(key)
                if key in existing:
                    results.append(f"受付済み（追加なし）: {slot.strftime('%m/%d %H:%M')} {STORE_NAMES[entry['store']]}")
                    continue
                result=check_availability(slot,entry['store'],snapshot)
                if not result['is_available']: raise ValueError(REASONS.get(result.get('reason'),'空きがありません。'))
                room=user.get('room_pref')
                if entry['store']!='ebisu' or room not in result.get('rooms_available',[]): room=None
                bid=await db.save_booking(user_id,entry['store'],slot.isoformat(),'provisional',{'room':room,'customer_name':user.get('display_name','')})
                last=bid
                results.append(f"受付 No.{bid}: {slot.strftime('%m/%d %H:%M')} {STORE_NAMES[entry['store']]}")
            except ValueError as exc:
                results.append(f"受付不可 {entry['date_str']} {entry['time_str']}: {exc}")
        if last:
            from conversation import remember
            await remember(user_id,last,{})
        self._invalidate_cache()
        await self.reply_text(reply_token,'仮予約の受付結果\n'+'\n'.join(results)+'\nスタッフ確認後に確定します。')


# Singleton instance
line_service = LINEService()
