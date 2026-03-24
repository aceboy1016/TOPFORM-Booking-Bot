import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
if not creds_json:
    print("Error: GOOGLE_CREDENTIALS_JSON not found in .env")
    exit(1)

# Base64エンコードの場合はデコード
if not creds_json.startswith('{'):
    import base64
    creds_json = base64.b64decode(creds_json).decode('utf-8')

# パース時のエスケープ問題を回避
try:
    creds_dict = json.loads(creds_json, strict=False)
except:
    import re
    # \nをエスケープ
    fixed_json = re.sub(r'("private_key":\s*)"((?:\\.|[^"\\])*)"', lambda m: m.group(1) + '"' + m.group(2).replace('\n', '\\n') + '"', creds_json)
    creds_dict = json.loads(fixed_json)

creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])
service = build('sheets', 'v4', credentials=creds)

SPREADSHEET_ID = "17jOb7Jh8xIlsmG9RJjdc0GUKykBVxEVkxpyw92sWkjk"

# 「キャンセル待ち」シートの追加
add_sheet_body = {
    "requests": [{
        "addSheet": {
            "properties": {
                "title": "キャンセル待ち"
            }
        }
    }]
}

try:
    res = service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=add_sheet_body).execute()
    print("✅ シート「キャンセル待ち」を作成しました")
except Exception as e:
    if "already exists" in str(e):
        print("💡 シート「キャンセル待ち」は既に存在します")
    else:
        print("⚠️ エラー:", e)

# ヘッダーを1行目に書き込む
headers = [["登録日時", "日付", "時間", "店舗", "名前", "LINE User ID", "ステータス"]]
update_body = {
    "values": headers
}
service.spreadsheets().values().update(
    spreadsheetId=SPREADSHEET_ID,
    range="キャンセル待ち!A1:G1",
    valueInputOption="USER_ENTERED",
    body=update_body
).execute()
print("✅ ヘッダー行を書き込みました")

# 1行目を固定する
try:
    sheet_metadata = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_id = next(s['properties']['sheetId'] for s in sheet_metadata['sheets'] if s['properties']['title'] == "キャンセル待ち")
    
    freeze_body = {
        "requests": [{
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {
                        "frozenRowCount": 1
                    }
                },
                "fields": "gridProperties.frozenRowCount"
            }
        }]
    }
    service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=freeze_body).execute()
    print("✅ 1行目を固定（フリーズ）しました")
except Exception as e:
    print("⚠️ 行固定に失敗:", e)

print("🎉 スプレッドシートのセットアップがすべて完了しました！")
