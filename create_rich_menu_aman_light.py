from PIL import Image, ImageDraw, ImageFont
import os

# Ultra Premium "Aman Light" Config
WIDTH = 2500
HEIGHT = 1686

# Color Palette (Aman Tokyo Light/Daytime)
# Very warm off-white (Washi/Plaster)
BG_COLOR = (250, 248, 245)    # #FAF8F5
# Dark Charcoal/Brown (Ink/Wood)
TEXT_COLOR = (60, 50, 40)     # #3C3228
ACCENT_COLOR = (160, 140, 100)# #A08C64 Muted Gold
DIVIDER_COLOR = (220, 215, 210)# #DCD7D2 Very subtle warm gray

def draw_calendar_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    w, h = size, size * 0.9
    x, y = cx - w/2, cy - h/2
    draw.rectangle([x, y, x+w, y+h], outline=color, width=4)
    header_h = h * 0.25
    draw.line([x, y+header_h, x+w, y+header_h], fill=color, width=3)
    # Minimalist Zen Grid
    for i in range(1, 4):
        lx = x + (w/4)*i
        for j in range(1, 3):
            ly = y + header_h + (h - header_h)/3 * j
            draw.line([lx-4, ly, lx+4, ly], fill=color, width=3)
            draw.line([lx, ly-4, lx, ly+4], fill=color, width=3)

def draw_refresh_icon(draw, cx, cy, size=150, color=TEXT_COLOR):
    bbox = [cx - size/2, cy - size/2, cx + size/2, cy + size/2]
    draw.arc(bbox, start=0, end=300, fill=color, width=4)
    # Arrow head
    draw.polygon([
        (cx + 60, cy - 40),
        (cx + 40, cy - 30),
        (cx + 65, cy - 15)
    ], fill=color)

def draw_plus_icon(draw, cx, cy, size=160, color=ACCENT_COLOR):
    w = 6 # Slightly thicker for impact
    draw.line([cx - size/2, cy, cx + size/2, cy], fill=color, width=w)
    draw.line([cx, cy - size/2, cx, cy + size/2], fill=color, width=w)
    # Accent ring
    r = size * 0.8
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=4)

def draw_list_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    w, h = size * 0.7, size
    x, y = cx - w/2, cy - h/2
    draw.rectangle([x, y, x+w, y+h], outline=color, width=4)
    line_x = x + 30
    line_w = w - 60
    for i in range(3):
        ly = y + 50 + i * 40
        draw.line([line_x, ly, line_x + line_w, ly], fill=color, width=3)

def create_aman_light_menu():
    print("Generating Aman Light image...")
    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Dividers - Very subtle lines
    # Shorten them slightly for elegance (not touching edges)
    # padding = 150
    # draw.line([(WIDTH//2, padding), (WIDTH//2, HEIGHT-padding)], fill=DIVIDER_COLOR, width=3)
    # draw.line([(padding, HEIGHT//2), (WIDTH-padding, HEIGHT//2)], fill=DIVIDER_COLOR, width=3)
    
    # Full dividers look cleaner on mobile
    draw.line([(WIDTH//2, 0), (WIDTH//2, HEIGHT)], fill=DIVIDER_COLOR, width=3)
    draw.line([(0, HEIGHT//2), (WIDTH, HEIGHT//2)], fill=DIVIDER_COLOR, width=3)

    # Fonts (Serif/Mincho) - Increased size for readability (Senior Friendly)
    font_paths = [
        "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "/System/Library/Fonts/Hiragino Mincho ProN.ttc",
        "/System/Library/Fonts/游明朝.ttc"
    ]
    font = ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            try:
                # Increased from 85 to 110
                font = ImageFont.truetype(path, 110)
                print(f"Loaded font: {path}")
                break
            except:
                pass

    # Increased offset for larger icons
    offset_y = 160 

    # Sections - Icons scaled up ~1.3x
    # TL: Schedule
    cx, cy = WIDTH * 0.25, HEIGHT * 0.25
    draw_calendar_icon(draw, cx, cy - 60, size=240, color=TEXT_COLOR) # 180 -> 240
    draw.text((cx, cy + offset_y), "早見表", font=font, fill=TEXT_COLOR, anchor="mm")

    # TR: Change
    cx, cy = WIDTH * 0.75, HEIGHT * 0.25
    draw_refresh_icon(draw, cx, cy - 60, size=230, color=TEXT_COLOR) # 180 -> 230
    draw.text((cx, cy + offset_y), "予約変更", font=font, fill=TEXT_COLOR, anchor="mm")

    # BL: Book (Accent)
    cx, cy = WIDTH * 0.25, HEIGHT * 0.75
    # Use Gold Accent
    draw_plus_icon(draw, cx, cy - 60, size=200, color=ACCENT_COLOR) # 150 -> 200
    draw.text((cx, cy + offset_y), "予約する", font=font, fill=ACCENT_COLOR, anchor="mm")

    # BR: Check
    cx, cy = WIDTH * 0.75, HEIGHT * 0.75
    draw_list_icon(draw, cx, cy - 60, size=240, color=TEXT_COLOR) # 180 -> 240
    draw.text((cx, cy + offset_y), "予約確認", font=font, fill=TEXT_COLOR, anchor="mm")

    img.save("rich_menu_aman_light.jpg", "JPEG", quality=95)
    print("Created rich_menu_aman_light.jpg")

if __name__ == "__main__":
    create_aman_light_menu()
