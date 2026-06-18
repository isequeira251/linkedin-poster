"""Render a LinkedIn post card: stock photo of people working, byline strip, and
a short, punchy caption overlaid in the top-right corner.

Corner-text (the words on the photo):
- The overlay is a SHORT, PUNCHY caption (<=CAPTION_MAX_WORDS words) distilled
  from the post's theme by a cheap LLM call (Anthropic; model from
  ANTHROPIC_MODEL, default claude-haiku-4-5), cached on a hash of the post text
  so re-renders cost ~$0.
- If the LLM is unavailable (no ANTHROPIC_API_KEY / error / SDK missing), it
  falls back to the deterministic first-paragraph hook so the card ALWAYS
  renders.
- show / hide: an explicit `bubble=True/False` always wins. Otherwise the
  caption shows whenever we have an LLM caption (it is always short + legible);
  for the deterministic fallback it shows only when shorter than
  CORNER_HOOK_MAX_CHARS.

Requires: pip install anthropic  (optional — the card still renders without it)

Usage as a library:
    from generate_card import generate_card
    png_bytes = generate_card("Your hook here.")

CLI:
    python generate_card.py "Your hook here." out.png

Background photo selection (in order):
1. If PEXELS_API_KEY is set, fetch a fresh photo from Pexels using a randomized
   "people working" search query, avoiding the most recently used ID.
2. Otherwise, pick a random image (.jpg/.jpeg/.png) from the assets/ folder.
3. If nothing usable, fall back to a solid navy canvas.
"""

import hashlib
import io
import json
import os
import random
import sys
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

CARD_SIZE = 1200
ASSETS = Path(__file__).parent / "assets"
LAST_PHOTO_FILE = Path(__file__).parent / ".last_photo.json"

PEXELS_QUERIES = [
    "people working in office",
    "team collaborating",
    "office meeting",
    "coworkers laptop",
    "professionals working together",
    "business team brainstorming",
    "open office workspace",
    "colleagues discussing project",
]

CORNER_TEXT_COLOR = (255, 255, 255)       # white, reads over the darkened photo
CORNER_TEXT_OUTLINE = (10, 37, 64)        # deep navy outline for legibility
BYLINE_COLOR = (255, 255, 255)
BYLINE_TAG_COLOR = (190, 215, 255)
OVERLAY_OPACITY = 110                     # 0..255; higher = darker photo

# Top-right corner text block. Lines are right-aligned, anchored CORNER_MARGIN
# from the top and right edges.
CORNER_MARGIN = 60
CORNER_TEXT_W = 620                       # max width of the text block
CORNER_TEXT_H = 380                       # max height of the text block
CORNER_TEXT_RIGHT = CARD_SIZE - CORNER_MARGIN
CORNER_TEXT_TOP = CORNER_MARGIN
CORNER_TEXT_OUTLINE_W = 3
CORNER_START_FONT = 60                    # largest font size tried for corner text
# Deterministic-fallback heuristic: when the LLM caption is unavailable, only
# short hooks get the corner caption — longer ones clutter the card.
CORNER_HOOK_MAX_CHARS = 120

# Punchy caption: a cheap LLM distills the post into a short theme line for the
# photo overlay. Model comes from ANTHROPIC_MODEL (CI pins sonnet-4-6); defaults
# to Haiku locally. Result is cached on a hash of the post text so re-renders are
# free, and any failure falls back to the deterministic hook (card never fails).
CAPTION_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
CAPTION_MAX_WORDS = 6  # target asked of the model (3-5 is ideal)
CAPTION_RUNAWAY_WORDS = 9  # only trim output longer than this (guards runaways)
CAPTION_CACHE_FILE = Path(__file__).parent / ".caption_cache.json"
CAPTION_SYSTEM = (
    "You write ultra-short text overlays for a LinkedIn image card by Ian "
    'Sequeira, whose tagline is "Notes on CRM performance" (HubSpot / CRM / '
    "revenue operations).\n"
    "Given the full text of one of his posts, return ONE punchy caption that "
    "captures the post's core idea — the kind of tight hook that reads well as "
    "large text on a photo.\n"
    "Rules:\n"
    f"- At most {CAPTION_MAX_WORDS} words (3-5 is ideal). No trailing period.\n"
    "- No surrounding quotes, no emoji, no hashtags, no markdown.\n"
    "- Capture the *idea*; do not just copy the first sentence verbatim.\n"
    '- Concrete and specific, not generic ("Stop guessing your lead source", '
    'not "Thoughts on CRM").\n'
    "Return only the caption text, nothing else."
)

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


def _caption_cache() -> dict:
    try:
        return json.loads(CAPTION_CACHE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _clean_caption(text: str) -> str:
    """Normalize the model's reply into a bare caption: first line, no quotes or
    trailing punctuation. We only trim genuinely runaway output — the prompt asks
    for <=CAPTION_MAX_WORDS words, and clipping a 7-8 word phrase mid-thought
    reads worse than letting the font shrink, so the guard is deliberately loose."""
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    line = line.strip("\"'“”‘’ ").rstrip(".,;:!").strip()
    words = line.split()
    if len(words) > CAPTION_RUNAWAY_WORDS:
        line = " ".join(words[:CAPTION_RUNAWAY_WORDS]) + "…"
    return line


def _punchy_caption(post_text: str) -> str | None:
    """Distill the post into a short, punchy theme caption via a cheap LLM call.

    Cached on a hash of the post text (re-renders cost ~$0). Returns None if the
    Anthropic SDK/key is unavailable or the call fails, so the caller can fall
    back to the deterministic hook — the card must never fail to render.
    """
    key = hashlib.sha256(post_text.strip().encode("utf-8")).hexdigest()
    cache = _caption_cache()
    if key in cache:
        return cache[key] or None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=CAPTION_MODEL,
            max_tokens=32,
            system=CAPTION_SYSTEM,
            messages=[{"role": "user", "content": post_text.strip()[:4000]}],
        )
        raw = next((b.text for b in resp.content if b.type == "text"), "")
        caption = _clean_caption(raw)
    except Exception as e:  # never let caption generation break the render
        print(f"WARN: caption LLM failed ({e}); using deterministic hook.", file=sys.stderr)
        return None
    if not caption:
        return None
    cache[key] = caption
    try:
        CAPTION_CACHE_FILE.write_text(json.dumps(cache, indent=2) + "\n")
    except OSError:
        pass
    print(f"Caption: {caption!r} (model={CAPTION_MODEL})", file=sys.stderr)
    return caption


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


def _fit_font_size(
    text: str,
    max_width: int,
    max_height: int,
    draw: ImageDraw.ImageDraw,
    start_size: int = 76,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    for size in range(start_size, 18, -2):
        font = _font(FONT_BOLD, FALLBACK_BOLD, size)
        lines = _wrap_to_fit(text, font, max_width, draw)
        line_height = int(size * 1.28)
        total_height = line_height * len(lines)
        if total_height <= max_height:
            return font, lines, line_height
    font = _font(FONT_BOLD, FALLBACK_BOLD, 32)
    return font, _wrap_to_fit(text, font, max_width, draw), int(32 * 1.28)


def _read_last_photo_id() -> str | None:
    try:
        return json.loads(LAST_PHOTO_FILE.read_text()).get("pexels_id")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_last_photo_id(photo_id: str) -> None:
    try:
        LAST_PHOTO_FILE.write_text(json.dumps({"pexels_id": photo_id}) + "\n")
    except OSError:
        pass


def _fetch_pexels_photo() -> Image.Image | None:
    """Try to fetch a fresh 'people working' photo from Pexels. Returns None on any failure."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return None
    query = random.choice(PEXELS_QUERIES)
    last_id = _read_last_photo_id()
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": 40, "orientation": "square"},
            timeout=15,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        candidates = [p for p in photos if str(p.get("id")) != str(last_id)] or photos
        if not candidates:
            print(f"WARN: Pexels returned 0 photos for query {query!r}", file=sys.stderr)
            return None
        chosen = random.choice(candidates)
        img_url = chosen["src"].get("large2x") or chosen["src"].get("original")
        img_resp = requests.get(img_url, timeout=30)
        img_resp.raise_for_status()
        _write_last_photo_id(str(chosen["id"]))
        print(
            f"Pexels: query={query!r} photo_id={chosen['id']} "
            f"by={chosen.get('photographer', '?')}",
            file=sys.stderr,
        )
        return Image.open(io.BytesIO(img_resp.content)).convert("RGB")
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"WARN: Pexels fetch failed ({e}); falling back to local assets.", file=sys.stderr)
        return None


def _pick_local_photo() -> Image.Image | None:
    if not ASSETS.exists():
        return None
    candidates = [
        p for p in ASSETS.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    if not candidates:
        return None
    chosen = random.choice(candidates)
    print(f"Local background: {chosen.name}", file=sys.stderr)
    return Image.open(chosen).convert("RGB")


def _prepare_background() -> Image.Image:
    photo = _fetch_pexels_photo() or _pick_local_photo()
    if photo is None:
        return Image.new("RGB", (CARD_SIZE, CARD_SIZE), (40, 50, 70))
    w, h = photo.size
    scale = max(CARD_SIZE / w, CARD_SIZE / h)
    photo = photo.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    left = (photo.width - CARD_SIZE) // 2
    top = (photo.height - CARD_SIZE) // 2
    photo = photo.crop((left, top, left + CARD_SIZE, top + CARD_SIZE))
    overlay = Image.new("RGBA", (CARD_SIZE, CARD_SIZE), (0, 0, 0, OVERLAY_OPACITY))
    photo = Image.alpha_composite(photo.convert("RGBA"), overlay)
    return photo


def _draw_corner_text(canvas: Image.Image, hook: str) -> None:
    """Render the hook as right-aligned text in the top-right corner of the photo.

    White text with a navy outline keeps it legible over any background, with no
    bubble or container around it.
    """
    draw = ImageDraw.Draw(canvas)
    font, lines, line_height = _fit_font_size(
        hook, CORNER_TEXT_W, CORNER_TEXT_H, draw, start_size=CORNER_START_FONT
    )
    y = CORNER_TEXT_TOP
    for line in lines:
        line_w = draw.textlength(line, font=font)
        x = CORNER_TEXT_RIGHT - line_w  # right-align against the right margin
        draw.text(
            (x, y),
            line,
            font=font,
            fill=CORNER_TEXT_COLOR,
            stroke_width=CORNER_TEXT_OUTLINE_W,
            stroke_fill=CORNER_TEXT_OUTLINE,
        )
        y += line_height


def generate_card(
    post_text: str,
    output_path: str | Path | None = None,
    *,
    bubble: bool | None = None,
) -> bytes:
    canvas = _prepare_background()

    llm_caption = _punchy_caption(post_text)
    hook = llm_caption or extract_hook(post_text)
    if bubble is not None:
        show_text = bubble
    elif llm_caption:
        show_text = True  # punchy caption is always short + legible
    else:
        show_text = len(hook) < CORNER_HOOK_MAX_CHARS  # deterministic fallback
    print(
        f"Card: caption={hook!r} source={'llm' if llm_caption else 'hook'} "
        f"corner_text={show_text} (override={bubble!r})",
        file=sys.stderr,
    )

    if show_text:
        _draw_corner_text(canvas, hook)

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
