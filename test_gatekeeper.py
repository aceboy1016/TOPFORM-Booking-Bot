import asyncio
import os
from database import db
from sheets_service import sheets_service

# モックのための設定
import config
config.settings.DATABASE_PATH = "./topform_line.db"

async def test():
    await db.init_db()
    users = await db.get_all_users()
    print(f"Total users in DB: {len(users)}")
    if users:
        print("Sample user:", dict(users[-1]))
        
    customers = sheets_service.fetch_customer_master()
    print(f"Total customers in Sheets: {len(customers)}")
    if customers:
        print("Sample customer:", customers[-1])

    # 特定のテストユーザーのLINE IDで Gatekeeper を通過できるかチェック
    # (ここでは 山田 知世さん: Uacf6b9f8d5c3eb4caa01369cf425c8f4)
    test_id = "Uacf6b9f8d5c3eb4caa01369cf425c8f4"
    customer = sheets_service.get_customer_by_line_id(test_id)
    print(f"Gatekeeper check for {test_id}: {'Pass' if customer else 'Fail'}")

asyncio.run(test())
