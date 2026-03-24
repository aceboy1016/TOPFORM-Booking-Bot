"""
TOPFORM LINE Bot - Google Sheets Service
顧客マスタ（スプレッドシート）を読み込んでユーザー情報を提供するサービス
"""

import json
from datetime import datetime
from typing import Optional, Dict, List

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import settings


class SheetsService:
    """Google Sheets API サービス"""

    def __init__(self):
        self._service = None
        self._sheet_id = settings.GOOGLE_SHEET_ID
        self._cached_data = None
        self._last_fetch = None
        self._cache_ttl = 60

    def initialize(self):
        """Initialize the Google Sheets API client."""
        creds_json = settings.GOOGLE_CREDENTIALS_JSON
        if not creds_json:
            print("⚠️ GOOGLE_CREDENTIALS_JSON is not set, skipping Sheets init")
            return

        # Decode base64 if needed
        if not creds_json.startswith("{"):
            import base64
            try:
                creds_json = base64.b64decode(creds_json).decode("utf-8")
            except Exception:
                pass

        try:
            creds_data = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(
                creds_data,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            self._service = build("sheets", "v4", credentials=credentials)
            print("✅ Google Sheets Service initialized")
        except Exception as e:
            print(f"❌ Failed to initialize Sheets Service: {e}")

    def fetch_customer_master(self, force_refresh: bool = False) -> List[Dict]:
        """Fetch customer master data from spreadsheet."""
        if not self._service:
            self.initialize()
            if not self._service:
                return []

        now = datetime.now()
        if (
            not force_refresh
            and self._cached_data is not None
            and self._last_fetch
            and (now - self._last_fetch).total_seconds() < self._cache_ttl
        ):
            return self._cached_data

        try:
            sheet_range = "A2:E"
            result = (
                self._service.spreadsheets()
                .values()
                .get(spreadsheetId=self._sheet_id, range=sheet_range)
                .execute()
            )
            rows = result.get("values", [])
            
            customers = []
            for row in rows:
                if len(row) < 2: continue
                
                name = row[0].strip()
                line_id = row[1].strip()
                ebisu_flag = row[2].strip() if len(row) > 2 else ""
                hanzomon_flag = row[3].strip() if len(row) > 3 else ""
                room_raw = row[4].strip() if len(row) > 4 else ""
                
                circle_marks = ["◯", "○", "〇", "🟢"]
                cross_marks = ["✖️", "✖", "×", "❌"]
                
                ebisu_ok = any(mark in ebisu_flag for mark in circle_marks)
                hanzomon_ok = any(mark in hanzomon_flag for mark in circle_marks)
                
                store_pref = None
                if ebisu_ok and not hanzomon_ok: store_pref = "ebisu"
                elif hanzomon_ok and not ebisu_ok: store_pref = "hanzoomon"

                room_pref = "A" if "A" in room_raw else "B" if "B" in room_raw else None
                
                customers.append({
                    "name": name,
                    "line_id": line_id,
                    "store_pref": store_pref,
                    "room_pref": room_pref,
                    "ebisu_ok": ebisu_ok,
                    "hanzomon_ok": hanzomon_ok
                })
            
            self._cached_data = customers
            self._last_fetch = now
            return customers
        except Exception as e:
            print(f"❌ Failed to fetch customer master: {e}")
            return self._cached_data or []

    def get_customer_by_line_id(self, line_id: str) -> Optional[Dict]:
        """Get customer info by LINE ID."""
        customers = self.fetch_customer_master()
        for c in customers:
            if c["line_id"] == line_id:
                return c
        return None

    def force_refresh(self) -> int:
        """Force refresh the cache and return number of customers loaded."""
        customers = self.fetch_customer_master(force_refresh=True)
        return len(customers)

    def fetch_waitlist(self) -> List[Dict]:
        """キャンセル待ちリストを取得する。"""
        if not self._service:
            self.initialize()
            if not self._service: return []

        try:
            sheet_range = "キャンセル待ち!A2:G"
            result = (
                self._service.spreadsheets().values().get(spreadsheetId=self._sheet_id, range=sheet_range).execute()
            )
            rows = result.get("values", [])
            
            waitlist = []
            for i, row in enumerate(rows):
                row_idx = i + 2
                row_data = row + [""] * (7 - len(row))
                status = row_data[6].strip()
                if status == "待機中":
                    waitlist.append({
                        "row_index": row_idx,
                        "registered_at": row_data[0],
                        "date": row_data[1],
                        "time": row_data[2],
                        "store": row_data[3],
                        "name": row_data[4],
                        "line_id": row_data[5],
                        "status": status
                    })
            return waitlist
        except Exception as e:
            print(f"❌ Failed to fetch waitlist: {e}")
            return []

    def update_waitlist_status(self, row_index: int, status: str):
        """キャンセル待ちのステータスを更新する。"""
        if not self._service: return
        try:
            cell_range = f"キャンセル待ち!G{row_index}"
            body = {"values": [[status]]}
            self._service.spreadsheets().values().update(
                spreadsheetId=self._sheet_id, range=cell_range,
                valueInputOption="USER_ENTERED", body=body
            ).execute()
        except Exception as e:
            print(f"❌ Failed to update waitlist status: {e}")

# Singleton instance
sheets_service = SheetsService()
