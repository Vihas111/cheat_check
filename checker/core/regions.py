"""Ignore part of an image: a region the marker boxed (for example the question header or a tool bar).

A rule stores the boxed patch. On every re-scan the patch is searched for in each image of the assignment (template
matching over a range of scales, so other screen sizes still match). Where it is found, that area is blanked before
the image is fingerprinted and the text read from inside it is dropped, so shared given material cannot match."""

import json
import logging
import uuid
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from sqlalchemy import delete, func, select

from checker.config import get_settings
from checker.core import fingerprint as fp
from checker.core.db import Assignment, Item, Shingle, Submission, Whitelist
from checker.core.normalize import normalize_text
from checker.core.ocr import lines_to_text

log = logging.getLogger(__name__)

IMAGE_KINDS = ("image", "page_render")
SEARCH_SIDE = 480  # images are searched at most this big: fast, and plenty exact for a blanked box
SCALES = (0.5, 0.6, 0.75, 0.9, 1.0, 1.15, 1.35, 1.6, 2.0)
MIN_SCORE = 0.82  # normalized correlation needed to say "this patch is here"
MIN_CONTRAST = 12  # a flat patch would "match" everywhere
FULLY_IGNORED = 0.8  # an image that is mostly ignored region is left out of image matching altogether


def _dir() -> Path:
    d = get_settings().data_dir / "regions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gray_small(path: Path) -> np.ndarray:
    im = Image.open(path).convert("L")
    s = min(1.0, SEARCH_SIDE / max(im.size))
    if s < 1:
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    return np.asarray(im)


def locate(target: np.ndarray, patch: np.ndarray, min_score: float = MIN_SCORE) -> list[float] | None:
    """Where the patch appears in the target -> [x0, y0, x1, y1] as fractions, or None."""
    th, tw = target.shape
    best, box = 0.0, None
    for f in SCALES:
        p = cv2.resize(patch, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
        ph, pw = p.shape
        if ph < 8 or pw < 8 or ph > th or pw > tw:
            continue
        score = cv2.minMaxLoc(cv2.matchTemplate(target, p, cv2.TM_CCOEFF_NORMED))
        if score[1] > best:
            best, box = score[1], (score[3][0], score[3][1], pw, ph)
    if box is None or best < min_score:
        return None
    x, y, w, h = box
    return [x / tw, y / th, (x + w) / tw, (y + h) / th]


def add_region(item_id: int, box: list[float], note: str = "") -> str | None:
    """Store a rule for this boxed part of an item's image. Returns the assignment name, or None if unusable."""
    x0, y0, x1, y1 = (min(max(float(v), 0.0), 1.0) for v in box)
    x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    if x1 - x0 < 0.01 or y1 - y0 < 0.01:
        return None
    from checker.core.db import session_scope
    with session_scope() as db:
        it = db.get(Item, item_id)
        if not it or not it.thumb_path:
            return None
        gray = _gray_small(get_settings().data_dir / it.thumb_path)
        h, w = gray.shape
        patch = gray[int(y0 * h):max(int(y1 * h), int(y0 * h) + 1), int(x0 * w):max(int(x1 * w), int(x0 * w) + 1)]
        name = it.submission.assignment.name
        rid = uuid.uuid4().hex[:8]
        file = f"{rid}.png"
        Image.fromarray(patch).save(_dir() / file)
        rule = {"file": file, "box": [x0, y0, x1, y1], "src_item": item_id, "contrast": float(patch.std())}
        reason = f'ignored image region #{rid} from {it.submission.filename}, {note or f"page {it.page}"}'
        db.add(Whitelist(kind="region", fingerprint=json.dumps(rule), scope=name, reason=reason))
    return name


def delete_files(rules: list[Whitelist]) -> None:
    for w in rules:
        try:
            (_dir() / json.loads(w.fingerprint)["file"]).unlink(missing_ok=True)
        except (ValueError, KeyError, OSError):
            pass


def _rules(db, assignment_name: str) -> list[dict]:
    out = []
    for w in db.scalars(select(Whitelist).where(Whitelist.kind == "region", Whitelist.scope == assignment_name)):
        try:
            r = json.loads(w.fingerprint)
            patch = np.asarray(Image.open(_dir() / r["file"]).convert("L"))
        except (ValueError, KeyError, OSError):
            log.warning("ignored region %s is unreadable; skipping", w.reason)
            continue
        out.append({**r, "patch": patch})
    return out


def _merge(boxes: list[list[float]]) -> list[list[float]]:
    return [[round(v, 4) for v in b] for b in boxes]


def paint(im: Image.Image, boxes: list[list[float]]) -> Image.Image:
    """Blank the boxed areas with flat grey (same grey everywhere, so matching images stay matching)."""
    if not boxes:
        return im
    im = im.convert("RGB").copy()
    w, h = im.size
    arr = np.asarray(im).copy()
    for x0, y0, x1, y1 in boxes:
        arr[int(y0 * h):int(np.ceil(y1 * h)), int(x0 * w):int(np.ceil(x1 * w))] = 127
    return Image.fromarray(arr)


def _covered(boxes: list[list[float]], size=(100, 100)) -> float:
    m = np.zeros(size, bool)
    for x0, y0, x1, y1 in boxes:
        m[int(y0 * size[0]):int(np.ceil(y1 * size[0])), int(x0 * size[1]):int(np.ceil(x1 * size[1]))] = True
    return float(m.mean())


def _apply_item(db, it: Item, boxes: list[list[float]]) -> None:
    """(Re)compute the hashes and text of one image with the boxes blanked. No boxes restores the originals."""
    s = get_settings()
    im = Image.open(s.data_dir / it.thumb_path).convert("RGB")
    if boxes and _covered(boxes) >= FULLY_IGNORED:
        it.phash = it.dhash = it.whash = None  # nothing left to compare
        it.hash_variants_json = None
    else:
        h = fp.image_hashes(paint(im, boxes), s.phash_size)
        it.phash, it.dhash, it.whash, it.hash_variants_json = h["phash"], h["dhash"], h["whash"], h["variants"]
    words = it.ocr_words_json or []
    if boxes and words:
        w, hh = max(it.width, 1), max(it.height, 1)

        def inside(b):
            cx, cy = (b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / hh
            return any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in boxes)

        kept = [x for x in words if not inside(x["bbox"])]
        it.norm_text = normalize_text(lines_to_text(kept))
    else:
        it.norm_text = normalize_text(it.ocr_text)
    it.masks_json = boxes or None
    db.execute(delete(Shingle).where(Shingle.item_id == it.id))
    prints = {"word": fp.word_shingles(it.norm_text, s.shingle_k),
              "line": fp.line_hashes(it.norm_text, s.min_line_chars),
              "code": fp.code_fingerprints(it.norm_text, s.code_k, s.code_w)}
    rows = [{"hash": h, "submission_id": it.submission_id, "item_id": it.id, "kind": k}
            for k, hs in prints.items() for h in hs]
    if rows:
        db.execute(Shingle.__table__.insert(), rows)


def apply(db, assignment_id: int, sub_ids=None, progress=None) -> int:
    """Find every ignored region in the assignment's images and refresh what they feed. Returns images changed."""
    name = db.get(Assignment, assignment_id).name
    rules = _rules(db, name)
    q = select(Item).where(Item.is_content, Item.kind.in_(IMAGE_KINDS), Item.thumb_path.is_not(None))
    q = q.where(Item.submission_id.in_(select(Submission.id).where(Submission.assignment_id == assignment_id)))
    if sub_ids is not None:
        q = q.where(Item.submission_id.in_(list(sub_ids)))
    if not rules and not db.scalar(select(func.count()).select_from(Item).where(Item.masks_json.is_not(None))):
        return 0  # nothing to apply and nothing to undo
    items = db.scalars(q).all()
    data = get_settings().data_dir
    changed = 0
    found_cache: dict[tuple[str, str], list[float] | None] = {}  # pixel-identical images need searching once
    for i, it in enumerate(items):
        if progress:
            progress(i, len(items))
        boxes: list[list[float]] = []
        if rules:
            target = None
            for r in rules:
                if r["src_item"] == it.id:
                    boxes.append(r["box"])
                elif r["contrast"] >= MIN_CONTRAST:
                    key = (it.sha256 or f"item{it.id}", r["file"])
                    if key not in found_cache:
                        if target is None:
                            target = _gray_small(data / it.thumb_path)
                        found_cache[key] = locate(target, r["patch"])
                    if found_cache[key]:
                        boxes.append(found_cache[key])
        boxes = _merge(boxes)
        if boxes != (it.masks_json or []):
            _apply_item(db, it, boxes)
            changed += 1
    db.flush()
    return changed
