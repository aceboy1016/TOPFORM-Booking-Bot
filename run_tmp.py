import os, json, traceback, sys
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

try:
    load_dotenv()
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if not creds_json:
        print('No creds')
        sys.exit(1)
        
    if not creds_json.startswith('{'):
        import base64
        creds_json = base64.b64decode(creds_json).decode('utf-8')
        
    try:
        creds_dict = json.loads(creds_json, strict=False)
    except:
        import re
        fixed = re.sub(r'("private_key":\s*)"((?:\\.|[^"\\])*)"', lambda m: m.group(1) + '"' + m.group(2).replace('\n', '\\n') + '"', creds_json)
        creds_dict = json.loads(fixed)
        
    creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])
    service = build('sheets', 'v4', credentials=creds)
    
    SPREADSHEET_ID = '17jOb7Jh8xIlsmG9RJjdc0GUKykBVxEVkxpyw92sWkjk'
    
    try:
        service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={'requests': [{'addSheet': {'properties': {'title': 'キャンセル待ち'}}}]}).execute()
        print('Sheet added')
    except Exception as e:
        print('Sheet probably exists:', str(e))
        
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range='キャンセル待ち!A1:G1',
        valueInputOption='USER_ENTERED',
        body={'values': [['登録日時', '日付', '時間', '店舗', '名前', 'LINE User ID', 'ステータス']]}
    ).execute()
    print('Headers written')
except Exception as e:
    traceback.print_exc()
