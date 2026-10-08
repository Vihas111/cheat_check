"""Second-stage verification of shortlisted pairs (plan.md §7.3)."""

import difflib

import cv2
import numpy as np
from PIL import Image


def _gray(path) -> np.ndarray:
    im = Image.open(path).convert("L")
    im.thumbnail((1200, 1200))
    return np.asarray(im)


def _keep_mask(img: np.ndarray, boxes) -> np.ndarray | None:
    """Feature detection mask: 0 inside ignored regions (a little widened), 255 elsewhere."""
    if not boxes:
        return None
    h, w = img.shape
    m = np.full((h, w), 255, np.uint8)
    pad = 12
    for x0, y0, x1, y1 in boxes:
        m[max(int(y0 * h) - pad, 0):int(y1 * h) + pad, max(int(x0 * w) - pad, 0):int(x1 * w) + pad] = 0
    return m


def _orb(a: np.ndarray, b: np.ndarray, ratio=0.75, masks_a=None, masks_b=None):
    orb = cv2.ORB_create(nfeatures=1500)
    ka, da = orb.detectAndCompute(a, _keep_mask(a, masks_a))
    kb, db = orb.detectAndCompute(b, _keep_mask(b, masks_b))
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return ka, kb, [], None
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < ratio * p[1].distance]
    if len(good) < 8:
        return ka, kb, [], None
    src = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if H is None:
        return ka, kb, [], None
    return ka, kb, [m for m, ok in zip(good, mask.ravel(), strict=True) if ok], H


def orb_verify(path_a, path_b, masks_a=None, masks_b=None) -> dict:
    """ORB + ratio test + RANSAC homography. -> {inliers, scale, shift} (transform is a -> b).
    masks_* are ignored regions ([x0, y0, x1, y1] fractions) that features must not come from."""
    _, _, inliers, H = _orb(_gray(path_a), _gray(path_b), masks_a=masks_a, masks_b=masks_b)
    if H is None:
        return {"inliers": 0}
    scale = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
    return {"inliers": len(inliers), "scale": round(scale, 3), "shift": [round(float(H[0, 2])), round(float(H[1, 2]))]}


def orb_overlay_png(path_a, path_b, masks_a=None, masks_b=None) -> bytes:
    """Side-by-side image with inlier matches drawn, for the comparison viewer."""
    a, b = _gray(path_a), _gray(path_b)
    ka, kb, inliers, _ = _orb(a, b, masks_a=masks_a, masks_b=masks_b)
    out = cv2.drawMatches(a, ka, b, kb, inliers[:200], None, matchColor=(0, 200, 0),
                          flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
    return cv2.imencode(".png", out)[1].tobytes()


def text_passages(a: str, b: str, min_words: int = 4) -> list[dict]:
    """Matching word runs between two normalized texts -> [{a_start, a_end, b_start, b_end, text}] (word indices)."""
    wa, wb = (a or "").split(), (b or "").split()
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    return [{"a": [m.a, m.a + m.size], "b": [m.b, m.b + m.size], "text": " ".join(wa[m.a:m.a + m.size])}
            for m in sm.get_matching_blocks() if m.size >= min_words]


def highlight(text: str, spans: list[list[int]]) -> list[tuple[str, bool]]:
    """Split text into (chunk, is_match) runs by word spans, for templates."""
    words = (text or "").split()
    marked = [False] * len(words)
    for s, e in spans:
        for i in range(s, min(e, len(words))):
            marked[i] = True
    out: list[tuple[str, bool]] = []
    for w, m in zip(words, marked, strict=True):
        if out and out[-1][1] == m:
            out[-1] = (out[-1][0] + " " + w, m)
        else:
            out.append((w, m))
    return out


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    from PIL import ImageDraw
    im = Image.new("RGB", (600, 400), "white")
    d = ImageDraw.Draw(im)
    for i in range(12):
        d.text((20, 20 + i * 30), f"line {i} value = compute(x{i}, y{i})", fill="black")
    tmp = Path(tempfile.mkdtemp())
    im.save(tmp / "a.png")
    im.crop((10, 10, 500, 380)).resize((735, 555)).save(tmp / "b.png")
    r = orb_verify(tmp / "a.png", tmp / "b.png")
    assert r["inliers"] > 20 and 1.3 < r["scale"] < 1.7, r
    p = text_passages("the quick brown fox jumps over it", "a quick brown fox jumps over there")
    assert p[0]["text"] == "quick brown fox jumps over"
    assert highlight("a b c", [[1, 2]]) == [("a", False), ("b", True), ("c", False)]
    print("ok")
