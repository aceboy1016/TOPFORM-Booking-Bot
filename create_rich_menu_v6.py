from PIL import Image, ImageDraw, ImageFont
import os

# Ultra Premium Config
WIDTH = 2500
HEIGHT = 1686

# Color Palette
BG_COLOR = (248, 249, 250)    # Off-White
TEXT_COLOR = (28, 28, 30)     # Dark Gray
ACCENT_COLOR = (52, 199, 89)  # Emerald Green
ACCENT_BG = (235, 255, 240)   # Light Green tint
DIVIDER_COLOR = (229, 229, 234)# Divider
MUTE_TEXT_COLOR = (142, 142, 147) # Gray for sub-labels

def draw_calendar_icon(draw, cx, cy, size=180, color=TEXT_COLOR):
    w, h = size, size * 0.9
    x, y = cx - w/2, cy - h/2
    draw.rounded_rectangle([x, y, x+w, y+h], radius=20, outline=color, width=12)
    header_h = h * 0.3
    draw.line([x, y+header_h, x+w, y+header_h], fill=color, width=8)
    ring_x_offset = w * 0.25
    draw.line([x+ring_x_offset, y-10, x+ring_x_offset, y+20], fill=color, width=12)
    draw.line([x+w-ring_x_offset, y-10, x+w-ring_x_offset, y+20], fill=color, width=12)

def draw_refresh_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    bbox = [cx - size/2, cy - size/2, cx + size/2, cy + size/2]
    draw.arc(bbox, start=30, end=330, fill=color, width=12)
    tip_x, tip_y = cx + size/2 * 0.9, cy - size/2 * 0.3
    draw.polygon([(tip_x, tip_y), (tip_x - 30, tip_y + 10), (tip_x - 10, tip_y + 35)], fill=color)
    tip_x, tip_y = cx - size/2 * 0.9, cy + size/2 * 0.3
    draw.polygon([(tip_x, tip_y), (tip_x + 30, tip_y - 10), (tip_x + 10, tip_y - 35)], fill=color)

def draw_plus_icon(draw, cx, cy, size=180, color=TEXT_COLOR):
    w = 16
    draw.line([cx - size/2, cy, cx + size/2, cy], fill=color, width=w)
    draw.line([cx, cy - size/2, cx, cy + size/2], fill=color, width=w)

def draw_list_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    w, h = size * 0.8, size
    x, y = cx - w/2, cy - h/2
    draw.rounded_rectangle([x, y, x+w, y+h], radius=15, outline=color, width=12)
    clip_w, clip_h = w * 0.5, 30
    draw.rectangle([cx - clip_w/2, y-10, cx + clip_w/2, y+clip_h], fill=BG_COLOR)
    draw.rounded_rectangle([cx - clip_w/2, y-10, cx + clip_w/2, y+clip_h], radius=5, outline=color, width=10)
    line_x, line_w = x + 40, w - 60
    for i in range(3):
        ly = y + h * 0.4 + (i * h * 0.2)
        draw.line([line_x, ly, line_x + line_w, ly], fill=color, width=8)
        draw.ellipse([line_x - 25, ly - 5, line_x - 15, ly + 5], fill=color)

def create_premium_menu_v6():
    print("Generating pure python premium image v6 with descriptive labels...")
    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Background
    draw.rectangle([0, HEIGHT//2, WIDTH//2, HEIGHT], fill=ACCENT_BG)

    # Dividers
    draw.line([(WIDTH//2, 80), (WIDTH//2, HEIGHT-80)], fill=DIVIDER_COLOR, width=3)
    draw.line([(80, HEIGHT//2), (WIDTH-80, HEIGHT//2)], fill=DIVIDER_COLOR, width=3)

    centers = [(WIDTH*0.25, HEIGHT*0.25), (WIDTH*0.75, HEIGHT*0.25), (WIDTH*0.25, HEIGHT*0.75), (WIDTH*0.75, HEIGHT*0.75)]
    
    font_paths = ["/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc", "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"]
    font, sub_font, notice_font = ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            font = ImageFont.truetype(path, 100)
            sub_font = ImageFont.truetype(path, 50)
            notice_font = ImageFont.truetype(path, 40)
            break

    # Items Config
    items = [
        {"title": "早見表", "sub": "Webで空枠を確認", "icon": draw_calendar_icon},
        {"title": "予約変更", "sub": "日程変更・取消", "icon": draw_refresh_icon},
        {"title": "予約する", "sub": "チャットで簡単予約", "icon": draw_plus_icon, "accent": True},
        {"title": "予約確認", "sub": "自分の予定を見る", "icon": draw_list_icon}
    ]

    for i, item in enumerate(items):
        cx, cy = centers[i]
        
        # Draw Icon (shifted up)
        icon_y_offset = -80
        if item.get("accent"):
            draw.ellipse([cx - 160, cy + icon_y_offset - 160, cx + 160, cy + icon_y_offset + 160], fill=ACCENT_COLOR)
            item["icon"](draw, cx, cy + icon_y_offset, size=150, color=(255, 255, 255))
        else:
            item["icon"](draw, cx, cy + icon_y_offset, size=200, color=TEXT_COLOR)
        
        # Main Title (shifted down)
        draw.text((cx, cy + 120), item["title"], font=font, fill=TEXT_COLOR, anchor="mm")
        
        # Sub Label (further down, muted)
        draw.text((cx, cy + 220), f"({item['sub']})", font=sub_font, fill=MUTE_TEXT_COLOR, anchor="mm")

    # Bottom Notice
    draw.text((WIDTH // 2, HEIGHT - 60), "※カレンダーの反映に1分ほどかかる場合があります", font=notice_font, fill=MUTE_TEXT_COLOR, anchor="mm")

    img.save("rich_menu_v6.jpg", "JPEG", quality=95)
    print("Created rich_menu_v6.jpg")

if __name__ == "__main__":
    create_premium_menu_v6()
