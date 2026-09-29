"""PDF -> images, page renders, visible/hidden text layer, metadata (plan.md §6.1)."""

import hashlib
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image

from checker.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class ExtractedImage:
    page: int
    idx: int
    kind: str  # image | page_render
    source: str  # embedded | render_crop | render
    image: Image.Image
    bbox: list[float] | None = None  # PDF points on the page
    raw_sha256: str | None = None
    is_content: bool = True


@dataclass
class ExtractedPage:
    number: int
    width: float
    height: float
    text: str  # visible text layer only
    spans: list[dict] = field(default_factory=list)
    hidden_spans: list[dict] = field(default_factory=list)
    path: str = ""  # which extraction path was used, for logging/debug


@dataclass
class ExtractedSubmission:
    path: Path
    sha256: str
    page_count: int
    meta: dict
    images: list[ExtractedImage]
    pages: list[ExtractedPage]
    skipped_images: int = 0


def _pix_to_pil(doc: pymupdf.Document, xref: int, smask: int) -> Image.Image:
    pix = pymupdf.Pixmap(doc, xref)
    if pix.colorspace and pix.colorspace.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if smask:
        try:
            pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, smask))
        except Exception as e:  # mask size mismatch etc.: keep the unmasked image
            log.warning("smask %s on xref %s ignored: %s", smask, xref, e)
    im = Image.open(io.BytesIO(pix.tobytes("png")))
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    return im.convert("RGB")


def _is_junk(im: Image.Image, min_px: int, uniform_std: float) -> bool:
    if im.width < min_px or im.height < min_px:
        return True
    small = im.convert("L").resize((64, 64))
    return float(np.asarray(small).std()) < uniform_std


def _render(page: pymupdf.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _text_layer(page: pymupdf.Page, render: np.ndarray, zoom: float) -> tuple[str, list, list]:
    """Split text spans into visible and hidden. Hidden = tiny font, outside the page box,
    or no visible contrast where it is drawn (white-on-white, render mode 3, covered)."""
    gray = cv2.cvtColor(render, cv2.COLOR_RGB2GRAY)
    prect = page.rect
    visible, hidden, lines_out = [], [], []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            parts = []
            for sp in line["spans"]:
                text = sp["text"]
                if not text.strip():
                    parts.append(text)
                    continue
                r = pymupdf.Rect(sp["bbox"])
                info = {"text": text, "size": round(sp["size"], 2), "color": f"#{sp['color']:06x}",
                        "font": sp["font"], "bbox": [round(v, 1) for v in r]}
                reason = None
                if sp["size"] < 3:
                    reason = "font_size_lt_3pt"
                elif not r.intersects(prect) or (r & prect).get_area() < 0.5 * max(r.get_area(), 1e-6):
                    reason = "outside_page"
                elif len(text.strip()) >= 3:  # single glyphs like "." have too few pixels to judge
                    x0, y0, x1, y1 = (int(v * zoom) for v in (r.x0, r.y0, r.x1, r.y1))
                    region = gray[max(y0, 0):y1 + 1, max(x0, 0):x1 + 1]
                    if region.size and float(region.std()) < 6:
                        reason = "no_visible_contrast"
                if reason:
                    info["reason"] = reason
                    hidden.append(info)
                else:
                    visible.append(info)
                    parts.append(text)
            if "".join(parts).strip():
                lines_out.append("".join(parts))
    return "\n".join(lines_out), visible, hidden


def _segment_regions(render: np.ndarray, mask_rects: list, min_px: int) -> list[tuple[int, int, int, int]]:
    """Contour-based crop of non-background regions (for screenshot pages with no image objects)."""
    gray = cv2.cvtColor(render, cv2.COLOR_RGB2GRAY)
    border = np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
    bg = int(np.median(border))
    mask = (np.abs(gray.astype(np.int16) - bg) > 12).astype(np.uint8) * 255
    for x0, y0, x1, y1 in mask_rects:  # ignore text lines and embedded images, already items
        mask[max(y0 - 3, 0):y1 + 4, max(x0 - 3, 0):x1 + 4] = 0  # pad: anti-aliased edges
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    out = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw >= min_px and ch >= min_px and cw * ch < 0.9 * w * h:
            out.append((x, y, x + cw, y + ch))
    return sorted(out, key=lambda r: (r[1], r[0]))


def pdf_metadata(doc: pymupdf.Document, raw: bytes) -> dict:
    fonts = set()
    for p in doc:
        fonts.update(f[3] for f in p.get_fonts())
    return {
        "info": {k: v for k, v in (doc.metadata or {}).items() if v},
        "xmp": (doc.get_xml_metadata() or "")[:20000],
        "eof_count": raw.count(b"%%EOF"),
        "incremental_updates": max(0, raw.count(b"%%EOF") - 1),
        "fonts": sorted(fonts),
        "page_count": doc.page_count,
    }


def extract(path: Path) -> ExtractedSubmission:
    s = get_settings()
    raw = Path(path).read_bytes()
    doc = pymupdf.open(stream=raw, filetype="pdf")
    zoom = s.render_dpi / 72
    images: list[ExtractedImage] = []
    pages: list[ExtractedPage] = []
    skipped = 0

    for pno, page in enumerate(doc):
        render_im = _render(page, s.render_dpi)
        render = np.asarray(render_im)
        text, spans, hidden = _text_layer(page, render, zoom)
        epage = ExtractedPage(pno + 1, page.rect.width, page.rect.height, text, spans, hidden)
        page_area = page.rect.get_area() or 1
        n_before = len(images)
        idx = 0
        covered = 0.0
        seen_xrefs = set()
        image_rects = []

        # 1. embedded image objects
        for img in page.get_images(full=True):
            xref, smask = img[0], img[1]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                im = _pix_to_pil(doc, xref, smask)
                raw_sha = hashlib.sha256(doc.xref_stream_raw(xref) or b"").hexdigest()
            except Exception as e:
                log.warning("page %s xref %s unreadable: %s", pno + 1, xref, e)
                continue
            rects = page.get_image_rects(xref)
            bbox = list(rects[0]) if rects else None
            covered += sum((r & page.rect).get_area() for r in rects)
            image_rects += [tuple(int(v * zoom) for v in r) for r in rects]
            if _is_junk(im, s.min_image_px, s.uniform_std):
                skipped += 1
                continue
            images.append(ExtractedImage(pno + 1, idx, "image", "embedded", im, bbox, raw_sha))
            idx += 1

        # ponytail: coverage sums rect areas (overlaps double count); fine for the 60% heuristic
        coverage = min(1.0, covered / page_area)
        paths = ["embedded"] if len(images) > n_before else []

        # 2. regions not captured by get_images(): inline images via get_image_info, else contours
        if coverage < s.embedded_coverage_min:
            infos = [i for i in page.get_image_info(xrefs=True) if i.get("xref", 0) not in seen_xrefs]
            boxes = []
            for info in infos:
                r = pymupdf.Rect(info["bbox"]) & page.rect
                if not r.is_empty:
                    boxes.append(tuple(int(v * zoom) for v in r))
            if boxes:
                paths.append("image_info")
            else:
                known = [tuple(int(v * zoom) for v in sp["bbox"]) for sp in spans] + image_rects
                boxes = _segment_regions(render, known, s.min_image_px)
                if boxes:
                    paths.append("contours")
            for x0, y0, x1, y1 in boxes:
                crop = render_im.crop((x0, y0, x1, y1))
                if _is_junk(crop, s.min_image_px, s.uniform_std):
                    skipped += 1
                    continue
                images.append(ExtractedImage(pno + 1, idx, "image", "render_crop", crop,
                                             [x0 / zoom, y0 / zoom, x1 / zoom, y1 / zoom]))
                idx += 1

        # 3. always keep the full page render; it is content only when nothing else covers the page
        has_content = len(images) > n_before or len(text.strip()) >= 20
        if not has_content:
            paths.append("page_render")
        images.append(ExtractedImage(pno + 1, idx, "page_render", "render", render_im,
                                     [0, 0, page.rect.width, page.rect.height], is_content=not has_content))
        epage.path = "+".join(paths) or "text_only"
        log.info("page %s: %s (embedded coverage %.0f%%)", pno + 1, epage.path, coverage * 100)
        pages.append(epage)

    meta = pdf_metadata(doc, raw)
    count = doc.page_count
    doc.close()
    return ExtractedSubmission(Path(path), hashlib.sha256(raw).hexdigest(), count, meta, images, pages, skipped)
