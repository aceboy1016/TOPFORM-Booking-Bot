from PIL import Image, ImageDraw, ImageFont
import os
import math

WIDTH = 2500
HEIGHT = 1686

def create_final_menu_repro():
    print("Generating FINAL design reproduction from latest image...")

    # Colors as per latest photo
    BG_COLOR = (255, 255, 255)       # Pure White
    GOLD = (196, 172, 120)           # Gold / Tan for icons and tags
    TEXT_COLOR = (0, 0, 0)           # Pure Black for titles
    DIVIDER_COLOR = (220, 220, 220)  # Thin gray divider
    WHITE = (255, 255, 255)
    NOTICE_COLOR = (255, 0, 0)       # Red for the bot response notice

    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Dividers
    mid_x, mid_y = WIDTH // 2, HEIGHT // 2
    draw.line([(mid_x, 0), (mid_x, HEIGHT)], fill=DIVIDER_COLOR, width=3)
    draw.line([(0, mid_y), (WIDTH, mid_y)], fill=DIVIDER_COLOR, width=3)

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
            title_font = ImageFont.truetype(path, 110) # Bolder and bigger
            tag_font = ImageFont.truetype(path, 60)
            notice_font = ImageFont.truetype(path, 55) # Notice is quite visible
            break

    def draw_pill_tag(d, cx, cy, text, font):
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad_x, pad_y = 50, 25
        rx = tw / 2 + pad_x
        ry = th / 2 + pad_y
        d.rounded_rectangle([cx - rx, cy - ry, cx + rx, cy + ry],
                            radius=ry, fill=GOLD)
        d.text((cx, cy), text, font=font, fill=WHITE, anchor="mm")

    def icon_calendar_plus(d, cx, cy):
        s = 200
        w, h = s, s * 0.85
        x0, y0 = cx - w/2, cy - h/2
        d.rounded_rectangle([x0, y0, x0+w, y0+h], radius=16, outline=GOLD, width=12)
        bar_y = y0 + h * 0.32
        d.line([x0, bar_y, x0+w, bar_y], fill=GOLD, width=10)
        for tx in [x0 + w*0.3, x0 + w*0.7]:
            d.line([tx, y0 - 20, tx, y0 + 20], fill=GOLD, width=12)
        for row in range(2):
            for col in range(3):
                gx = x0 + 35 + col * 50
                gy = bar_y + 25 + row * 45
                d.rectangle([gx, gy, gx + 20, gy + 15], fill=GOLD)
        bx, by = x0 + w + 10, y0 + h + 10
        br = 48
        d.ellipse([bx-br, by-br, bx+br, by+br], fill=BG_COLOR, outline=GOLD, width=10)
        d.line([bx - 22, by, bx + 22, by], fill=GOLD, width=10)
        d.line([bx, by - 22, bx, by + 22], fill=GOLD, width=10)

    def icon_refresh(d, cx, cy):
        r = 100
        lw = 16
        d.arc([cx-r, cy-r, cx+r, cy+r], start=200, end=340, fill=GOLD, width=lw)
        d.arc([cx-r, cy-r, cx+r, cy+r], start=20, end=160, fill=GOLD, width=lw)
        def arrowhead(angle_deg):
            a = math.radians(angle_deg)
            px = cx + r * math.cos(a)
            py = cy + r * math.sin(a)
            ta = a + math.pi / 2
            tip_len = 55
            tx = px + tip_len * math.cos(ta)
            ty = py + tip_len * math.sin(ta)
            perp = ta + math.pi / 2
            bh = 30
            b1x = px + bh * math.cos(perp)
            b1y = py + bh * math.sin(perp)
            b2x = px - bh * math.cos(perp)
            b2y = py - bh * math.sin(perp)
            d.polygon([(tx, ty), (b1x, b1y), (b2x, b2y)], fill=GOLD)
        arrowhead(340)
        arrowhead(160)

    def icon_check_circle(d, cx, cy):
        r = 110
        d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=GOLD, width=15)
        lw = 18
        d.line([cx - 45, cy + 5, cx - 10, cy + 45], fill=GOLD, width=lw)
        d.line([cx - 10, cy + 45, cx + 55, cy - 35], fill=GOLD, width=lw)

    def icon_clipboard_check(d, cx, cy):
        bw, bh = 150, 210
        x0, y0 = cx - bw/2, cy - bh/2
        d.rounded_rectangle([x0, y0, x0+bw, y0+bh], radius=16, outline=GOLD, width=12)
        cw, ch = 75, 45
        d.rectangle([cx - cw/2, y0 - 15, cx + cw/2, y0 + ch], fill=BG_COLOR)
        d.rounded_rectangle([cx - cw/2, y0 - 15, cx + cw/2, y0 + ch],
                            radius=10, outline=GOLD, width=10)
        lw = 18
        check_cy = cy + 22
        d.line([cx - 35, check_cy, cx - 5, check_cy + 35], fill=GOLD, width=lw)
        d.line([cx - 5, check_cy + 35, cx + 50, cy - 20], fill=GOLD, width=lw)

    centers = [
        (WIDTH * 0.25, HEIGHT * 0.25),
        (WIDTH * 0.75, HEIGHT * 0.25),
        (WIDTH * 0.25, HEIGHT * 0.75),
        (WIDTH * 0.75, HEIGHT * 0.75),
    ]

    items = [
        {"tag": "空き状況を見る", "title": "予約早見表", "icon": icon_calendar_plus},
        {"tag": "予約を変更・キャンセル", "title": "予約変更", "icon": icon_refresh},
        {"tag": "新しく予約する", "title": "予約する", "icon": icon_check_circle},
        {"tag": "予約内容を見る", "title": "予約確認", "icon": icon_clipboard_check},
    ]

    for i, item in enumerate(items):
        cx, cy = centers[i]
        qy_top = (i // 2) * (HEIGHT // 2)
        # Perfectly balanced spacing:
        draw_pill_tag(draw, cx, qy_top + 170, item["tag"], tag_font)
        item["icon"](draw, cx, cy + 10)
        draw.text((cx, cy + 270), item["title"], font=title_font, fill=TEXT_COLOR, anchor="mm")

    # NOTICE in RED (Further down, slightly smaller to be safe)
    draw.text((WIDTH // 2, HEIGHT - 50),
              "※Botの返信には 1 分 程度かかる場合があります",
              font=notice_font, fill=NOTICE_COLOR, anchor="mm")

    img.save("rich_menu_reflection.jpg", "JPEG", quality=95)
    print("Created rich_menu_reflection.jpg")

if __name__ == "__main__":
    create_final_menu_repro()
