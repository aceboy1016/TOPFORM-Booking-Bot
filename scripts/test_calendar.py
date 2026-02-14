"""
TEST CALENDAR CONNECTION
Google Calendar APIの接続テストを行うスクリプト

.env の GOOGLE_CREDENTIALS_JSON が正しく設定されているか確認します。
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from config import settings
from calendar_service import calendar_service, get_available_slots
from datetime import datetime, timedelta
import pytz

JST = pytz.timezone("Asia/Tokyo")

def test_connection():
    print("🚀 Testing Google Calendar API connection...")
    
    if not settings.GOOGLE_CREDENTIALS_JSON:
        print("❌ Error: GOOGLE_CREDENTIALS_JSON is not set in .env")
        print("   Please run 'python scripts/encode_creds.py <your_json_file>' to generate it.")
        return

    try:
        # 1. Initialize
        calendar_service.initialize()
        print("✅ Service initialized.")
        
        # 2. Fetch bookings
        print("🔍 Fetching bookings (this may take a few seconds)...")
        bookings = calendar_service.fetch_all_bookings()
        
        print(f"✅ Fetched data successfully!")
        print(f"   Last Update: {bookings.last_update}")
        print(f"   Ishihara Bookings: {len(bookings.ishihara)}")
        print(f"   Ebisu Bookings: {len(bookings.ebisu)}")
        print(f"   Hanzoomon Bookings: {len(bookings.hanzoomon)}")
        
        # 3. Check for recent bookings
        if bookings.ishihara:
            print("\n📋 Recent Ishihara bookings:")
            for b in bookings.ishihara[:3]:
                print(f"   - [{b.start}] {b.title}")
        
        # 4. Check Availability for tomorrow
        tomorrow = datetime.now(JST) + timedelta(days=1)
        tomorrow_slots = get_available_slots(tomorrow, "ebisu", bookings)
        
        print(f"\n📅 Availability for {tomorrow.strftime('%Y-%m-%d')} (Ebisu):")
        if tomorrow_slots:
            print(f"   ✅ {len(tomorrow_slots)} slots available")
            for slot in tomorrow_slots[:3]:
                print(f"   - {slot.strftime('%H:%M')}")
            if len(tomorrow_slots) > 3:
                print("     ...")
        else:
            print("   ❌ No slots available")
            
        print("\n🎉 Test completed successfully!")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_connection()
