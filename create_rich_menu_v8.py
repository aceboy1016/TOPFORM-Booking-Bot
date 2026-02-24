from PIL import Image, ImageDraw, ImageFont
import os

# Ultra Premium Config
WIDTH = 2500
HEIGHT = 1686

# Color Palette
BG_COLOR = (242, 242, 247)    # System Gray 6 (iOS style background)
CARD_COLOR = (255, 255, 255)  # White cards
TEXT_COLOR = (28, 28, 30)     # Dark Gray
ACCENT_COLOR = (52, 199, 89)  # Emerald Green
ACCENT_BG = (235, 255, 240)   # Light Green tint
DIVIDER_COLOR = (209, 209, 214)# Border color
MUTE_TEXT_COLOR = (142, 142, 147) # Gray

def draw_calendar_icon(draw, cx, cy, size=180, color=TEXT_COLOR):
    w, h = size, size * 0.9
    x, y = cx - w/2, cy - h/2
    draw.rounded_rectangle([x, y, x+w, y+h], radius=24, outline=color, width=14)
    header_h = h * 0.3
    draw.line([x, y+header_h, x+w, y+header_h], fill=color, width=10)

def draw_refresh_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    # Balanced circular arrow
    bbox = [cx - size/2, cy - size/2, cx + size/2, cy + size/2]
    draw.arc(bbox, start=30, end=330, fill=color, width=14)
    tip_x, tip_y = cx + size/2 * 0.9, cy - size/2 * 0.3
    draw.polygon([(tip_x, tip_y), (tip_x - 35, tip_y + 10), (tip_x - 10, tip_y + 40)], fill=color)

def draw_plus_icon(draw, cx, cy, size=180, color=TEXT_COLOR):
    w = 18
    draw.line([cx - size/2, cy, cx + size/2, cy], fill=color, width=w)
    draw.line([cx, cy - size/2, cx, cy + size/2], fill=color, width=w)

def draw_list_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    w, h = size * 0.8, size
    x, y = cx - w/2, cy - h/2
    draw.rounded_rectangle([x, y, x+w, y+h], radius=15, outline=color, width=14)
    for i in range(3):
        ly = y + h * 0.45 + (i * h * 0.22)
        draw.line([x + 35, ly, x + w - 35, ly], fill=color, width=10)

def create_premium_menu_v8():
    print("Generating card-style premium image v8...")
    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 1. Card Layout Logic
    padding = 40
    card_w = (WIDTH // 2) - (padding * 2)
    card_h = (HEIGHT // 2) - (padding * 2) - 20 # Leave room for bottom notice

    # Positions for 4 cards
    card_positions = [
        (padding, padding), # TL
        (WIDTH // 2 + padding, padding), # TR
        (padding, HEIGHT // 2 + padding - 20), # BL
        (WIDTH // 2 + padding, HEIGHT // 2 + padding - 20) # BR
    ]

    font_paths = ["/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc", "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"]
    font, label_font, notice_font = ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            font = ImageFont.truetype(path, 100)      # "早見表"
            label_font = ImageFont.truetype(path, 65)   # "空き状況をみる"
            notice_font = ImageFont.truetype(path, 40)
            break

    items = [
        {"action": "空き状況をみる", "title": "早見表", "icon": draw_calendar_icon},
        {"action": "予定を変更・消す", "title": "予約変更", "icon": draw_refresh_icon},
        {"action": "新しく予約したい", "title": "予約する", "icon": draw_plus_icon, "accent": True},
        {"action": "予約内容をみる", "title": "予約確認", "icon": draw_list_icon}
    ]

    for i, item in enumerate(items):
        pos_x, pos_y = card_positions[i]
        
        # Draw Shadow / Border Card
        # Main Card
        card_rect = [pos_x, pos_y, pos_x + card_w, pos_y + card_h]
        if item.get("accent"):
            draw.rounded_rectangle(card_rect, radius=50, fill=ACCENT_BG, outline=ACCENT_COLOR, width=4)
        else:
            draw.rounded_rectangle(card_rect, radius=50, fill=CARD_COLOR, outline=DIVIDER_COLOR, width=4)

        # Content Center
        cx = pos_x + card_w // 2
        cy = pos_y + card_h // 2
        
        # Action Label (Top of Card)
        draw.text((cx, pos_y + 120), item["action"], font=label_font, fill=MUTE_TEXT_COLOR, anchor="mm")
        
        # Icon (Middle of Card)
        icon_y = cy + 20
        if item.get("accent"):
            draw.ellipse([cx - 150, icon_y - 150, cx + 150, icon_y + 150], fill=ACCENT_COLOR)
            item["icon"](draw, cx, icon_y, size=150, color=(255, 255, 255))
        else:
            item["icon"](draw, cx, icon_y, size=180, color=TEXT_COLOR)
        
        # Main Title (Bottom of Card)
        draw.text((cx, pos_y + card_h - 120), item["title"], font=font, fill=TEXT_COLOR, anchor="mm")

    # Bottom Notice
    draw.text((WIDTH // 2, HEIGHT - 55), "※カレンダーの反映に1分ほどかかる場合があります", font=notice_font, fill=MUTE_TEXT_COLOR, anchor="mm")

    img.save("rich_menu_v8.jpg", "JPEG", quality=95)
    print("Created rich_menu_v8.jpg")

if __name__ == "__main__":
    create_premium_menu_v8()
