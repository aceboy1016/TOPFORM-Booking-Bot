from PIL import Image, ImageDraw, ImageFont
import os

# Original generated image path
BASE_IMAGE_PATH = "/Users/junya/.gemini/antigravity/brain/1f08a161-293f-4b5d-ac93-b41d9035be10/rich_menu_base_bright_1771149049769.png"
OUTPUT_PATH = "rich_menu_final.jpg"

WIDTH = 2500
HEIGHT = 1686
TEXT_COLOR = (22, 33, 62) # Dark Navy

def create_final_image():
    print("Opening base image...")
    if not os.path.exists(BASE_IMAGE_PATH):
        print(f"Error: Base image not found at {BASE_IMAGE_PATH}")
        return

    base_img = Image.open(BASE_IMAGE_PATH)
    
    # Resize to target resolution maintaining aspect ratio (Crop-to-fit)
    # This prevents the "stretched/distorted" look.
    from PIL import ImageOps
    print("Resizing with Aspect Ratio preserved...")
    img = ImageOps.fit(base_img, (WIDTH, HEIGHT), method=Image.LANCZOS, centering=(0.5, 0.5))
    draw = ImageDraw.Draw(img)

    # Font handling - Try multiple known paths for Japanese fonts on macOS
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/Library/Fonts/Arial Unicode.ttf"
    ]
    
    font = None
    for path in font_paths:
        if os.path.exists(path):
            try:
                print(f"Loading font: {path}")
                font = ImageFont.truetype(path, 100) # Reduced from 110 to 100 for better balance
                break
            except Exception as e:
                print(f"Failed to load {path}: {e}")
    
    if font is None:
        print("Warning: No suitable Japanese font found. Using default (text may be garbled).")
        font = ImageFont.load_default()

    # Sections (Text, Center X, Center Y)
    # Visual adjustment based on the generated image structure
    # Increased offset to add space between icon and text
    offset_y = 350 # Increased from 280 to 350

    sections = [
        ("早見表", WIDTH * 0.25, HEIGHT * 0.25 + offset_y),
        ("予約変更", WIDTH * 0.75, HEIGHT * 0.25 + offset_y),
        ("予約する", WIDTH * 0.25, HEIGHT * 0.75 + offset_y),
        ("予約確認", WIDTH * 0.75, HEIGHT * 0.75 + offset_y),
    ]

    for text, cx, cy in sections:
        # Get text size
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Center horizontally
        x = cx - text_width / 2
        y = cy - text_height / 2
        
        draw.text((x, y), text, font=font, fill=TEXT_COLOR)

    # Save
    img = img.convert("RGB") # Ensure RGB for JPEG
    img.save(OUTPUT_PATH, "JPEG", quality=95)
    print(f"Created {OUTPUT_PATH}")

if __name__ == "__main__":
    create_final_image()
