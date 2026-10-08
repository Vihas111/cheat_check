"""Ignored content: passages and image parts the marker said do not count.

A rule is made once, from one PDF, and is then looked for in every PDF of the assignment:

* a **text** rule (selected lines, or the text inside a boxed image part) is found in other PDFs by fuzzy matching
  against their OCR text, so a different font size, theme, line wrapping or small OCR errors do not hide it;
* an **image** rule (a boxed part) also keeps the boxed pixels and searches for them at several scales, for parts
  that carry no text, such as icons or tool bars.

Wherever a rule is found, that text stops counting and that area of the image is blanked before the image is
fingerprinted and feature-matched. So two other PDFs that only share the ignored passage no longer match."""

import json
import logging
import uuid
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from rapidfuzz import fuzz
from sqlalchemy import delete, func, select

from checker.config import get_settings
from checker.core import fingerprint as fp
from checker.core.db import Assignment, Item, Shingle, Submission, Whitelist
from checker.core.normalize import normalize_text
from checker.core.ocr import group_lines

log = logging.getLogger(__name__)

IMAGE_KINDS = ("image", "page_render")
RULE_KINDS = ("region", "snippet")
SEARCH_SIDE = 480  # images are searched at most this big: fast, and plenty exact for a blanked box
SCALES = (0.5, 0.6, 0.75, 0.9, 1.0, 1.15, 1.35, 1.6, 2.0)
MIN_SCORE = 0.82  # normalized correlation needed to say "this patch is here"
MIN_CONTRAST = 12  # a flat patch would "match" everywhere
FULLY_IGNORED = 0.8  # an image that is mostly ignored is left out of image matching altogether
TEXT_MATCH = 88  # fuzzy score (0-100) for "this line is the ignored passage"
MIN_TEXT = 8  # shorter passages are too generic to recognise
MASK_PAD = 0.004  # blank a little beyond a matched line


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


def locate_features(target: np.ndarray, patch: np.ndarray, min_inliers: int = 15) -> list[float] | None:
    """Find the patch in the target by local features (survives crops, resizes and small changes), for parts the
    pixel search misses. -> [x0, y0, x1, y1] as fractions of the target (clipped to it), or None."""
    orb = cv2.ORB_create(nfeatures=1500)
    kp, dp = orb.detectAndCompute(patch, None)
    kt, dt = orb.detectAndCompute(target, None)
    if dp is None or dt is None or len(kp) < min_inliers or len(kt) < min_inliers:
        return None
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(dp, dt, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < min_inliers:
        return None
    src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kt[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None or int(mask.sum()) < min_inliers:
        return None
    if not 0.3 < float(np.sqrt(abs(np.linalg.det(H[:2, :2])))) < 3.0:
        return None  # not a believable copy of the patch
    ph, pw = patch.shape
    corners = cv2.perspectiveTransform(np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]]).reshape(-1, 1, 2), H).reshape(-1, 2)
    th, tw = target.shape
    x0, y0 = np.clip(corners.min(axis=0), 0, [tw, th])
    x1, y1 = np.clip(corners.max(axis=0), 0, [tw, th])
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return [float(x0 / tw), float(y0 / th), float(x1 / tw), float(y1 / th)]


def strip_snippet(line: str, snippet: str) -> tuple[str, bool]:
    """Take an ignored passage out of one line of text, tolerating OCR noise.
    -> (what is left of the line, whether the passage was found in it)."""
    if len(line) < MIN_TEXT or len(snippet) < MIN_TEXT:
        return line, False
    need = TEXT_MATCH if len(snippet) >= 25 else 96  # a short passage is generic, so it must match almost exactly
    if len(line) <= len(snippet):  # the line is a piece of the passage (the passage may wrap differently)
        return ("", True) if fuzz.partial_ratio(line, snippet) >= need else (line, False)
    al = fuzz.partial_ratio_alignment(snippet, line)  # the passage sits inside a longer line
    if al.score >= need:
        return (line[:al.dest_start] + " " + line[al.dest_end:]).strip(), True
    return line, False


def snippet_of(text: str) -> str:
    return " ".join(normalize_text(text).split())


def _words_in(it: Item, box: list[float]) -> list[dict]:
    w, h = max(it.width, 1), max(it.height, 1)
    x0, y0, x1, y1 = box
    return [x for x in (it.ocr_words_json or [])
            if x0 <= (x["bbox"][0] + x["bbox"][2]) / 2 / w <= x1 and y0 <= (x["bbox"][1] + x["bbox"][3]) / 2 / h <= y1]


def _store(db, name: str, reason: str, rule: dict, kind: str) -> bool:
    """Save a rule unless the same one exists already (same passage, or same box of the same item)."""
    for w in db.scalars(select(Whitelist).where(Whitelist.kind.in_(RULE_KINDS), Whitelist.scope == name)):
        try:
            old = json.loads(w.fingerprint)
        except ValueError:
            continue
        if (rule["text"] and old.get("text") == rule["text"]) or (
                rule["box"] and old.get("box") == rule["box"] and old.get("src_item") == rule["src_item"]):
            return False
    db.add(Whitelist(kind=kind, fingerprint=json.dumps(rule), scope=name, reason=reason))
    return True


def add_region(item_id: int, box: list[float], note: str = "") -> str | None:
    """Rule for a boxed part of an item's image. Returns the assignment name, or None if the box is unusable."""
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
        lines = group_lines(_words_in(it, [x0, y0, x1, y1]))
        text = snippet_of("\n".join(" ".join(w["text"] for w in ln) for ln in lines))
        rule = {"file": file, "box": [x0, y0, x1, y1], "src_item": item_id, "contrast": float(patch.std()),
                "text": text if len(text) >= MIN_TEXT else "", "found": 0}
        reason = f'ignored image region #{rid} from {it.submission.filename}, {note or f"page {it.page}"}'
        if not _store(db, name, reason, rule, "region"):
            (_dir() / file).unlink(missing_ok=True)
    return name


def add_snippet(item_id: int, lines: list[str]) -> tuple[str | None, str]:
    """Rule for selected lines of text. -> (assignment name or None, error message)."""
    text = snippet_of("\n".join(lines))
    if len(text) < MIN_TEXT or len(text.split()) < 2:
        return None, "That is too short to recognise. Select at least a few words."
    from checker.core.db import session_scope
    with session_scope() as db:
        it = db.get(Item, item_id)
        if not it:
            return None, "That item no longer exists."
        name = it.submission.assignment.name
        shown = text[:70] + ("…" if len(text) > 70 else "")
        rule = {"text": text, "src_item": item_id, "box": None, "file": None, "contrast": 0.0, "found": 0}
        _store(db, name, f'ignored text "{shown}" #{uuid.uuid4().hex[:6]}', rule, "snippet")
    return name, ""


def delete_files(rules: list[Whitelist]) -> None:
    for w in rules:
        try:
            f = json.loads(w.fingerprint).get("file")
            if f:
                (_dir() / f).unlink(missing_ok=True)
        except (ValueError, OSError):
            pass


def _rules(db, assignment_name: str) -> list[dict]:
    out = []
    for w in db.scalars(select(Whitelist).where(Whitelist.kind.in_(RULE_KINDS), Whitelist.scope == assignment_name)):
        try:
            r = json.loads(w.fingerprint)
            patch = np.asarray(Image.open(_dir() / r["file"]).convert("L")) if r.get("file") else None
        except (ValueError, OSError):
            log.warning("ignored content %s is unreadable; skipping", w.reason)
            continue
        out.append({"wl": w, "meta": r, "text": r.get("text") or "", "patch": patch, "box": r.get("box"),
                    "src_item": r.get("src_item"), "contrast": r.get("contrast", 0.0), "file": r.get("file")})
    return out


def paint(im: Image.Image, boxes: list[list[float]]) -> Image.Image:
    """Blank the boxed areas with flat grey (same grey everywhere, so matching images stay matching)."""
    if not boxes:
        return im
    im = im.convert("RGB")
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


def _merge_boxes(boxes: list[list[float]]) -> list[list[float]]:
    """Join boxes that touch or overlap (lines of one passage) so they blank as one block."""
    boxes = sorted(([round(v, 4) for v in b] for b in boxes), key=lambda b: (b[1], b[0]))
    out: list[list[float]] = []
    for b in boxes:
        for o in out:
            if b[0] <= o[2] + 0.02 and b[2] >= o[0] - 0.02 and b[1] <= o[3] + 0.015 and b[3] >= o[1] - 0.015:
                o[0], o[1], o[2], o[3] = min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])
                break
        else:
            out.append(b)
    return out


def _rehash(it: Item, boxes: list[list[float]]) -> None:
    s = get_settings()
    im = Image.open(s.data_dir / it.thumb_path).convert("RGB")
    if boxes and _covered(boxes) >= FULLY_IGNORED:
        it.phash = it.dhash = it.whash = None  # nothing left to compare
        it.hash_variants_json = None
    else:
        h = fp.image_hashes(paint(im, boxes), s.phash_size)
        it.phash, it.dhash, it.whash, it.hash_variants_json = h["phash"], h["dhash"], h["whash"], h["variants"]


def _retext(db, it: Item, norm: str) -> None:
    s = get_settings()
    it.norm_text = norm
    db.execute(delete(Shingle).where(Shingle.item_id == it.id))
    prints = {"word": fp.word_shingles(norm, s.shingle_k), "line": fp.line_hashes(norm, s.min_line_chars),
              "code": fp.code_fingerprints(norm, s.code_k, s.code_w)}
    rows = [{"hash": h, "submission_id": it.submission_id, "item_id": it.id, "kind": k}
            for k, hs in prints.items() for h in hs]
    if rows:
        db.execute(Shingle.__table__.insert(), rows)


def _lines_of(it: Item) -> list[dict]:
    """The item's text as normalized lines, each with the OCR words (and so the position) it came from."""
    words = it.ocr_words_json or []
    if words and it.kind in IMAGE_KINDS:
        out = []
        for ln in group_lines(words):
            t = normalize_text(" ".join(w["text"] for w in ln))
            if t:
                out.append({"text": t, "rest": t, "words": ln, "hit": False})
        return out
    return [{"text": t, "rest": t, "words": None, "hit": False} for t in normalize_text(it.ocr_text).splitlines()]


def _line_box(it: Item, ln: dict) -> list[float]:
    w, h = max(it.width, 1), max(it.height, 1)
    xs = [x["bbox"][0] for x in ln["words"]] + [x["bbox"][2] for x in ln["words"]]
    ys = [x["bbox"][1] for x in ln["words"]] + [x["bbox"][3] for x in ln["words"]]
    cy, half = (min(ys) + max(ys)) / 2, (max(ys) - min(ys)) / 2 * 0.75  # detection boxes are padded; stay on the text
    return [max(min(xs) / w - MASK_PAD, 0), max((cy - half) / h - MASK_PAD, 0),
            min(max(xs) / w + MASK_PAD, 1), min((cy + half) / h + MASK_PAD, 1)]


def apply(db, assignment_id: int, sub_ids=None, progress=None) -> int:
    """Find every ignored passage and image part in the assignment's items and refresh what they feed
    (image fingerprints, text and its shingles). Returns the number of items changed."""
    name = db.get(Assignment, assignment_id).name
    rules = _rules(db, name)
    q = select(Item).where(Item.is_content, Item.submission_id.in_(
        select(Submission.id).where(Submission.assignment_id == assignment_id)))
    q = q.where(((Item.kind.in_(IMAGE_KINDS)) & Item.thumb_path.is_not(None)) | (Item.kind == "text_block"))
    if sub_ids is not None:
        q = q.where(Item.submission_id.in_(list(sub_ids)))
    marked = db.scalar(select(func.count()).select_from(Item).where(
        Item.masks_json.is_not(None) | Item.text_masks_json.is_not(None)))
    if not rules and not marked:
        return 0  # nothing to apply and nothing to undo
    seen_text: set[str] = set()
    for r in rules:  # two rules for the same passage are applied once
        if r["text"] in seen_text:
            r["text"] = ""
        seen_text.add(r["text"])
    items = db.scalars(q).all()
    data = get_settings().data_dir
    found = Counter()
    cache: dict[tuple[str, str], list[float] | None] = {}  # pixel-identical images need searching once
    changed = 0
    for i, it in enumerate(items):
        if progress:
            progress(i, len(items))
        pix_boxes: list[list[float]] = []  # areas known by position or by pixels: their text goes too
        text_boxes: list[list[float]] = []
        lines = _lines_of(it) if any(r["text"] for r in rules) else None
        target = None
        for r in rules:
            hit = False
            if r["box"] and r["src_item"] == it.id and it.thumb_path:
                pix_boxes.append(r["box"])
                hit = True
            if r["text"]:
                for ln in lines or []:
                    rest, ok = strip_snippet(ln["rest"], r["text"])
                    if ok:
                        ln["rest"], ln["hit"], hit = rest, True, True
            if r["patch"] is not None and not hit and r["contrast"] >= MIN_CONTRAST and it.thumb_path:
                key = (it.sha256 or f"item{it.id}", r["file"])
                if key not in cache:
                    target = _gray_small(data / it.thumb_path) if target is None else target
                    cache[key] = locate(target, r["patch"]) or locate_features(target, r["patch"])
                if cache[key]:
                    pix_boxes.append(cache[key])
                    hit = True
            if hit:
                found[r["wl"].id] += 1
        if lines is None and pix_boxes:
            lines = _lines_of(it)
        for ln in lines or []:
            if ln["words"] is None:
                continue
            lb = _line_box(it, ln)
            cx, cy = (lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2
            if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in pix_boxes):
                ln["rest"], ln["hit"] = "", True
            if ln["hit"] and len(ln["rest"]) < 0.5 * len(ln["text"]):
                text_boxes.append(lb)
        gone = [ln for ln in lines or [] if ln["hit"]]
        boxes = _merge_boxes(pix_boxes + text_boxes) if it.thumb_path else []
        if it.thumb_path and boxes != (it.masks_json or []):
            _rehash(it, boxes)
            changed += 1
        norm = "\n".join(ln["rest"] for ln in lines if ln["rest"].strip()) if gone else normalize_text(it.ocr_text)
        removed = [ln["text"] for ln in gone]
        if norm != (it.norm_text or "") or removed != (it.text_masks_json or []):
            _retext(db, it, norm)
            changed += 1
        it.masks_json = boxes or None
        it.text_masks_json = removed or None
    if sub_ids is None:  # how many items each rule was found in, shown under Settings, "Ignored content"
        for r in rules:
            r["wl"].fingerprint = json.dumps({**r["meta"], "found": found[r["wl"].id]})
    db.flush()
    return changed
