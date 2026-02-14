"""
CREATE STYLISH RICH MENU IMAGE
Python Pillowを使ってリッチメニュー画像を生成するスクリプト

デザイン:
- 背景: 深いチャコールグレー (#1a1a1a) + 微細なノイズ/グラデーション
- 文字色: 白 (#ffffff)
- アクセント: ゴールド (#ffd700)
- レイアウト:
  ---------------------------------
  |        📋 石原早見表          | (予約状況Web)
  |---------------------------------|
  |  📅 予約する   |  📖 予約確認  |
  ---------------------------------
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import random

# Constants
WIDTH = 2500
HEIGHT = 1686
OUTPUT_PATH = "assets/rich_menu.jpg"

# Colors
BG_COLOR = (20, 20, 30)       # Dark Navy/Black
ACCENT_COLOR = (255, 215, 0)  # Gold
TEXT_COLOR = (255, 255, 255)  # White
BTN_BG_COLOR = (40, 40, 50)   # Slightly lighter gray for buttons
BORDER_COLOR = (60, 60, 80)   # Subtle border

def create_gradient(width, height, start_color, end_color):
    base = Image.new('RGB', (width, height), start_color)
    top = Image.new('RGB', (width, height), end_color)
    mask = Image.new('L', (width, height))
    mask_data = []
    for y in range(height):
        mask_data.extend([int(255 * (y / height))] * width)
    mask.putdata(mask_data)
    base.paste(top, (0, 0), mask)
    return base

def draw_rounded_rect(draw, box, radius, fill, outline=None, width=0):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=width)

def main():
    # Make sure assets directory exists
    os.makedirs("assets", exist_ok=True)

    # 1. Background (Subtle Gradient)
    img = create_gradient(WIDTH, HEIGHT, (10, 10, 15), (30, 30, 40))
    draw = ImageDraw.Draw(img)

    # 2. Add subtle texture/noise (optional, skipping for clean look)
    
    # 3. Define Areas
    # Area 1: Top (Hayamihyo)
    top_area = (50, 50, WIDTH - 50, 843 - 25)
    
    # Area 2: Bottom Left (Booking)
    bl_area = (50, 843 + 25, 1250 - 25, HEIGHT - 50)
    
    # Area 3: Bottom Right (Check Booking)
    br_area = (1250 + 25, 843 + 25, WIDTH - 50, HEIGHT - 50)

    # Draw Button Backgrounds (Rounded)
    radius = 40
    draw_rounded_rect(draw, top_area, radius, BTN_BG_COLOR, outline=ACCENT_COLOR, width=3)
    draw_rounded_rect(draw, bl_area, radius, BTN_BG_COLOR, outline=BORDER_COLOR, width=2)
    draw_rounded_rect(draw, br_area, radius, BTN_BG_COLOR, outline=BORDER_COLOR, width=2)

    # 4. Add Text
    # Try to load a nice font, fallback to default
    try:
        # Mac standard font
        font_large = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 100, index=0)
        font_medium = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 80, index=0)
        font_small = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 50, index=0)
    except:
        try:
             # Typical linux font path
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 100)
            font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 50)
        except:
            print("⚠️ Custom font not found, using default.")
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()

    # Helper to center text
    def draw_centered_text(box, text, font, color=(255, 255, 255), y_offset=0):
        x0, y0, x1, y1 = box
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        
        # Get text size
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        
        draw.text((cx - w/2, cy - h/2 + y_offset), text, font=font, fill=color)

    # Top Area Text
    draw_centered_text(top_area, "📋 石原早見表", font_large, y_offset=-40)
    draw_centered_text(top_area, "SCHEDULE & MENU", font_small, color=(180, 180, 180), y_offset=60)
    
    # Bottom Left Text
    draw_centered_text(bl_area, "📅 予約する", font_medium, y_offset=-30)
    draw_centered_text(bl_area, "BOOKING", font_small, color=(180, 180, 180), y_offset=50)

    # Bottom Right Text
    draw_centered_text(br_area, "📖 予約確認", font_medium, y_offset=-30)
    draw_centered_text(br_area, "MY PAGE", font_small, color=(180, 180, 180), y_offset=50)

    # 5. Save
    img.save(OUTPUT_PATH, quality=95)
    print(f"✅ Image created at {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
