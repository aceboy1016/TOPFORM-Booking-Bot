"""
TOPFORM LINE Bot - Main Application
公式LINE予約Botのメインエントリーポイント
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    FollowEvent,
    TextMessageContent,
    PostbackEvent,
)
from linebot.v3 import WebhookParser

from config import settings
from database import db
from calendar_service import calendar_service
from line_service import line_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    print("🚀 Starting TOPFORM LINE Bot...")

    # Validate configuration
    missing = settings.validate()
    if missing:
        print(f"⚠️  Warning: Missing configuration: {', '.join(missing)}")

    # Initialize database
    await db.init_db()
    print("✅ Database initialized")

    # Initialize Google Calendar
    try:
        await calendar_service.initialize()
        print("✅ Google Calendar Service initialized")
    except Exception as e:
        print(f"⚠️  Calendar Service init failed: {e}")

    # Initialize LINE
    await line_service.initialize()
    print("✅ LINE Service initialized")

    print("🎉 TOPFORM LINE Bot is ready!")

    yield

    print("👋 Shutting down TOPFORM LINE Bot...")


app = FastAPI(
    title="TOPFORM LINE Bot",
    description="TOPFORM公式LINE 予約Bot（石原トレーナー）",
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================
# Health check
# ============================================================
@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "TOPFORM_LINE_Bot",
        "version": "1.0.0",
    }


@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "services": {
            "database": "connected",
            "line": "initialized",
            "calendar": "ready",
        },
    }


# ============================================================
# LINE Webhook
# ============================================================
@app.post("/webhook")
async def webhook_handler(request: Request):
    """LINE Webhook endpoint."""
    signature = request.headers.get("X-Line-Signature", "")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    body = await request.body()
    body_text = body.decode("utf-8")

    try:
        parser = WebhookParser(settings.LINE_CHANNEL_SECRET)
        events = parser.parse(body_text, signature)

        print(f"📩 Webhook received: {len(events)} event(s)")

        for event in events:
            # Cloud Runではレスポンス返却後にCPUが割り当てられなくなるため
            # awaitして処理完了まで待機する必要があります。
            await process_event(event)

        return JSONResponse(content={"status": "ok"})

    except InvalidSignatureError:
        print("❌ Invalid signature!")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def process_event(event):
    """Process a single LINE event."""
    event_type = type(event).__name__
    try:
        user_id = event.source.user_id
        print(f"🔄 Processing {event_type} from {user_id[:8]}...")
        
        # Get or create user for all event types
        # This ensures we have display_name even for postbacks
        display_name = await line_service.get_user_profile(user_id)
        user = await db.get_or_create_user(user_id, display_name)

        if isinstance(event, FollowEvent):
            print(f"  👤 Follow event")
            await line_service.handle_follow_event(event)

        elif isinstance(event, MessageEvent):
            # Handle text messages
            if isinstance(event.message, TextMessageContent):
                print(f"  💬 Text: {event.message.text[:50]}")
                await line_service.handle_text_message(event, user)
            else:
                print(f"  📎 Non-text message: {type(event.message).__name__}")
        
        elif isinstance(event, PostbackEvent):
            print(f"  🔘 Postback: {event.postback.data[:50]}")
            await line_service.handle_postback_event(event, user)
        
        else:
            print(f"  ⏭️ Unhandled event type: {event_type}")

        print(f"✅ {event_type} processed successfully")

    except Exception as e:
        print(f"❌ Error processing {event_type}: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# API endpoints (for debugging/admin)
# ============================================================
@app.get("/api/availability/{date}")
async def get_availability(date: str, store: str = "ebisu"):
    """Get available slots for a date (YYYY-MM-DD)."""
    from datetime import datetime
    import pytz

    JST = pytz.timezone("Asia/Tokyo")

    try:
        target = JST.localize(datetime.strptime(date, "%Y-%m-%d"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    from calendar_service import get_available_slots

    bookings = calendar_service.fetch_all_bookings()
    slots = get_available_slots(target, store, bookings)

    return {
        "date": date,
        "store": store,
        "available_slots": [s.strftime("%H:%M") for s in slots],
        "count": len(slots),
    }


@app.get("/api/bookings/{line_user_id}")
async def get_user_bookings(line_user_id: str):
    """Get bookings for a user."""
    bookings = await db.get_user_bookings(line_user_id, include_past=True)
    return {"bookings": bookings}


@app.get("/api/check-waitlist")
async def trigger_check_waitlist():
    """Check waitlist and notify users if there are available slots."""
    from sheets_service import sheets_service
    from calendar_service import calendar_service, check_availability
    from line_service import line_service
    from datetime import datetime
    import pytz
    
    # Ensure services are initialized
    await line_service.initialize()
    
    JST = pytz.timezone("Asia/Tokyo")
    waitlist = sheets_service.fetch_waitlist()
    if not waitlist:
        return {"status": "success", "message": "No waitlist entries"}

    bookings = calendar_service.fetch_all_bookings()
    notified_count = 0
    results = []

    for entry in waitlist:
        if entry["status"] != "待機中":
            continue
            
        date_str = entry["date"]
        time_str = entry["time"]
        store_entry = entry["store"]
        stores_to_check = []
        if "恵比寿" in store_entry or "または" in store_entry or "どちら" in store_entry:
            stores_to_check.append("ebisu")
        if "半蔵門" in store_entry or "または" in store_entry or "どちら" in store_entry:
            stores_to_check.append("hanzoomon")
        if not stores_to_check:
            stores_to_check = ["ebisu"]
        
        try:
            target_date = JST.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))
        except Exception as e:
            print(f"Date parsing error: {e}")
            continue
                
        # Check availability
        is_available = False
        available_store_name = store_entry
        for sc in stores_to_check:
            status = check_availability(target_date, sc, bookings)
            if status.get("is_available"):
                is_available = True
                available_store_name = "恵比寿店" if sc == "ebisu" else "半蔵門店"
                break
        
        if is_available:
            import json
            # Interactive Flex Message
            postback_data_accept = json.dumps({
                "action": "waitlist_accept",
                "date": date_str,
                "time": time_str,
                "store": available_store_name
            })
            postback_data_decline = json.dumps({
                "action": "waitlist_decline"
            })
            
            flex_content = {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "🚨 空き枠のお知らせ",
                            "weight": "bold",
                            "color": "#ff0000",
                            "size": "md"
                        },
                        {
                            "type": "text",
                            "text": f"{entry['name']}様\nキャンセル待ちされていた以下の日時に空きが出ました！",
                            "wrap": True,
                            "size": "sm",
                            "margin": "md"
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "margin": "md",
                            "spacing": "sm",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": f"📅 {date_str} {time_str}",
                                    "weight": "bold",
                                    "size": "md"
                                },
                                {
                                    "type": "text",
                                    "text": f"📍 {available_store_name}",
                                    "weight": "bold",
                                    "size": "md"
                                }
                            ]
                        },
                        {
                            "type": "text",
                            "text": "この枠で予約手続きを進めますか？\n（※先着順となりますので、入れ違いで埋まってしまった場合はご了承ください🙇‍♂️）",
                            "wrap": True,
                            "size": "xs",
                            "color": "#666666",
                            "margin": "lg"
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
                                "label": "受けます",
                                "data": postback_data_accept,
                                "displayText": "キャンセル待ちをお受けします（希望します）"
                            },
                            "style": "primary",
                            "color": "#E63946"
                        },
                        {
                            "type": "button",
                            "action": {
                                "type": "postback",
                                "label": "見送ります",
                                "data": postback_data_decline,
                                "displayText": "今回は見送ります"
                            },
                            "style": "secondary"
                        }
                    ],
                    "paddingAll": "20px"
                }
            }

            try:
                if entry["line_id"]:
                    await line_service.push_flex(entry["line_id"], "空き枠のお知らせ", flex_content)
                    sheets_service.update_waitlist_status(entry["row_index"], "通知済み")
                    notified_count += 1
                    results.append({"name": entry["name"], "status": "notified"})
                else:
                    results.append({"name": entry["name"], "status": "no_line_id"})
            except Exception as e:
                print(f"Failed to notify {entry['name']}: {e}")
                results.append({"name": entry["name"], "status": "error", "error": str(e)})

    return {
        "status": "success",
        "processed": len([e for e in waitlist if e["status"] == "待機中"]),
        "notified": notified_count,
        "details": results
    }


# ============================================================
# Local development
# ============================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
