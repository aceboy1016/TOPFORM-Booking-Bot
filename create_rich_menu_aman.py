from PIL import Image, ImageDraw, ImageFont
import os

# Ultra Premium "Aman" Config
WIDTH = 2500
HEIGHT = 1686

# Color Palette (Aman Tokyo Inspired)
# Deep Charcoal (Stone/Basalt)
BG_COLOR = (40, 40, 40)       # #282828
# Off-White (Washi/Plaster)
TEXT_COLOR = (220, 220, 220)  # #DCDCDC
# Subtle Gold/Beige (Wood/Light) - Use sparingly
ACCENT_COLOR = (180, 160, 120)# #B4A078
# Divider - Very faint
DIVIDER_COLOR = (60, 60, 60)  # #3C3C3C

def draw_calendar_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    w, h = size, size * 0.9
    x, y = cx - w/2, cy - h/2
    # Body: Thin lines
    draw.rectangle([x, y, x+w, y+h], outline=color, width=3)
    # Header line
    header_h = h * 0.25
    draw.line([x, y+header_h, x+w, y+header_h], fill=color, width=2)
    # Simple grid inside (Zen dots)
    for i in range(1, 4): # Columns
        lx = x + (w/4)*i
        for j in range(1, 3): # Rows
            ly = y + header_h + (h - header_h)/3 * j
            # Draw tiny plus or dot
            draw.line([lx-5, ly, lx+5, ly], fill=color, width=2)
            draw.line([lx, ly-5, lx, ly+5], fill=color, width=2)

def draw_refresh_icon(draw, cx, cy, size=150, color=TEXT_COLOR):
    # Minimalist circle
    bbox = [cx - size/2, cy - size/2, cx + size/2, cy + size/2]
    draw.arc(bbox, start=0, end=300, fill=color, width=3)
    # Arrow head (Thin)
    # Tip at 300 deg (approx top right)
    # Draw simple lines
    tip_x = cx + size/2 * 0.5 # approx
    tip_y = cy - size/2 * 0.86
    # Manual fine tuning for cleaner look
    draw.polygon([
        (cx + 60, cy - 40),
        (cx + 60 - 20, cy - 40 + 10),
        (cx + 60 + 5, cy - 40 + 25)
    ], fill=color)

def draw_plus_icon(draw, cx, cy, size=160, color=ACCENT_COLOR):
    # Very thin, elegant plus
    w = 4 # Very thin
    draw.line([cx - size/2, cy, cx + size/2, cy], fill=color, width=w)
    draw.line([cx, cy - size/2, cx, cy + size/2], fill=color, width=w)
    
    # Encircle it with thin ring
    r = size * 0.8
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=2)

def draw_list_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    w, h = size * 0.7, size
    x, y = cx - w/2, cy - h/2
    draw.rectangle([x, y, x+w, y+h], outline=color, width=3)
    
    # Lines (Abstract)
    line_x = x + 30
    line_w = w - 60
    for i in range(3):
        ly = y + 50 + i * 40
        draw.line([line_x, ly, line_x + line_w, ly], fill=color, width=2)

def create_aman_menu():
    print("Generating Aman-style image...")
    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 1. Subtle Texture/Gradient simulation (Optional)
    # For coding simplicity and "Zen", flat color is better, or very subtle noise.
    # Let's keep it flat matte for now.

    # 2. Dividers (Shoji style - thin, precise)
    draw.line([(WIDTH//2, 100), (WIDTH//2, HEIGHT-100)], fill=DIVIDER_COLOR, width=2)
    draw.line([(100, HEIGHT//2), (WIDTH-100, HEIGHT//2)], fill=DIVIDER_COLOR, width=2)

    # 3. Load Mincho Font (Serif)
    font_paths = [
        "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
        "/System/Library/Fonts/Hiragino Mincho ProN.ttc",
        "/System/Library/Fonts/游明朝.ttc",
        "/System/Library/Fonts/YuMincho.ttc",
        "/Library/Fonts/Songti.ttc" # Fallback Serif
    ]
    font = ImageFont.load_default()
    font_large = font
    
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, 80) # Elegant, small
                # font_large = ImageFont.truetype(path, 90)
                print(f"Loaded font: {path}")
                break
            except:
                pass

    # Centers
    # Shift Y up slightly because text is below
    offset_y = 120 
    
    # -- Top Left: Schedule --
    cx, cy = WIDTH * 0.25, HEIGHT * 0.25
    draw_calendar_icon(draw, cx, cy - 50, size=180, color=TEXT_COLOR)
    draw.text((cx, cy + offset_y), "早見表", font=font, fill=TEXT_COLOR, anchor="mm")

    # -- Top Right: Change --
    cx, cy = WIDTH * 0.75, HEIGHT * 0.25
    draw_refresh_icon(draw, cx, cy - 50, size=180, color=TEXT_COLOR)
    draw.text((cx, cy + offset_y), "予約変更", font=font, fill=TEXT_COLOR, anchor="mm")

    # -- Bottom Left: Book (Focus) --
    cx, cy = WIDTH * 0.25, HEIGHT * 0.75
    # Aman doesn't do "buttons". It does "Presence".
    # Use the gold accent color here.
    draw_plus_icon(draw, cx, cy - 50, size=140, color=ACCENT_COLOR) # Gold Plus
    draw.text((cx, cy + offset_y), "予約する", font=font, fill=ACCENT_COLOR, anchor="mm") # Gold Text

    # -- Bottom Right: Check --
    cx, cy = WIDTH * 0.75, HEIGHT * 0.75
    draw_list_icon(draw, cx, cy - 50, size=180, color=TEXT_COLOR)
    draw.text((cx, cy + offset_y), "予約確認", font=font, fill=TEXT_COLOR, anchor="mm")

    # Save
    img.save("rich_menu_aman.jpg", "JPEG", quality=95)
    print("Created rich_menu_aman.jpg")

if __name__ == "__main__":
    create_aman_menu()
