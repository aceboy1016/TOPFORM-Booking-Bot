import requests
import json
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

try:
    from config import settings
except ImportError:
    print("Error: Could not import settings.")
    sys.exit(1)

token = settings.LINE_CHANNEL_ACCESS_TOKEN
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

def run():
    print("Creating Rich Menu using simple_setup.py...")
    # 1. Create Rich Menu
    menu_data = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": "TopForm Set V2",
        "chatBarText": "MENU",
        "areas": [
            {
              "bounds": {"x": 0, "y": 0, "width": 2500, "height": 843},
              "action": {"type": "message", "text": "早見表"}
            },
            {
              "bounds": {"x": 0, "y": 843, "width": 1250, "height": 843},
              "action": {"type": "message", "text": "予約する"}
            },
            {
              "bounds": {"x": 1250, "y": 843, "width": 1250, "height": 843},
              "action": {"type": "message", "text": "予約確認"}
            }
        ]
    }

    try:
        resp = requests.post("https://api.line.me/v2/bot/richmenu", headers=headers, json=menu_data)
        resp.raise_for_status()
        rm_id = resp.json().get("richMenuId")
        print(f"Created ID: {rm_id}")

        if rm_id:
            # 2. Upload Image
            print("Processing Image (resizing)...")
            from PIL import Image
            
            # Resize
            # Use generated image rich_menu_v2.jpg if available, else png
            target_img = "rich_menu_v2.jpg"
            if not os.path.exists(target_img):
                target_img = "rich_menu.png"
            
            if not os.path.exists(target_img):
                print(f"{target_img} not found!")
                return

            with Image.open(target_img) as img:
                # Force resize to exact dimensions required by LINE API
                # 2500x1686 is standard large size
                new_img = img.resize((2500, 1686), Image.Resampling.LANCZOS)
                # Convert to RGB if RGBA (PNG) to save as JPEG
                if new_img.mode == 'RGBA':
                    new_img = new_img.convert('RGB')
                
                new_img.save("rich_menu_resized.jpg", "JPEG", quality=90)
            
            with open("rich_menu_resized.jpg", "rb") as f:
                img_data = f.read()
            
            h_img = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/jpeg"
            }
            resp_img = requests.post(f"https://api-data.line.me/v2/bot/richmenu/{rm_id}/content", headers=h_img, data=img_data)
            print(f"Upload Image Response: {resp_img.status_code} {resp_img.text}")

            if resp_img.status_code == 200:
                # 3. Set Default
                print("Setting Default...")
                resp_def = requests.post(f"https://api.line.me/v2/bot/user/all/richmenu/{rm_id}", headers=headers)
                print(f"Set Default Response: {resp_def.status_code} {resp_def.text}")
            else:
                print("Skipping set default due to upload failure.")
            
    except Exception as e:
        print(f"Error: {e}")
        if 'resp' in locals():
            print(resp.text)

if __name__ == "__main__":
    run()
