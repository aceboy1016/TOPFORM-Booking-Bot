from PIL import Image, ImageDraw, ImageFont
import os

# Ultra Premium Config
WIDTH = 2500
HEIGHT = 1686

# Color Palette (Google Material / Apple Human Interface inspired)
BG_COLOR = (248, 249, 250)    # #F8F9FA Off-White
TEXT_COLOR = (28, 28, 30)     # #1C1C1E Dark Gray (Apple System Gray 6)
ACCENT_COLOR = (52, 199, 89)  # #34C759 Emerald Green (Modern, Friendly)
ACCENT_BG = (235, 255, 240)   # Light Green tint for button
DIVIDER_COLOR = (229, 229, 234)# #E5E5EA Light Gray Divider

def draw_calendar_icon(draw, cx, cy, size=180, color=TEXT_COLOR):
    # Calendar body
    w, h = size, size * 0.9
    x, y = cx - w/2, cy - h/2
    draw.rounded_rectangle([x, y, x+w, y+h], radius=20, outline=color, width=12)
    # Header line
    header_h = h * 0.3
    draw.line([x, y+header_h, x+w, y+header_h], fill=color, width=8)
    # Rings
    ring_h = 40
    ring_x_offset = w * 0.25
    draw.line([x+ring_x_offset, y-10, x+ring_x_offset, y+20], fill=color, width=12)
    draw.line([x+w-ring_x_offset, y-10, x+w-ring_x_offset, y+20], fill=color, width=12)

def draw_refresh_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    # Simplified circular arrow concept
    # Draw arc
    bbox = [cx - size/2, cy - size/2, cx + size/2, cy + size/2]
    draw.arc(bbox, start=30, end=330, fill=color, width=12)
    # Draw arrow head (Top right)
    # Simple triangle manually
    tip_x = cx + size/2 * 0.9
    tip_y = cy - size/2 * 0.3
    draw.polygon([
        (tip_x, tip_y), 
        (tip_x - 30, tip_y + 10), 
        (tip_x - 10, tip_y + 35)
    ], fill=color)
    # Bottom left arrow head
    tip_x = cx - size/2 * 0.9
    tip_y = cy + size/2 * 0.3
    draw.polygon([
        (tip_x, tip_y), 
        (tip_x + 30, tip_y - 10), 
        (tip_x + 10, tip_y - 35)
    ], fill=color)

def draw_plus_icon(draw, cx, cy, size=180, color=TEXT_COLOR):
    # Plus sign
    w = 16 # Line thickness
    draw.line([cx - size/2, cy, cx + size/2, cy], fill=color, width=w)
    draw.line([cx, cy - size/2, cx, cy + size/2], fill=color, width=w)

def draw_list_icon(draw, cx, cy, size=160, color=TEXT_COLOR):
    # Clipboard shape
    w, h = size * 0.8, size
    x, y = cx - w/2, cy - h/2
    draw.rounded_rectangle([x, y, x+w, y+h], radius=15, outline=color, width=12)
    # Create distinct clip holder at top
    clip_w = w * 0.5
    clip_h = 30
    draw.rectangle([cx - clip_w/2, y-10, cx + clip_w/2, y+clip_h], fill=BG_COLOR) # Clear
    draw.rounded_rectangle([cx - clip_w/2, y-10, cx + clip_w/2, y+clip_h], radius=5, outline=color, width=10)
    
    # Check lines
    line_x = x + 40
    line_w = w - 60
    for i in range(3):
        ly = y + h * 0.4 + (i * h * 0.2)
        draw.line([line_x, ly, line_x + line_w, ly], fill=color, width=8)
        # Check mark dot
        draw.ellipse([line_x - 25, ly - 5, line_x - 15, ly + 5], fill=color)


def create_premium_menu():
    print("Generating pure python premium image...")
    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 1. Background Highlights (Subtle)
    # Bottom Left (Booking) Highlight Area - Soft Green
    # Instead of full fill, let's draw a nice rounded rectangle "button" effect
    # area for "Book" is (0, 843) to (1250, 1686)
    # Let's put a "card" inside it? No, keeping it flat is better for menus.
    # Let's faint tint the bottom left quadrant.
    draw.rectangle([0, HEIGHT//2, WIDTH//2, HEIGHT], fill=ACCENT_BG)

    # 2. Dividers (Very subtle)
    draw.line([(WIDTH//2, 80), (WIDTH//2, HEIGHT-80)], fill=DIVIDER_COLOR, width=3)
    draw.line([(80, HEIGHT//2), (WIDTH-80, HEIGHT//2)], fill=DIVIDER_COLOR, width=3)

    # 3. Icons & Text Logic
    # Centers
    centers = [
        (WIDTH * 0.25, HEIGHT * 0.25), # TL
        (WIDTH * 0.75, HEIGHT * 0.25), # TR
        (WIDTH * 0.25, HEIGHT * 0.75), # BL
        (WIDTH * 0.75, HEIGHT * 0.75), # BR
    ]
    
    # Load Font
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    ]
    font = ImageFont.load_default()
    for path in font_paths:
        if os.path.exists(path):
            font = ImageFont.truetype(path, 90) # Clean, readable size
            break

    # -- Top Left: Schedule --
    cx, cy = centers[0]
    draw_calendar_icon(draw, cx, cy - 60, size=200, color=TEXT_COLOR)
    draw.text((cx, cy + 120), "早見表", font=font, fill=TEXT_COLOR, anchor="mm")

    # -- Top Right: Change --
    cx, cy = centers[1]
    draw_refresh_icon(draw, cx, cy - 60, size=200, color=TEXT_COLOR)
    draw.text((cx, cy + 120), "予約変更", font=font, fill=TEXT_COLOR, anchor="mm")

    # -- Bottom Left: Book (Accent) --
    cx, cy = centers[2]
    # Draw a prominent circle button behind the plus
    btn_r = 160
    draw.ellipse([cx - btn_r, cy - 80 - btn_r, cx + btn_r, cy - 80 + btn_r], fill=ACCENT_COLOR)
    draw_plus_icon(draw, cx, cy - 80, size=140, color=(255, 255, 255)) # White Plus
    
    # Text in Accent Color? Or Dark? Let's go Dark for readability, or Green?
    # Let's go with Dark Gray for text to keep it grounding.
    draw.text((cx, cy + 140), "予約する", font=font, fill=TEXT_COLOR, anchor="mm")

    # -- Bottom Right: Check --
    cx, cy = centers[3]
    draw_list_icon(draw, cx, cy - 60, size=200, color=TEXT_COLOR)
    draw.text((cx, cy + 120), "予約確認", font=font, fill=TEXT_COLOR, anchor="mm")

    # Save
    img.save("rich_menu_premium.jpg", "JPEG", quality=95)
    print("Created rich_menu_premium.jpg")

if __name__ == "__main__":
    create_premium_menu()
