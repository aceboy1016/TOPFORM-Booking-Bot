from PIL import Image, ImageDraw, ImageFont
import os

def create_rich_menu_image(output_path="rich_menu_v2.jpg"):
    # Constants
    WIDTH = 2500
    HEIGHT = 1686
    BG_COLOR = (255, 255, 255) # White
    THEME_COLOR = (0, 31, 63)  # Navy Blue #001f3f
    TEXT_COLOR = THEME_COLOR
    BORDER_WIDTH = 30
    
    # Canvas
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    
    # --- Layout Borders ---
    # Outer Border
    draw.rectangle([0, 0, WIDTH-1, HEIGHT-1], outline=THEME_COLOR, width=BORDER_WIDTH)
    
    # Divider Horizontal (y=843)
    draw.line([(0, 843), (WIDTH, 843)], fill=THEME_COLOR, width=BORDER_WIDTH)
    
    # Divider Vertical (x=1250, y from 843 to HEIGHT)
    draw.line([(1250, 843), (1250, HEIGHT)], fill=THEME_COLOR, width=BORDER_WIDTH)
    
    # Inner borders (Gap style) - Optional for style
    # Top Area
    gap = 40
    draw.rectangle([gap, gap, WIDTH-gap, 843-gap], outline=THEME_COLOR, width=10)
    # Bottom Left
    draw.rectangle([gap, 843+gap, 1250-gap, HEIGHT-gap], outline=THEME_COLOR, width=10)
    # Bottom Right
    draw.rectangle([1250+gap, 843+gap, WIDTH-gap, HEIGHT-gap], outline=THEME_COLOR, width=10)

    # --- Text ---
    # Font Settings
    # Try to find a good Japanese font on Mac
    font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
    if not os.path.exists(font_path):
        # Fallback to W3 or W8
        font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    
    if not os.path.exists(font_path):
        print("Japanese font not found, using default.")
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_icon = ImageFont.load_default()
    else:
        try:
            # Face index 0 is usually the font
            font_title = ImageFont.truetype(font_path, 140)
            font_sub = ImageFont.truetype(font_path, 80)
            font_icon = ImageFont.truetype(font_path, 150)
        except:
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()
            font_icon = ImageFont.load_default()

    def draw_centered_text(x, y, text, font, color=TEXT_COLOR):
        # Get bounding box
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((x - w/2, y - h/2), text, font=font, fill=color)

    # --- Top Area (Schedule) ---
    cx, cy = 1250, 421
    # Icon (Simple square for now if emoji fails)
    draw_centered_text(cx, cy - 120, "SCHEDULE & MENU", font=font_sub)
    draw_centered_text(cx, cy + 50, "石原早見表", font=font_title)

    # --- Bottom Left (Booking) ---
    cx, cy = 625, 1264
    draw_centered_text(cx, cy - 80, "BOOKING", font=font_sub)
    draw_centered_text(cx, cy + 60, "予約する", font=font_title)
    
    # --- Bottom Right (My Page) ---
    cx, cy = 1875, 1264
    draw_centered_text(cx, cy - 80, "MY PAGE", font=font_sub)
    draw_centered_text(cx, cy + 60, "予約確認", font=font_title)

    # Save
    img.save(output_path, quality=95)
    print(f"Created {output_path}")
    return output_path

if __name__ == "__main__":
    create_rich_menu_image()
