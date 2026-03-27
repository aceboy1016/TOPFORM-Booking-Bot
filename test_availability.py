import asyncio
from datetime import datetime
import pytz
from calendar_service import calendar_service, check_availability

JST = pytz.timezone("Asia/Tokyo")

async def test_slot():
    print("🔄 Initializing calendar service...")
    await calendar_service.initialize()
    
    print("📅 Fetching all bookings for simulation...")
    all_bookings = calendar_service.fetch_all_bookings()
    
    # ターゲット: 2026-03-28 09:00 @ Ebisu
    target_time = JST.localize(datetime(2026, 3, 28, 9, 0))
    store = "ebisu"
    
    print(f"\n🔍 Checking availability for: {target_time.strftime('%Y-%m-%d %H:%M')} @ {store}")
    result = check_availability(target_time, store, all_bookings)
    
    print(f"\n📢 Result: {'✅ Available' if result['is_available'] else '❌ NOT Available'}")
    if not result['is_available']:
        print(f"   Reason: {result.get('reason')}")
    
    # 詳細な重複理由を調査するためのデバッグ表示
    print("\n--- Detailed Status ---")
    ishihara_work = [b for b in all_bookings.ishihara if b.source == "work"]
    print(f"Trainer bookings: {len(ishihara_work)}")
    for b in ishihara_work:
        if max(target_time, b.start_dt) < min(target_time + timedelta(minutes=60), b.end_dt):
            print(f"⚠️ Conflict with: {b.title} ({b.start_dt.strftime('%H:%M')} - {b.end_dt.strftime('%H:%M')})")

    ebisu_bookings = all_bookings.ebisu
    print(f"Ebisu bookings: {len(ebisu_bookings)}")
    for b in ebisu_bookings:
        if max(target_time, b.start_dt) < min(target_time + timedelta(minutes=60), b.end_dt):
            print(f"⚠️ Ebisu room occupied: {b.title} (Room {b.room})")

if __name__ == "__main__":
    from datetime import timedelta
    asyncio.run(test_slot())
