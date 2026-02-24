from PIL import Image, ImageDraw, ImageFont
import os

# Ultra Premium Config
WIDTH = 2500
HEIGHT = 1686

def create_premium_menu_v9():
    print("Generating partitioned premium image v9...")
    
    # 1. Colors inside function to be absolutely safe
    BG_COLOR = (255, 255, 255)    
    TEXT_COLOR = (28, 28, 30)     
    ACCENT_COLOR = (52, 199, 89)  
    TAG_BG_COLOR = (242, 242, 247) 
    TAG_TEXT_COLOR = (68, 68, 70)  
    MUTE_TEXT_COLOR = (142, 142, 147)
    BORDER_COLOR = (44, 44, 46) # Darker for clear structure

    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 2. Strong Grid Dividers
    draw.line([(0, HEIGHT//2), (WIDTH, HEIGHT//2)], fill=BORDER_COLOR, width=15)
    draw.line([(WIDTH//2, 0), (WIDTH//2, HEIGHT)], fill=BORDER_COLOR, width=15)

    # Load Font
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    ]
    font, tag_font, notice_font = ImageFont.load_default(), ImageFont.load_default(), ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            font = ImageFont.truetype(path, 110)
            tag_font = ImageFont.truetype(path, 80)
            notice_font = ImageFont.truetype(path, 45)
            break

    # 3. Item Definitions
    items = [
        {"action": "空き状況をみる", "title": "早見表", "type": "schedule"},
        {"action": "予定を変更・消す", "title": "予約変更", "type": "change"},
        {"action": "新しく予約したい", "title": "予約する", "type": "book", "accent": True},
        {"action": "予約内容をみる", "title": "予約確認", "type": "check"}
    ]

    centers = [
        (WIDTH * 0.25, HEIGHT * 0.25),
        (WIDTH * 0.75, HEIGHT * 0.25),
        (WIDTH * 0.25, HEIGHT * 0.75),
        (WIDTH * 0.75, HEIGHT * 0.75),
    ]

    for i, item in enumerate(items):
        cx, cy = centers[i]
        qx = (i % 2) * (WIDTH // 2)
        qy = (i // 2) * (HEIGHT // 2)

        # -- Header Title Box (Action Area) --
        tag_h = 280
        # Draw a strong header bar for each section
        draw.rectangle([qx + 10, qy + 10, qx + (WIDTH // 2) - 10, qy + tag_h], fill=TAG_BG_COLOR)
        draw.rectangle([qx + 10, qy + 10, qx + (WIDTH // 2) - 10, qy + tag_h], outline=BORDER_COLOR, width=5)
        
        # Action Text in Header
        draw.text((qx + (WIDTH // 4), qy + (tag_h // 2)), item["action"], font=tag_font, fill=TEXT_COLOR, anchor="mm")

        # -- Icon Setup (Simplified shapes for clearer rendering) --
        icon_cy = qy + (HEIGHT // 4) + 80
        if item.get("accent"):
            # Prominent Green Circle for "予約する"
            draw.ellipse([cx - 180, icon_cy - 180, cx + 180, icon_cy + 180], fill=ACCENT_COLOR)
            # Plus sign in white
            w = 25
            draw.line([cx - 80, icon_cy, cx + 80, icon_cy], fill=(255, 255, 255), width=w)
            draw.line([cx, icon_cy - 80, cx, icon_cy + 80], fill=(255, 255, 255), width=w)
        else:
            # Subtle glyph representation
            if item["type"] == "schedule":
                draw.rounded_rectangle([cx - 110, icon_cy - 100, cx + 110, icon_cy + 100], radius=20, outline=TEXT_COLOR, width=15)
                draw.line([cx - 110, icon_cy - 30, cx + 110, icon_cy - 30], fill=TEXT_COLOR, width=12)
            elif item["type"] == "change":
                draw.arc([cx - 100, icon_cy - 100, cx + 100, icon_cy + 100], start=30, end=330, fill=TEXT_COLOR, width=15)
            elif item["type"] == "check":
                draw.rounded_rectangle([cx - 90, icon_cy - 110, cx + 90, icon_cy + 110], radius=15, outline=TEXT_COLOR, width=15)
                for line_y in [-30, 20, 70]:
                    draw.line([cx - 50, icon_cy + line_y, cx + 50, icon_cy + line_y], fill=TEXT_COLOR, width=12)

        # -- Main Title (Bottom Area) --
        draw.text((cx, qy + (HEIGHT // 2) - 140), item["title"], font=font, fill=TEXT_COLOR, anchor="mm")

    # Bottom Notice with Frame
    notice_rect = [WIDTH // 4, HEIGHT - 110, WIDTH * 3 // 4, HEIGHT - 15]
    draw.rectangle(notice_rect, fill=(242, 242, 247), outline=BORDER_COLOR, width=3)
    draw.text((WIDTH // 2, HEIGHT - 62), "※カレンダーの反映に1分ほどかかる場合があります", font=notice_font, fill=TAG_TEXT_COLOR, anchor="mm")

    img.save("rich_menu_v9.jpg", "JPEG", quality=95)
    print("Created rich_menu_v9.jpg")

if __name__ == "__main__":
    create_premium_menu_v9()
