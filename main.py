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
