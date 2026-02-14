"""
SETUP RICH MENU - TOPFORM LINE Bot
公式LINEのリッチメニューを登録・設定するスクリプト

レイアウト:
---------------------------------
|            早見表 (Web)        |
|---------------------------------|
|    予約する    |    予約確認    |
---------------------------------
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    RichMenuRequest,
    RichMenuArea,
    RichMenuBounds,
    RichMenuSize,
    PostbackAction,
    URIAction,
    MessageAction,
)

from config import settings


def setup_rich_menu():
    """Create and set the default rich menu."""
    if not settings.LINE_CHANNEL_ACCESS_TOKEN:
        print("❌ Error: LINE_CHANNEL_ACCESS_TOKEN is not set.")
        return

    configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_blob = MessagingApiBlob(api_client)

        # 1. Create Rich Menu Object
        # Size: 2500x1686 (Standard Large) or 2500x843 (Small/Half)
        # Using a compact layout: 2500x843 (Half height)
        # Top half: Hayamihyo (Full width)
        # Bottom half: Booking (Left) | Check Booking (Right)
        
        # But for better visibility, let's use full height 2500x1686
        # Area 1: Top (0,0) - (2500, 843) -> Hayamihyo
        # Area 2: Bottom Left (0, 843) - (1250, 843) -> Booking
        # Area 3: Bottom Right (1250, 843) - (1250, 843) -> Check Booking

        print("🚀 Creating Rich Menu...")
        
        rich_menu_to_create = RichMenuRequest(
            size=RichMenuSize(width=2500, height=1686),
            selected=True,
            name="TOPFORM Main Menu",
            chat_bar_text="メニューを開く",
            areas=[
                # 1. 石原早見表 (上半分全体)
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=0, width=2500, height=843),
                    action=URIAction(label="早見表", uri=settings.HAYAMIHYO_URL)
                ),
                # 2. 予約する (下段左)
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=843, width=1250, height=843),
                    action=MessageAction(label="予約する", text="予約する")
                ),
                # 3. 予約確認 (下段右)
                RichMenuArea(
                    bounds=RichMenuBounds(x=1250, y=843, width=1250, height=843),
                    action=MessageAction(label="予約確認", text="予約確認")
                )
            ]
        )

        rich_menu_id = line_bot_api.create_rich_menu(rich_menu_request=rich_menu_to_create).rich_menu_id
        print(f"✅ Created Rich Menu ID: {rich_menu_id}")

        # 2. Upload Image
        # Note: You need a valid image file. 
        # For now, we'll skip this if no image is provided, but in production you need one.
        image_path = Path(__file__).parent.parent / "assets" / "rich_menu.jpg"
        
        if image_path.exists():
            print(f"🖼 Uploading image from {image_path}...")
            
            # Determine content type (jpeg/png)
            content_type = "image/jpeg"
            if str(image_path).endswith(".png"):
                content_type = "image/png"

            # SDK v3 upload method has issues with binary data serialization
            # Using requests directly for image upload
            import requests
            
            url = f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content"
            headers = {
                "Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": content_type
            }
            
            with open(image_path, 'rb') as f:
                response = requests.post(url, headers=headers, data=f)
                
            if response.status_code == 200:
                print("✅ Image uploaded.")
            else:
                print(f"❌ Image upload failed: {response.text}")
        else:
            print(f"⚠️ Warning: Image file not found at {image_path}")
            print("   Please place a 2500x1686 JPEG/PNG image there and run this script again.")
            print("   Or upload an image manually via LINE Official Account Manager.")

        # 3. Set as Default
        line_bot_api.set_default_rich_menu(rich_menu_id=rich_menu_id)
        print("✅ Set as default rich menu.")


if __name__ == "__main__":
    setup_rich_menu()
