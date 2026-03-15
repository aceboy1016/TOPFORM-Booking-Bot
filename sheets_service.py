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
        # Cache duration: 1 minute (짧くしてリアルタイム性を向上)
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
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
            self._service = build("sheets", "v4", credentials=credentials)
            print("✅ Google Sheets Service initialized")
        except Exception as e:
            print(f"❌ Failed to initialize Sheets Service: {e}")

    def fetch_customer_master(self, force_refresh: bool = False) -> List[Dict]:
        """
        Fetch customer master data from spreadsheet.
        Returns a list of dicts:
        {
            "name": "石原 順二",
            "line_id": "U123...",
            "store_pref": "ebisu" | "hanzoomon",
            "room_pref": "A" | "B" | None
        }
        """
        if not self._service:
            self.initialize()
            if not self._service:
                return []

        # Check cache
        now = datetime.now()
        if (
            not force_refresh
            and self._cached_data is not None
            and self._last_fetch
            and (now - self._last_fetch).total_seconds() < self._cache_ttl
        ):
            return self._cached_data

        try:
            # Assume data is in the first sheet, from A2 to E (skip header)
            # Adjust range as needed based on actual sheet structure
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
                if len(row) < 2:  # Must have Name and LINE ID at least
                    continue
                
                # Column mapping based on actual sheet structure:
                # A (0): 顧客名
                # B (1): LINE ID
                # C (2): 恵比寿 (◯/✖️)
                # D (3): 半蔵門 (◯/✖️)
                # E (4): 優先スタジオ (A/B)
                
                name = row[0].strip()
                line_id = row[1].strip()
                ebisu_flag = row[2].strip() if len(row) > 2 else ""
                hanzomon_flag = row[3].strip() if len(row) > 3 else ""
                room_raw = row[4].strip() if len(row) > 4 else ""
                
                circle_marks = ["◯", "○", "〇", "🟢"]
                cross_marks = ["✖️", "✖", "×", "❌"]
                
                ebisu_ok = any(mark in ebisu_flag for mark in circle_marks)
                ebisu_ng = any(mark in ebisu_flag for mark in cross_marks)
                hanzomon_ok = any(mark in hanzomon_flag for mark in circle_marks)
                hanzomon_ng = any(mark in hanzomon_flag for mark in cross_marks)
                
                # Determine store preference
                store_pref = None
                if ebisu_ok and (hanzomon_ng or not hanzomon_ok):
                    store_pref = "ebisu"
                elif hanzomon_ok and (ebisu_ng or not ebisu_ok):
                    store_pref = "hanzoomon"
                # If both are OK, store_pref remains None (let user choose)

                # Determine room preference for Ebisu
                room_pref = None
                if "A" in room_raw:
                    room_pref = "A"
                elif "B" in room_raw:
                    room_pref = "B"
                
                customers.append({
                    "name": name,
                    "line_id": line_id,
                    "store_pref": store_pref,
                    "room_pref": room_pref,
                    "ebisu_ok": "◯" in ebisu_flag,
                    "hanzomon_ok": "◯" in hanzomon_flag
                })
            
            print(f"✅ Fetched {len(customers)} customers from sheet")
            self._cached_data = customers
            self._last_fetch = now
            return customers

        except Exception as e:
            print(f"❌ Failed to fetch customer master: {e}")
            # Return empty list or previous cache if available
            return self._cached_data or []

    def get_customer_by_line_id(self, line_id: str) -> Optional[Dict]:
        """Get customer info by LINE ID."""
        customers = self.fetch_customer_master()
        for c in customers:
            if c["line_id"] == line_id:
                return c
        # Not found in cache — try a force refresh once before giving up
        customers = self.fetch_customer_master(force_refresh=True)
        for c in customers:
            if c["line_id"] == line_id:
                return c
        return None

    def force_refresh(self) -> int:
        """Force refresh the cache and return number of customers loaded."""
        customers = self.fetch_customer_master(force_refresh=True)
        return len(customers)

# Singleton instance
sheets_service = SheetsService()
