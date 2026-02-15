from PIL import Image, ImageDraw, ImageFont
import os

# Config
WIDTH = 2500
HEIGHT = 1686
# Brand Colors
WHITE = (255, 255, 255)
DARK_NAVY = (22, 33, 62)   # #16213e
MINT = (46, 196, 182)      # #2ec4b6
LIGHT_GRAY = (240, 240, 240)
DIVIDER = (200, 200, 200)

def create_image():
    print("Generating bright image...")
    img = Image.new('RGB', (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)

    # Define Sections
    # (Text, Center X, Center Y, BgColor, TextColor)
    # 1. Top Left: Schedule
    # 2. Top Right: Change
    # 3. Bottom Left: Book (Highlighted)
    # 4. Bottom Right: Check
    
    # Draw Backgrounds
    # Bottom Left (Booking) Highlight
    draw.rectangle([(0, HEIGHT//2), (WIDTH//2, HEIGHT)], fill=MINT)

    # Draw dividers
    draw.line([(WIDTH//2, 0), (WIDTH//2, HEIGHT)], fill=DIVIDER, width=6)
    draw.line([(0, HEIGHT//2), (WIDTH, HEIGHT//2)], fill=DIVIDER, width=6)

    # Font handling
    font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
    font = None
    try:
        if os.path.exists(font_path):
            font = ImageFont.truetype(font_path, 130)
        else:
            font = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 130)
    except:
        font = ImageFont.load_default()

    sections = [
        ("📅 早見表", WIDTH * 0.25, HEIGHT * 0.25, DARK_NAVY),
        ("🔄 予約変更", WIDTH * 0.75, HEIGHT * 0.25, DARK_NAVY),
        ("➕ 予約する", WIDTH * 0.25, HEIGHT * 0.75, WHITE), # White text on Mint bg
        ("📋 予約確認", WIDTH * 0.75, HEIGHT * 0.75, DARK_NAVY),
    ]

    for text, cx, cy, color in sections:
        # Get text size
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = cx - text_width / 2
        y = cy - text_height / 2
        
        draw.text((x, y), text, font=font, fill=color)

    # Save
    output_path = "rich_menu_v4.jpg"
    img.save(output_path, "JPEG", quality=95)
    print(f"Created {output_path}")

if __name__ == "__main__":
    create_image()
