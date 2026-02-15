from PIL import Image, ImageDraw, ImageFont
import os

# Ultra Premium "Aman Color" Config
WIDTH = 2500
HEIGHT = 1686

# Color Palette (Aman Tokyo + Japanese Traditional Teal)
# Warm Off-White (Washi)
BG_COLOR = (250, 248, 245)    # #FAF8F5
# Dark Brown/Charcoal (Ink)
TEXT_COLOR = (60, 50, 40)     # #3C3228
# Divider
DIVIDER_COLOR = (220, 215, 210)

# ACCENT: Sabi-Asagi (Rusty/Muted Teal)
ACCENT_COLOR = (40, 110, 110) # #286E6E Deep Teal
ACCENT_BG = (225, 240, 240)   # Very light Teal tint

def draw_calendar_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    w, h = size, size * 0.9
    x, y = cx - w/2, cy - h/2
    draw.rectangle([x, y, x+w, y+h], outline=color, width=4)
    header_h = h * 0.25
    draw.line([x, y+header_h, x+w, y+header_h], fill=color, width=3)
    for i in range(1, 4):
        lx = x + (w/4)*i
        for j in range(1, 3):
            ly = y + header_h + (h - header_h)/3 * j
            draw.line([lx-4, ly, lx+4, ly], fill=color, width=3)
            draw.line([lx, ly-4, lx, ly+4], fill=color, width=3)

def draw_refresh_icon(draw, cx, cy, size=150, color=TEXT_COLOR):
    bbox = [cx - size/2, cy - size/2, cx + size/2, cy + size/2]
    draw.arc(bbox, start=0, end=300, fill=color, width=4)
    draw.polygon([
        (cx + 60, cy - 40),
        (cx + 40, cy - 30),
        (cx + 65, cy - 15)
    ], fill=color)

def draw_plus_icon_button(draw, cx, cy, size=160, color=ACCENT_COLOR, bg_color=ACCENT_BG):
    # Draw a filled circle (Button base)
    r = size * 0.85 
    # Fill
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=bg_color)
    # Outline
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=4)
    
    # Plus sign inside
    w = 8 
    draw.line([cx - size/2, cy, cx + size/2, cy], fill=color, width=w)
    draw.line([cx, cy - size/2, cx, cy + size/2], fill=color, width=w)

def draw_list_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    w, h = size * 0.7, size
    x, y = cx - w/2, cy - h/2
    draw.rectangle([x, y, x+w, y+h], outline=color, width=4)
    line_x = x + 30
    line_w = w - 60
    for i in range(3):
        ly = y + 50 + i * 40
        draw.line([line_x, ly, line_x + line_w, ly], fill=color, width=3)

def create_aman_color_menu():
    print("Generating Aman Color image...")
    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.line([(WIDTH//2, 0), (WIDTH//2, HEIGHT)], fill=DIVIDER_COLOR, width=3)
    draw.line([(0, HEIGHT//2), (WIDTH, HEIGHT//2)], fill=DIVIDER_COLOR, width=3)

    # Fonts
    font_paths = [
        "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "/System/Library/Fonts/Hiragino Mincho ProN.ttc",
        "/System/Library/Fonts/游明朝.ttc"
    ]
    font = ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, 110)
                print(f"Loaded font: {path}")
                break
            except:
                pass

    offset_y = 180 

    # Sections - Customized Sizing
    # TL: Schedule (Large)
    cx, cy = WIDTH * 0.25, HEIGHT * 0.25
    draw_calendar_icon(draw, cx, cy - 60, size=210, color=TEXT_COLOR) # Restored to 210
    draw.text((cx, cy + offset_y), "早見表", font=font, fill=TEXT_COLOR, anchor="mm")

    # TR: Change (Large)
    cx, cy = WIDTH * 0.75, HEIGHT * 0.25
    draw_refresh_icon(draw, cx, cy - 60, size=200, color=TEXT_COLOR) # Restored to 200
    draw.text((cx, cy + offset_y), "予約変更", font=font, fill=TEXT_COLOR, anchor="mm")

    # BL: Book (Small & Spaced - KEPT AS IS)
    cx, cy = WIDTH * 0.25, HEIGHT * 0.75
    # Use Teal Button - Small size maintained
    draw_plus_icon_button(draw, cx, cy - 60, size=150, color=ACCENT_COLOR, bg_color=ACCENT_BG)
    draw.text((cx, cy + offset_y), "予約する", font=font, fill=ACCENT_COLOR, anchor="mm")

    # BR: Check (Large)
    cx, cy = WIDTH * 0.75, HEIGHT * 0.75
    draw_list_icon(draw, cx, cy - 60, size=210, color=TEXT_COLOR) # Restored to 210
    draw.text((cx, cy + offset_y), "予約確認", font=font, fill=TEXT_COLOR, anchor="mm")

    img.save("rich_menu_aman_color.jpg", "JPEG", quality=95)
    print("Created rich_menu_aman_color.jpg")

if __name__ == "__main__":
    create_aman_color_menu()
