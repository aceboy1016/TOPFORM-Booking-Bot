from PIL import Image, ImageDraw, ImageFont
import os
import math

WIDTH = 2500
HEIGHT = 1686

def create_premium_menu_v12():
    print("Generating v12: Photo-accurate icons, v8 colors/text, no cards...")
    
    # v8 Colors
    BG_COLOR = (248, 249, 250)
    TEXT_COLOR = (28, 28, 30)
    ACCENT_COLOR = (52, 199, 89)
    DIVIDER_COLOR = (229, 229, 234)
    MUTE_TEXT_COLOR = (142, 142, 147)

    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Subtle dividers (no cards)
    draw.line([(WIDTH//2, 60), (WIDTH//2, HEIGHT-60)], fill=DIVIDER_COLOR, width=3)
    draw.line([(60, HEIGHT//2), (WIDTH-60, HEIGHT//2)], fill=DIVIDER_COLOR, width=3)

    # Fonts
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    ]
    title_font = ImageFont.load_default()
    label_font = ImageFont.load_default()
    notice_font = ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            title_font = ImageFont.truetype(path, 100)
            label_font = ImageFont.truetype(path, 65)
            notice_font = ImageFont.truetype(path, 40)
            break

    # ================================================================
    # ICON 1: Calendar with (+) badge  (Photo: Top-Left)
    # ================================================================
    def icon_calendar_plus(d, cx, cy, color):
        s = 190  # overall size
        w, h = s, s * 0.85
        x0, y0 = cx - w/2, cy - h/2

        # Calendar body
        d.rounded_rectangle([x0, y0, x0+w, y0+h], radius=18, outline=color, width=13)
        # Header bar
        bar_y = y0 + h * 0.32
        d.line([x0, bar_y, x0+w, bar_y], fill=color, width=10)
        # Two ring tabs on top
        tab_w = 12
        for tx in [x0 + w*0.3, x0 + w*0.7]:
            d.line([tx, y0-18, tx, y0+18], fill=color, width=tab_w)

        # Dot grid (3x2) inside body
        grid_x0 = x0 + 35
        grid_y0 = bar_y + 25
        dot_r = 8
        for row in range(2):
            for col in range(3):
                gx = grid_x0 + col * 48
                gy = grid_y0 + row * 40
                d.ellipse([gx-dot_r, gy-dot_r, gx+dot_r, gy+dot_r], fill=color)

        # (+) badge circle at bottom-right
        bx, by = x0 + w + 5, y0 + h + 5
        badge_r = 45
        d.ellipse([bx-badge_r, by-badge_r, bx+badge_r, by+badge_r],
                  fill=BG_COLOR, outline=color, width=9)
        d.line([bx-20, by, bx+20, by], fill=color, width=9)
        d.line([bx, by-20, bx, by+20], fill=color, width=9)

    # ================================================================
    # ICON 2: Refresh / Sync arrows  (Photo: Top-Right)
    # ================================================================
    def icon_refresh(d, cx, cy, color):
        r = 95  # radius of the circle
        lw = 14  # line width

        # We draw two arcs + two arrowheads.
        # Pillow arc: 0°=3-o'clock, angles increase COUNTER-clockwise
        # But y-axis is flipped, so visually it goes CLOCKWISE.
        #
        # Photo shows: two arcs separated by two gaps,
        # arrowheads at leading edges (clockwise flow).

        # Arc A: top portion   (visual: from ~225° to ~345°)
        # Arc B: bottom portion (visual: from ~45° to ~165°)
        # In Pillow coords (CW visual): start < end
        d.arc([cx-r, cy-r, cx+r, cy+r], start=195, end=345, fill=color, width=lw)
        d.arc([cx-r, cy-r, cx+r, cy+r], start=15, end=165, fill=color, width=lw)

        # Arrowhead helper: draw triangle at angle on circle pointing tangentially CW
        def arrowhead(angle_deg, clockwise=True):
            a = math.radians(angle_deg)
            # Position on circle
            px = cx + r * math.cos(a)
            py = cy + r * math.sin(a)
            # Tangent direction (clockwise = +90° from radial outward)
            if clockwise:
                ta = a + math.pi/2
            else:
                ta = a - math.pi/2
            # Arrow tip along tangent
            tip_len = 50
            tx = px + tip_len * math.cos(ta)
            ty = py + tip_len * math.sin(ta)
            # Two base points perpendicular to tangent
            perp = ta + math.pi/2
            base_half = 28
            b1x = px + base_half * math.cos(perp)
            b1y = py + base_half * math.sin(perp)
            b2x = px - base_half * math.cos(perp)
            b2y = py - base_half * math.sin(perp)
            d.polygon([(tx, ty), (b1x, b1y), (b2x, b2y)], fill=color)

        # Arrowhead at "leading edge" of each arc (CW visual flow)
        # Arc A ends at 345° → arrowhead there, pointing CW
        arrowhead(345, clockwise=True)
        # Arc B ends at 165° → arrowhead there, pointing CW
        arrowhead(165, clockwise=True)

    # ================================================================
    # ICON 3: Circle with checkmark  (Photo: Bottom-Left)
    # ================================================================
    def icon_check_circle(d, cx, cy, color):
        r = 110
        # Green filled circle
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=ACCENT_COLOR)
        # White checkmark
        lw = 18
        d.line([cx-45, cy+5, cx-10, cy+45], fill=(255,255,255), width=lw)
        d.line([cx-10, cy+45, cx+55, cy-35], fill=(255,255,255), width=lw)

    # ================================================================
    # ICON 4: Clipboard with checkmark  (Photo: Bottom-Right)
    # ================================================================
    def icon_clipboard_check(d, cx, cy, color):
        bw, bh = 150, 200
        x0, y0 = cx - bw/2, cy - bh/2

        # Main board
        d.rounded_rectangle([x0, y0, x0+bw, y0+bh], radius=16, outline=color, width=13)

        # Clip tab at top center
        cw, ch = 70, 40
        d.rectangle([cx-cw/2, y0-12, cx+cw/2, y0+ch], fill=BG_COLOR)
        d.rounded_rectangle([cx-cw/2, y0-12, cx+cw/2, y0+ch],
                            radius=8, outline=color, width=10)

        # Checkmark inside board
        lw = 16
        check_cy = cy + 20
        d.line([cx-35, check_cy, cx-5, check_cy+35], fill=color, width=lw)
        d.line([cx-5, check_cy+35, cx+45, check_cy-25], fill=color, width=lw)

    # ================================================================
    # LAYOUT (v8 text, no cards)
    # ================================================================
    centers = [
        (WIDTH*0.25, HEIGHT*0.25),
        (WIDTH*0.75, HEIGHT*0.25),
        (WIDTH*0.25, HEIGHT*0.75),
        (WIDTH*0.75, HEIGHT*0.75),
    ]

    items = [
        {"label": "空き状況をみる",   "title": "早見表",   "icon": icon_calendar_plus},
        {"label": "予定を変更・消す", "title": "予約変更", "icon": icon_refresh},
        {"label": "新しく予約したい", "title": "予約する", "icon": icon_check_circle},
        {"label": "予約内容をみる",   "title": "予約確認", "icon": icon_clipboard_check},
    ]

    for i, item in enumerate(items):
        cx, cy = centers[i]
        # Label (top)
        draw.text((cx, cy - 260), item["label"],
                  font=label_font, fill=MUTE_TEXT_COLOR, anchor="mm")
        # Icon (centre)
        item["icon"](draw, cx, cy + 10, TEXT_COLOR)
        # Title (bottom)
        draw.text((cx, cy + 260), item["title"],
                  font=title_font, fill=TEXT_COLOR, anchor="mm")

    # Notice
    draw.text((WIDTH//2, HEIGHT-55),
              "※カレンダーの反映に1分ほどかかる場合があります",
              font=notice_font, fill=MUTE_TEXT_COLOR, anchor="mm")

    img.save("rich_menu_v12.jpg", "JPEG", quality=95)
    print("Created rich_menu_v12.jpg")

if __name__ == "__main__":
    create_premium_menu_v12()
