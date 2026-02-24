from PIL import Image, ImageDraw, ImageFont
import os

# Ultra Premium Config
WIDTH = 2500
HEIGHT = 1686

def create_premium_menu_v10():
    print("Generating refined premium image v10 based on photo icons and v8 style...")
    
    # 1. Colors (v8 Palette)
    BG_COLOR = (242, 242, 247)    # System Gray 6
    CARD_COLOR = (255, 255, 255)  # White Card
    TEXT_COLOR = (28, 28, 30)     # Dark Gray
    ACCENT_COLOR = (52, 199, 89)  # Emerald Green (v8)
    ACCENT_BG = (235, 255, 240)   # Light Green tint
    DIVIDER_COLOR = (209, 209, 214)# Border
    MUTE_TEXT_COLOR = (142, 142, 147) # Gray

    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Load Fonts
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    ]
    font, label_font, notice_font = ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            font = ImageFont.truetype(path, 100)      # Title
            label_font = ImageFont.truetype(path, 60)   # Action Label
            notice_font = ImageFont.truetype(path, 40)
            break

    # 2. Icon Drawer Functions (Based on the Photo)
    
    def draw_calendar_plus(draw, cx, cy, color):
        size = 180
        w, h = size, size * 0.9
        x, y = cx - w/2, cy - h/2
        # Main Calendar
        draw.rounded_rectangle([x, y, x+w, y+h], radius=20, outline=color, width=14)
        draw.line([x, y + h*0.3, x+w, y + h*0.3], fill=color, width=10)
        # Internal grid dots
        for i in range(3):
            for j in range(2):
                dx = x + 40 + i*50
                dy = y + 80 + j*40
                draw.rectangle([dx, dy, dx+10, dy+10], fill=color)
        # The small (+) circle in the photo
        pcx, pcy = x + w - 10, y + h - 10
        draw.ellipse([pcx-50, pcy-50, pcx+50, pcy+50], fill=CARD_COLOR, outline=color, width=8)
        draw.line([pcx-25, pcy, pcx+25, pcy], fill=color, width=8)
        draw.line([pcx, pcy-25, pcx, pcy+25], fill=color, width=8)

    def draw_refresh_custom(draw, cx, cy, color):
        size = 180
        bbox = [cx - size/2, cy - size/2, cx + size/2, cy + size/2]
        # Circular arrows from photo
        draw.arc(bbox, start=30, end=150, fill=color, width=15)
        draw.arc(bbox, start=210, end=330, fill=color, width=15)
        # Arrow heads
        # Upper Right
        draw.polygon([(cx + 80, cy - 60), (cx + 120, cy - 100), (cx + 130, cy - 40)], fill=color)
        # Lower Left
        draw.polygon([(cx - 80, cy + 60), (cx - 120, cy + 100), (cx - 130, cy + 40)], fill=color)

    def draw_check_circle(draw, cx, cy, color):
        size = 180
        # Circle
        draw.ellipse([cx - size/2, cy - size/2, cx + size/2, cy + size/2], outline=color, width=15)
        # Checkmark
        draw.line([cx - 40, cy, cx - 10, cy + 30], fill=color, width=15)
        draw.line([cx - 10, cy + 30, cx + 50, cy - 30], fill=color, width=15)

    def draw_clipboard_check(draw, cx, cy, color):
        size = 180
        w, h = size * 0.8, size
        x, y = cx - w/2, cy - h/2
        # Clipboard body
        draw.rounded_rectangle([x, y, x+w, y+h], radius=15, outline=color, width=14)
        # Clip at top
        draw.rectangle([cx-40, y-10, cx+40, y+30], fill=CARD_COLOR, outline=color, width=10)
        # Checkmark inside
        draw.line([cx - 30, cy + 10, cx - 5, cy + 35], fill=color, width=14)
        draw.line([cx - 5, cy + 35, cx + 40, cy - 15], fill=color, width=14)

    # 3. Layout Cards
    padding = 45
    card_w = (WIDTH // 2) - (padding * 2)
    card_h = (HEIGHT // 2) - (padding * 2) - 20

    card_positions = [
        (padding, padding), # TL
        (WIDTH // 2 + padding, padding), # TR
        (padding, HEIGHT // 2 + padding - 20), # BL
        (WIDTH // 2 + padding, HEIGHT // 2 + padding - 20) # BR
    ]

    items = [
        {"action": "空き状況をみる", "title": "早見表", "func": draw_calendar_plus},
        {"action": "予定を変更・消す", "title": "予約変更", "func": draw_refresh_custom},
        {"action": "新しく予約したい", "title": "予約する", "func": draw_check_circle, "accent": True},
        {"action": "予約内容をみる", "title": "予約確認", "func": draw_clipboard_check}
    ]

    for i, item in enumerate(items):
        px, py = card_positions[i]
        cx = px + card_w // 2
        cy = py + card_h // 2
        
        # Card Background
        card_rect = [px, py, px + card_w, py + card_h]
        if item.get("accent"):
            draw.rounded_rectangle(card_rect, radius=60, fill=ACCENT_BG, outline=ACCENT_COLOR, width=5)
            ic_color = ACCENT_COLOR
        else:
            draw.rounded_rectangle(card_rect, radius=60, fill=CARD_COLOR, outline=DIVIDER_COLOR, width=5)
            ic_color = TEXT_COLOR

        # Content
        # Label
        draw.text((cx, py + 110), item["action"], font=label_font, fill=MUTE_TEXT_COLOR, anchor="mm")
        # Icon
        item["func"](draw, cx, cy + 10, ic_color)
        # Title
        draw.text((cx, py + card_h - 110), item["title"], font=font, fill=TEXT_COLOR, anchor="mm")

    # 4. Global Notice
    draw.text((WIDTH // 2, HEIGHT - 55), "※カレンダーの反映に1分ほどかかる場合があります", font=notice_font, fill=MUTE_TEXT_COLOR, anchor="mm")

    img.save("rich_menu_v10.jpg", "JPEG", quality=95)
    print("Created rich_menu_v10.jpg")

if __name__ == "__main__":
    create_premium_menu_v10()
