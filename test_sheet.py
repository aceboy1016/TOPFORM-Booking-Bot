import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

creds_file = "/Users/junya/hacomono-automation/google-credentials.json"
sheet_id = "17jOb7Jh8xIlsmG9RJjdc0GUKykBVxEVkxpyw92sWkjk"

try:
    with open(creds_file, "r") as f:
        creds_data = json.load(f)
    
    credentials = service_account.Credentials.from_service_account_info(
        creds_data, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=credentials)
    
    result = service.spreadsheets().values().get(spreadsheetId=sheet_id, range="A2:E5").execute()
    rows = result.get("values", [])
    print("Fetched rows:", rows)
except Exception as e:
    print("Error:", e)
