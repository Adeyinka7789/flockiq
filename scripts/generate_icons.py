"""Generate PWA icons for FlockIQ — navy #3d5a99 background, white 'FQ' text."""
import os

from PIL import Image, ImageDraw, ImageFont

os.makedirs('static/icons', exist_ok=True)

for size in [192, 512]:
    img = Image.new('RGB', (size, size), '#3d5a99')
    draw = ImageDraw.Draw(img)
    text = 'FQ'
    font_size = size // 3
    try:
        font = ImageFont.truetype('arial.ttf', font_size)
    except OSError:
        try:
            font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', font_size)
        except OSError:
            font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) // 2, (size - h) // 2), text, fill='white', font=font)
    img.save(f'static/icons/icon-{size}.png')
    print(f'Created static/icons/icon-{size}.png')
