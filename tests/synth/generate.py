"""Building blocks for synthetic screenshot PDFs used by tests and `cli synth`."""

import io
import random
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/noto/NotoSansMono-Regular.ttf",
    "C:/Windows/Fonts/consola.ttf",
]
# Unicode text-layer font (Cyrillic look-alikes for the homoglyph case).
_PDF_FONTS = ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/TTF/DejaVuSans.ttf"]


def font(size=20):
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def screenshot(lines: list[str], *, dark=True, width=900, size=20, seed=0, title=None) -> Image.Image:
    """Fake terminal/editor screenshot: window chrome + monospace text + some noise."""
    rnd = random.Random(seed)
    f = font(size)
    lh = int(size * 1.4)
    h = 60 + lh * len(lines) + 30
    bg, fg = ((30, 30, 30), (220, 220, 220)) if dark else ((250, 250, 250), (20, 20, 20))
    im = Image.new("RGB", (width, h), bg)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, width, 36), fill=(60, 60, 70) if dark else (220, 220, 225))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse((12 + i * 24, 10, 28 + i * 24, 26), fill=c)
    d.text((110, 8), title or f"session-{rnd.randint(100, 999)}", font=font(16), fill=fg)
    for i, ln in enumerate(lines):
        d.text((20, 50 + i * lh), ln, font=f, fill=fg)
    return im


def png_bytes(im: Image.Image, fmt="PNG", **kw) -> bytes:
    b = io.BytesIO()
    im.save(b, fmt, **kw)
    return b.getvalue()


def make_pdf(path: Path, pages: list[list[Image.Image]], *, meta: dict | None = None, text: str | None = None,
             hidden_text: str | None = None, fmt="PNG") -> Path:
    """One or more embedded images per page, stacked vertically on A4."""
    doc = pymupdf.open()
    for imgs in pages:
        page = doc.new_page(width=595, height=842)
        y = 40
        if text:
            ff = next((f for f in _PDF_FONTS if Path(f).exists()), None) if not text.isascii() else None
            page.insert_text((40, y), text, fontsize=11, **({"fontfile": ff, "fontname": "uni"} if ff else {}))
            y += 20
        for im in imgs:
            w = 515
            h = w * im.height / im.width
            page.insert_image(pymupdf.Rect(40, y, 40 + w, y + h), stream=png_bytes(im, fmt))
            y += h + 15
        if hidden_text:
            page.insert_text((40, 830), hidden_text, fontsize=8, color=(1, 1, 1))
    doc.set_metadata(meta or {"producer": "synth", "creator": "synth"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def make_inline_image_pdf(path: Path, im: Image.Image) -> Path:
    """Screenshot painted as an inline image (BI..ID..EI): get_images() returns nothing."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    im = im.convert("RGB")
    w, h = 515, 515 * im.height / im.width
    data = im.tobytes().hex().encode() + b">"
    stream = (f"q {w:.2f} 0 0 {h:.2f} 40 {842 - 40 - h:.2f} cm\n"
              f"BI /W {im.width} /H {im.height} /CS /RGB /BPC 8 /F /AHx ID\n").encode() + data + b"\nEI Q\n"
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")
    doc.set_metadata({"producer": "synth-inline"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def make_vector_pdf(path: Path) -> Path:
    """A 'window' drawn with vector shapes only: no image objects at all (contour path)."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(pymupdf.Rect(60, 100, 520, 400), color=None, fill=(0.12, 0.12, 0.12))
    page.draw_rect(pymupdf.Rect(60, 100, 520, 122), color=None, fill=(0.3, 0.3, 0.35))
    for i in range(8):
        page.draw_line((80, 140 + i * 30), (80 + 40 * (i % 5 + 3), 140 + i * 30), color=(0.8, 0.8, 0.8), width=3)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path
