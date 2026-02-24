from PIL import Image, ImageDraw, ImageFont
import os
import math

# Ultra Premium Config
WIDTH = 2500
HEIGHT = 1686

def create_premium_menu_v11():
    print("Generating v11: No cards, correct icons, v8 colors & text...")
    
    # 1. Colors (v8 Palette)
    BG_COLOR = (242, 242, 247)    # System Gray 6 (Light Gray)
    TEXT_COLOR = (28, 28, 30)     # Dark Gray
    ACCENT_COLOR = (52, 199, 89)  # Emerald Green
    DIVIDER_COLOR = (199, 199, 204)# Soft Divider
    MUTE_TEXT_COLOR = (142, 142, 147) # Gray

    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 2. Strong Crosshair Dividers (But no cards)
    mid_x, mid_y = WIDTH // 2, HEIGHT // 2
    draw.line([(mid_x, 100), (mid_x, HEIGHT - 100)], fill=DIVIDER_COLOR, width=5)
    draw.line([(100, mid_y), (WIDTH - 100, mid_y)], fill=DIVIDER_COLOR, width=5)

    # Load Fonts
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    ]
    font, label_font, notice_font = ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            font = ImageFont.truetype(path, 110)      # Title
            label_font = ImageFont.truetype(path, 65)   # Action Label
            notice_font = ImageFont.truetype(path, 40)
            break

    # 3. Correct Icon Drawers (Refined)
    
    def draw_calendar_plus_fixed(draw, cx, cy, color):
        size = 200
        w, h = size, size * 0.9
        x, y = cx - w/2, cy - h/2
        # Calendar body (rounded but clean)
        draw.rounded_rectangle([x, y, x+w, y+h], radius=20, outline=color, width=15)
        draw.line([x, y + h*0.35, x+w, y + h*0.35], fill=color, width=12)
        # Small internal grids
        for i in range(2):
            for j in range(2):
                gx = x + 50 + i*70
                gy = y + 90 + j*45
                draw.rectangle([gx, gy, gx+15, gy+15], fill=color)
        # The (+) badge at bottom right
        bx, by = x + w + 10, y + h + 10
        draw.ellipse([bx-65, by-65, bx+65, by+65], fill=BG_COLOR, outline=color, width=10)
        draw.line([bx-30, by, bx+30, by], fill=color, width=12)
        draw.line([bx, by-30, bx, by+30], fill=color, width=12)

    def draw_refresh_perfect(draw, cx, cy, color):
        size = 200
        # Draw two arcs for the refresh circle
        box = [cx - size/2, cy - size/2, cx + size/2, cy + size/2]
        # Arcs
        draw.arc(box, start=30, end=140, fill=color, width=18)
        draw.arc(box, start=210, end=320, fill=color, width=18)
        
        # Helper to draw arrowheads at specific angles
        def draw_arrow(ax, ay, angle, color):
            # Triangle points for arrowhead
            l = 45 # length
            a1 = math.radians(angle + 160)
            a2 = math.radians(angle - 160)
            p1 = (ax + l * math.cos(a1), ay + l * math.sin(a1))
            p2 = (ax + l * math.cos(a2), ay + l * math.sin(a2))
            draw.polygon([(ax, ay), p1, p2], fill=color)

        # Upper right arrowhead (approx 30 deg)
        rx = cx + (size/2) * math.cos(math.radians(30))
        ry = cy + (size/2) * math.sin(math.radians(30)) # Wait, Pillow arc is clockwise?
        # Actually let's manually place them at the start/end of arcs
        # Arc 1: 30 to 140. End is 140.
        x1 = cx + (size/2) * math.cos(math.radians(140))
        y1 = cy + (size/2) * math.sin(math.radians(140))
        draw_arrow(x1, y1, 140+90, color)
        # Arc 2: 210 to 320. End is 320.
        x2 = cx + (size/2) * math.cos(math.radians(320))
        y2 = cy + (size/2) * math.sin(math.radians(320))
        draw_arrow(x2, y2, 320+90, color)

    def draw_check_circle_premium(draw, cx, cy, color):
        size = 220
        # Prominent circle with inner white check
        draw.ellipse([cx - size/2, cy - size/2, cx + size/2, cy + size/2], fill=ACCENT_COLOR)
        # White checkmark
        draw.line([cx - 50, cy, cx - 10, cy + 40], fill=(255,255,255), width=20)
        draw.line([cx - 10, cy + 40, cx + 60, cy - 40], fill=(255,255,255), width=20)

    def draw_clipboard_check_clean(draw, cx, cy, color):
        size = 200
        w, h = size * 0.8, size
        x, y = cx - w/2, cy - h/2
        # Board
        draw.rounded_rectangle([x, y, x+w, y+h], radius=20, outline=color, width=16)
        # Clip
        draw.rectangle([cx-50, y-10, cx+50, y+40], fill=BG_COLOR, outline=color, width=12)
        # Check inside
        draw.line([cx - 40, cy + 10, cx - 10, cy + 45], fill=color, width=18)
        draw.line([cx - 10, cy + 45, cx + 50, cy - 25], fill=color, width=18)

    # 4. Layout
    centers = [
        (WIDTH * 0.25, HEIGHT * 0.25), # TL
        (WIDTH * 0.75, HEIGHT * 0.25), # TR
        (WIDTH * 0.25, HEIGHT * 0.75), # BL
        (WIDTH * 0.75, HEIGHT * 0.75), # BR
    ]

    items = [
        {"action": "空き状況をみる", "title": "早見表", "func": draw_calendar_plus_fixed},
        {"action": "予定を変更・消す", "title": "予約変更", "func": draw_refresh_perfect},
        {"action": "新しく予約したい", "title": "予約する", "func": draw_check_circle_premium},
        {"action": "予約内容をみる", "title": "予約確認", "func": draw_clipboard_check_clean}
    ]

    for i, item in enumerate(items):
        cx, cy = centers[i]
        # Text from v8
        # Label (Top)
        draw.text((cx, cy - 280), item["action"], font=label_font, fill=MUTE_TEXT_COLOR, anchor="mm")
        # Icon (Middle)
        item["func"](draw, cx, cy + 10, TEXT_COLOR)
        # Title (Bottom)
        draw.text((cx, cy + 300), item["title"], font=font, fill=TEXT_COLOR, anchor="mm")

    # 5. Global Notice
    draw.text((WIDTH // 2, HEIGHT - 60), "※カレンダーの反映に1分ほどかかる場合があります", font=notice_font, fill=MUTE_TEXT_COLOR, anchor="mm")

    img.save("rich_menu_v11.jpg", "JPEG", quality=95)
    print("Created rich_menu_v11.jpg")

if __name__ == "__main__":
    create_premium_menu_v11()
