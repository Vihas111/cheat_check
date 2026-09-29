"""Pluggable OCR: OcrEngine.extract(image) -> {text, words:[{text, bbox, conf}]}."""

import shutil
import threading
from functools import lru_cache
from typing import Protocol

import numpy as np
from PIL import Image, ImageOps

from checker.config import get_settings


class OcrEngine(Protocol):
    name: str

    def extract(self, image: Image.Image) -> dict: ...


def preprocess(im: Image.Image) -> tuple[Image.Image, float]:
    """Upscale small screenshots, grayscale, invert dark themes. Returns (image, scale)."""
    s = get_settings()
    g = im.convert("L")
    scale = 1.0
    if max(g.size) < s.ocr_upscale_below:
        scale = 2.0
        g = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
    if np.asarray(g).mean() < s.ocr_dark_mean:
        g = ImageOps.invert(g)
    return g, scale


def lines_to_text(words: list[dict]) -> str:
    """Group boxes into reading-order lines by vertical overlap."""
    words = sorted(words, key=lambda w: (w["bbox"][1] + w["bbox"][3]) / 2)
    lines: list[list[dict]] = []
    for w in words:
        cy = (w["bbox"][1] + w["bbox"][3]) / 2
        h = max(1, w["bbox"][3] - w["bbox"][1])
        if lines:
            last = lines[-1][-1]
            lcy = (last["bbox"][1] + last["bbox"][3]) / 2
            if abs(cy - lcy) < 0.5 * h:
                lines[-1].append(w)
                continue
        lines.append([w])
    return "\n".join(" ".join(w["text"] for w in sorted(ln, key=lambda w: w["bbox"][0])) for ln in lines)


def _result(words: list[dict]) -> dict:
    conf = float(np.mean([w["conf"] for w in words])) if words else 0.0
    return {"text": lines_to_text(words), "words": words, "conf": conf}


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self._ocr = RapidOCR()
        self._lock = threading.Lock()  # ponytail: one OCR at a time per process; onnxruntime is multi-threaded inside

    def extract(self, image: Image.Image) -> dict:
        g, scale = preprocess(image)
        arr = np.asarray(g.convert("RGB"))
        with self._lock:
            res, _ = self._ocr(arr)
        words = []
        for box, text, conf in res or []:
            xs, ys = [p[0] / scale for p in box], [p[1] / scale for p in box]
            words.append({"text": text, "bbox": [min(xs), min(ys), max(xs), max(ys)], "conf": float(conf)})
        return _result(words)


class TesseractEngine:
    name = "tesseract"

    def extract(self, image: Image.Image) -> dict:
        import pytesseract
        g, scale = preprocess(image)
        d = pytesseract.image_to_data(g, output_type=pytesseract.Output.DICT, config="--psm 6")
        words = []
        for i, t in enumerate(d["text"]):
            if t.strip() and float(d["conf"][i]) >= 0:
                x, y, w, h = (d[k][i] / scale for k in ("left", "top", "width", "height"))
                words.append({"text": t, "bbox": [x, y, x + w, y + h], "conf": float(d["conf"][i]) / 100})
        return _result(words)


class NullEngine:
    """Used in tests / --no-ocr runs."""
    name = "none"

    def extract(self, image: Image.Image) -> dict:
        return {"text": "", "words": [], "conf": 0.0}


ENGINES = {"rapidocr": RapidOcrEngine, "tesseract": TesseractEngine, "none": NullEngine}


def available_engines() -> list[str]:
    out = []
    try:
        import rapidocr_onnxruntime  # noqa: F401
        out.append("rapidocr")
    except ImportError:
        pass
    if shutil.which("tesseract"):
        out.append("tesseract")
    return out


@lru_cache
def get_engine(name: str | None = None) -> OcrEngine:
    name = name or get_settings().ocr_engine
    if name == "auto":
        avail = available_engines()
        if not avail:
            raise RuntimeError("No OCR engine available: install rapidocr-onnxruntime or tesseract")
        name = avail[0]
    return ENGINES[name]()
