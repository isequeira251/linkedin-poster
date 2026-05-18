"""Render a LinkedIn post card with a thought-bubble quote over a stock photo of people working.

Usage as a library:
    from generate_card import generate_card
    png_bytes = generate_card("Your hook here.")

CLI:
    python generate_card.py "Your hook here." out.png
"""

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CARD_SIZE = 1200
ASSETS = Path(__file__).parent / "assets"
STOCK_PHOTO = ASSETS / "office.jpg"

BUBBLE_COLOR = (255, 255, 255)
BUBBLE_TEXT_COLOR = (10, 37, 64)         # deep navy
BYLINE_COLOR = (255, 255, 255)
BYLINE_TAG_COLOR = (190, 215, 255)
OVERLAY_OPACITY = 110                     # 0..255; higher = darker photo

BUBBLE_W = 300
BUBBLE_H = 200
BUBBLE_X = CARD_SIZE - BUBBLE_W - 50  # far right, 50px margin from right edge
BUBBLE_Y = 90
BUBBLE_RADIUS = 24
BUBBLE_PAD = 26

# Trail drifts down-left from bubble's bottom-left toward the woman in white
THOUGHT_TRAIL = [
    (BUBBLE_X + 18, BUBBLE_Y + BUBBLE_H + 8, 24),
    (BUBBLE_X - 8, BUBBLE_Y + BUBBLE_H + 38, 16),
    (BUBBLE_X - 28, BUBBLE_Y + BUBBLE_H + 62, 10),
]

BYLINE_NAME = "Ian Sequeira"
BYLINE_TAG = "Notes on CRM performance"

FONT_REGULAR = "/usr/share/fonts/chromeos/croscore/Arimo-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/chromeos/croscore/Arimo-Bold.ttf"
FALLBACK_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FALLBACK_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(path: str, fallback: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype(fallback, size)


def extract_hook(post_text: str, max_chars: int = 220) -> str:
    first_paragraph = post_text.split("\n\n", 1)[0].strip()
    if len(first_paragraph) <= max_chars:
        return first_paragraph
    cut = first_paragraph[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


def _wrap_to_fit(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_font_size(text: str, max_width: int, max_height: int, draw: ImageDraw.ImageDraw) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    for size in range(76, 18, -2):
        font = _font(FONT_BOLD, FALLBACK_BOLD, size)
        lines = _wrap_to_fit(text, font, max_width, draw)
        line_height = int(size * 1.28)
        total_height = line_height * len(lines)
        if total_height <= max_height:
            return font, lines, line_height
    font = _font(FONT_BOLD, FALLBACK_BOLD, 32)
    return font, _wrap_to_fit(text, font, max_width, draw), int(32 * 1.28)


def _prepare_background() -> Image.Image:
    if not STOCK_PHOTO.exists():
        return Image.new("RGB", (CARD_SIZE, CARD_SIZE), (40, 50, 70))
    photo = Image.open(STOCK_PHOTO).convert("RGB")
    w, h = photo.size
    scale = max(CARD_SIZE / w, CARD_SIZE / h)
    photo = photo.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    left = (photo.width - CARD_SIZE) // 2
    top = (photo.height - CARD_SIZE) // 2
    photo = photo.crop((left, top, left + CARD_SIZE, top + CARD_SIZE))
    overlay = Image.new("RGBA", (CARD_SIZE, CARD_SIZE), (0, 0, 0, OVERLAY_OPACITY))
    photo = Image.alpha_composite(photo.convert("RGBA"), overlay)
    return photo


def _draw_thought_bubble(canvas: Image.Image) -> None:
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    shadow_draw.rounded_rectangle(
        [BUBBLE_X + 6, BUBBLE_Y + 12, BUBBLE_X + BUBBLE_W + 6, BUBBLE_Y + BUBBLE_H + 12],
        radius=BUBBLE_RADIUS,
        fill=(0, 0, 0, 90),
    )
    for cx, cy, d in THOUGHT_TRAIL:
        shadow_draw.ellipse([cx + 6 - d // 2, cy + 12 - d // 2, cx + 6 + d // 2, cy + 12 + d // 2], fill=(0, 0, 0, 70))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=10))
    canvas.alpha_composite(shadow_layer)

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        [BUBBLE_X, BUBBLE_Y, BUBBLE_X + BUBBLE_W, BUBBLE_Y + BUBBLE_H],
        radius=BUBBLE_RADIUS,
        fill=BUBBLE_COLOR,
    )
    for cx, cy, d in THOUGHT_TRAIL:
        draw.ellipse([cx - d // 2, cy - d // 2, cx + d // 2, cy + d // 2], fill=BUBBLE_COLOR)


def generate_card(post_text: str, output_path: str | Path | None = None) -> bytes:
    canvas = _prepare_background()

    _draw_thought_bubble(canvas)

    draw = ImageDraw.Draw(canvas)
    hook = extract_hook(post_text)
    text_max_width = BUBBLE_W - 2 * BUBBLE_PAD
    text_max_height = BUBBLE_H - 2 * BUBBLE_PAD
    font, lines, line_height = _fit_font_size(hook, text_max_width, text_max_height, draw)
    total_text_height = line_height * len(lines)
    y = BUBBLE_Y + BUBBLE_PAD + (text_max_height - total_text_height) // 2
    for line in lines:
        line_w = draw.textlength(line, font=font)
        x = BUBBLE_X + (BUBBLE_W - line_w) // 2
        draw.text((x, y), line, font=font, fill=BUBBLE_TEXT_COLOR)
        y += line_height

    byline_strip = Image.new("RGBA", (CARD_SIZE, 140), (10, 37, 64, 220))
    canvas.alpha_composite(byline_strip, (0, CARD_SIZE - 140))
    draw = ImageDraw.Draw(canvas)
    byline_font = _font(FONT_BOLD, FALLBACK_BOLD, 38)
    tag_font = _font(FONT_REGULAR, FALLBACK_REGULAR, 26)
    draw.text((80, CARD_SIZE - 110), BYLINE_NAME, font=byline_font, fill=BYLINE_COLOR)
    draw.text((80, CARD_SIZE - 60), BYLINE_TAG, font=tag_font, fill=BYLINE_TAG_COLOR)

    out = canvas.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()
    if output_path:
        Path(output_path).write_bytes(png_bytes)
    return png_bytes


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python generate_card.py "post text" [out.png]', file=sys.stderr)
        return 1
    text = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "card.png"
    generate_card(text, out)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
