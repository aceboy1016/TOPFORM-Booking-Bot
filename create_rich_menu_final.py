from PIL import Image, ImageDraw, ImageFont
import os
import math

WIDTH = 2500
HEIGHT = 1686

def create_final_menu():
    print("Generating FINAL design: exact photo reproduction + notice...")

    # Colors from the photo
    BG_COLOR = (245, 243, 238)       # Warm light cream
    GOLD = (196, 172, 120)           # Gold / Tan
    GOLD_LIGHT = (210, 190, 145)     # Slightly lighter gold
    TEXT_COLOR = (60, 55, 50)        # Dark brown-gray
    DIVIDER_COLOR = (215, 210, 200)  # Subtle warm divider
    WHITE = (255, 255, 255)
    NOTICE_COLOR = (160, 150, 135)   # Muted for notice

    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Dividers
    mid_x, mid_y = WIDTH // 2, HEIGHT // 2
    draw.line([(mid_x, 30), (mid_x, HEIGHT - 30)], fill=DIVIDER_COLOR, width=4)
    draw.line([(30, mid_y), (WIDTH - 30, mid_y)], fill=DIVIDER_COLOR, width=4)

    # Fonts
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    ]
    title_font = ImageFont.load_default()
    tag_font = ImageFont.load_default()
    notice_font = ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            title_font = ImageFont.truetype(path, 100)
            tag_font = ImageFont.truetype(path, 55)
            notice_font = ImageFont.truetype(path, 38)
            break

    # ================================================================
    # Helper: Draw pill-shaped tag (rounded rectangle with gold bg)
    # ================================================================
    def draw_pill_tag(d, cx, cy, text, font):
        # Measure text
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad_x, pad_y = 45, 22
        rx = tw / 2 + pad_x
        ry = th / 2 + pad_y
        d.rounded_rectangle([cx - rx, cy - ry, cx + rx, cy + ry],
                            radius=ry, fill=GOLD, outline=GOLD)
        d.text((cx, cy), text, font=font, fill=WHITE, anchor="mm")

    # ================================================================
    # ICON 1: Calendar with (+) badge
    # ================================================================
    def icon_calendar_plus(d, cx, cy):
        s = 180
        w, h = s, s * 0.85
        x0, y0 = cx - w/2, cy - h/2

        # Calendar body
        d.rounded_rectangle([x0, y0, x0+w, y0+h], radius=16, outline=GOLD, width=11)
        # Header bar
        bar_y = y0 + h * 0.32
        d.line([x0, bar_y, x0+w, bar_y], fill=GOLD, width=8)
        # Two ring tabs on top
        for tx in [x0 + w*0.3, x0 + w*0.7]:
            d.line([tx, y0 - 16, tx, y0 + 16], fill=GOLD, width=10)

        # Grid inside (3x2)
        for row in range(2):
            for col in range(3):
                gx = x0 + 32 + col * 45
                gy = bar_y + 22 + row * 38
                d.rectangle([gx, gy, gx + 18, gy + 12], fill=GOLD)

        # (+) badge
        bx, by = x0 + w + 8, y0 + h + 8
        br = 42
        d.ellipse([bx-br, by-br, bx+br, by+br], fill=BG_COLOR, outline=GOLD, width=8)
        d.line([bx - 18, by, bx + 18, by], fill=GOLD, width=8)
        d.line([bx, by - 18, bx, by + 18], fill=GOLD, width=8)

    # ================================================================
    # ICON 2: Refresh / Sync arrows
    # ================================================================
    def icon_refresh(d, cx, cy):
        r = 88
        lw = 13
        d.arc([cx-r, cy-r, cx+r, cy+r], start=195, end=345, fill=GOLD, width=lw)
        d.arc([cx-r, cy-r, cx+r, cy+r], start=15, end=165, fill=GOLD, width=lw)

        def arrowhead(angle_deg):
            a = math.radians(angle_deg)
            px = cx + r * math.cos(a)
            py = cy + r * math.sin(a)
            ta = a + math.pi / 2  # tangent CW
            tip_len = 45
            tx = px + tip_len * math.cos(ta)
            ty = py + tip_len * math.sin(ta)
            perp = ta + math.pi / 2
            bh = 25
            b1x = px + bh * math.cos(perp)
            b1y = py + bh * math.sin(perp)
            b2x = px - bh * math.cos(perp)
            b2y = py - bh * math.sin(perp)
            d.polygon([(tx, ty), (b1x, b1y), (b2x, b2y)], fill=GOLD)

        arrowhead(345)
        arrowhead(165)

    # ================================================================
    # ICON 3: Circle with checkmark (outline style like photo)
    # ================================================================
    def icon_check_circle(d, cx, cy):
        r = 100
        # Gold outline circle (not filled)
        d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=GOLD, width=12)
        # Gold checkmark
        lw = 14
        d.line([cx - 40, cy + 5, cx - 8, cy + 40], fill=GOLD, width=lw)
        d.line([cx - 8, cy + 40, cx + 50, cy - 30], fill=GOLD, width=lw)

    # ================================================================
    # ICON 4: Clipboard with checkmark
    # ================================================================
    def icon_clipboard_check(d, cx, cy):
        bw, bh = 140, 190
        x0, y0 = cx - bw/2, cy - bh/2

        d.rounded_rectangle([x0, y0, x0+bw, y0+bh], radius=14, outline=GOLD, width=11)

        # Clip tab
        cw, ch = 65, 38
        d.rectangle([cx - cw/2, y0 - 10, cx + cw/2, y0 + ch], fill=BG_COLOR)
        d.rounded_rectangle([cx - cw/2, y0 - 10, cx + cw/2, y0 + ch],
                            radius=8, outline=GOLD, width=9)

        # Checkmark
        lw = 14
        check_cy = cy + 18
        d.line([cx - 32, check_cy, cx - 5, check_cy + 32], fill=GOLD, width=lw)
        d.line([cx - 5, check_cy + 32, cx + 42, check_cy - 22], fill=GOLD, width=lw)

    # ================================================================
    # LAYOUT
    # ================================================================
    centers = [
        (WIDTH * 0.25, HEIGHT * 0.25),
        (WIDTH * 0.75, HEIGHT * 0.25),
        (WIDTH * 0.25, HEIGHT * 0.75),
        (WIDTH * 0.75, HEIGHT * 0.75),
    ]

    items = [
        {"tag": "空き状況を見る",       "title": "予約早見表", "icon": icon_calendar_plus},
        {"tag": "予約を変更・キャンセル", "title": "予約変更",   "icon": icon_refresh},
        {"tag": "新しく予約する",       "title": "予約する",   "icon": icon_check_circle},
        {"tag": "予約内容を見る",       "title": "予約確認",   "icon": icon_clipboard_check},
    ]

    for i, item in enumerate(items):
        cx, cy = centers[i]

        # Pill Tag (top of quadrant)
        qy_top = (i // 2) * (HEIGHT // 2)
        draw_pill_tag(draw, cx, qy_top + 100, item["tag"], tag_font)

        # Icon (center)
        item["icon"](draw, cx, cy + 30)

        # Title (bottom)
        draw.text((cx, cy + 280), item["title"],
                  font=title_font, fill=TEXT_COLOR, anchor="mm")

    # ================================================================
    # NOTICE (※ annotation at bottom)
    # ================================================================
    draw.text((WIDTH // 2, HEIGHT - 55),
              "※カレンダーへの反映に1分ほどかかる場合があります",
              font=notice_font, fill=NOTICE_COLOR, anchor="mm")

    img.save("rich_menu_final.jpg", "JPEG", quality=95)
    print("Created rich_menu_final.jpg")

if __name__ == "__main__":
    create_final_menu()
