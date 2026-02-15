
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sheets_service import sheets_service
from config import settings

print(f"Checking Spreadsheet: {settings.GOOGLE_SHEET_ID}")

try:
    sheets_service.initialize()
    if not sheets_service._service:
        print("❌ Service not initialized")
        sys.exit(1)
        
    # Read header row
    result = sheets_service._service.spreadsheets().values().get(
        spreadsheetId=settings.GOOGLE_SHEET_ID, range="A1:Z1"
    ).execute()
    
    header = result.get("values", [[]])[0]
    print(f"✅ Sheet Header: {header}")
    
    # Read first 5 rows of data
    result_data = sheets_service._service.spreadsheets().values().get(
        spreadsheetId=settings.GOOGLE_SHEET_ID, range="A2:E6"
    ).execute()
    
    rows = result_data.get("values", [])
    print(f"✅ Data Preview ({len(rows)} rows):")
    for row in rows:
        print(row)

except Exception as e:
    print(f"❌ Error: {e}")
