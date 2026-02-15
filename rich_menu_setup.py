"""
Setup Rich Menu for TopForm LINE Bot
Uses layout:
- Top (Full width): Schedule & Menu (Action: "早見表")
- Bottom Left (Half width): Booking (Action: "予約する")
- Bottom Right (Half width): My Page (Action: "予約確認")
"""
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    RichMenuRequest,
    RichMenuArea,
    RichMenuBounds,
    RichMenuSize,
    MessageAction,
)

try:
    from config import settings
except ImportError:
    print("Error: Could not import settings. Run this from project root.")
    sys.exit(1)

def setup_rich_menu(image_path):
    if not os.path.exists(image_path):
        print(f"Error: Image file not found at {image_path}")
        return

    configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
    
    with ApiClient(configuration) as api_client:
        messaging_api = MessagingApi(api_client)
        messaging_api_blob = MessagingApiBlob(api_client)

        print("Creating Rich Menu...")
        
        # Define areas
        # 2500 x 1686 (Standard Large)
        # Top: y=0, h=843
        # Bottom: y=843, h=843
        rich_menu_req = RichMenuRequest(
            size=RichMenuSize(width=2500, height=1686),
            selected=True,
            name="TopForm Menu v1",
            chat_bar_text="MENU",
            areas=[
                # 1. Schedule (Top)
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=0, width=2500, height=843),
                    action=MessageAction(label="早見表", text="早見表")
                ),
                # 2. Booking (Bottom Left)
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=843, width=1250, height=843),
                    action=MessageAction(label="予約する", text="予約する")
                ),
                # 3. Confirmation (Bottom Right)
                RichMenuArea(
                    bounds=RichMenuBounds(x=1250, y=843, width=1250, height=843),
                    action=MessageAction(label="予約確認", text="予約確認")
                )
            ]
        )

        try:
            # Create
            rich_menu_id = messaging_api.create_rich_menu(
                rich_menu_request=rich_menu_req
            ).rich_menu_id
            print(f"Created Rich Menu ID: {rich_menu_id}")

            # Upload Image
            print("Uploading image...")
            with open(image_path, "rb") as f:
                image_bytes = f.read()
                
            # Content type detection (simple)
            content_type = "image/jpeg"
            if image_path.lower().endswith(".png"):
                content_type = "image/png"
                
            messaging_api_blob.set_rich_menu_image(
                rich_menu_id=rich_menu_id,
                body=image_bytes,
                _content_type=content_type
            )
            print("Image uploaded successfully.")

            # Set as default
            print("Setting as default menu...")
            messaging_api.set_default_rich_menu(rich_menu_id=rich_menu_id)
            print("Done! The new rich menu has been applied.")

        except Exception as e:
            print(f"Failed to setup rich menu: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python rich_menu_setup.py <path_to_image_file>")
        print("Image requirement: 2500x1686, JPG or PNG, Max 1MB")
    else:
        setup_rich_menu(sys.argv[1])
