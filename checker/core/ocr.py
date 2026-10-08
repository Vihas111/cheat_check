"""Pluggable OCR: OcrEngine.extract(image) -> {text, words:[{text, bbox, conf}]}."""

import logging
import shutil
import threading
from functools import lru_cache
from typing import Protocol

import numpy as np
from PIL import Image, ImageOps

from checker.config import get_settings

log = logging.getLogger(__name__)


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


def group_lines(words: list[dict]) -> list[list[dict]]:
    """Group boxes into reading-order lines by vertical overlap; each line is sorted left to right."""
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
    return [sorted(ln, key=lambda w: w["bbox"][0]) for ln in lines]


def lines_to_text(words: list[dict]) -> str:
    return "\n".join(" ".join(w["text"] for w in ln) for ln in group_lines(words))


def _result(words: list[dict]) -> dict:
    conf = float(np.mean([w["conf"] for w in words])) if words else 0.0
    return {"text": lines_to_text(words), "words": words, "conf": conf}


def pick_device(requested: str | None = None) -> str:
    """cpu | cuda | directml, from the setting and what onnxruntime can actually use on this machine."""
    import onnxruntime as ort
    want = (requested or get_settings().ocr_device).lower()
    have = set(ort.get_available_providers())
    usable = {"cuda": "CUDAExecutionProvider" in have, "directml": "DmlExecutionProvider" in have}
    if want in usable:
        if usable[want]:
            return want
        log.warning("ocr_device=%s is not available here (onnxruntime providers: %s); using the CPU. "
                    "See the README section on GPUs.", want, sorted(have))
        return "cpu"
    if want == "auto":
        return next((d for d in ("cuda", "directml") if usable[d]), "cpu")
    return "cpu"


GPU_PROVIDERS = {"cuda": "CUDAExecutionProvider", "directml": "DmlExecutionProvider"}


def _use_gpu_id(gpu_id: int) -> None:
    """RapidOCR always asks for GPU 0; pass the configured GPU id through instead."""
    from rapidocr_onnxruntime.utils.infer_engine import OrtInferSession
    if getattr(OrtInferSession, "_gpu_id_patched", None) == gpu_id:
        return
    original = getattr(OrtInferSession, "_orig_get_ep_list", OrtInferSession._get_ep_list)

    def patched(self):
        eps = original(self)
        return [(n, {**o, "device_id": gpu_id}) if n != "CPUExecutionProvider" and "device_id" in o else (n, o)
                for n, o in eps]

    OrtInferSession._orig_get_ep_list = original
    OrtInferSession._get_ep_list = patched
    OrtInferSession._gpu_id_patched = gpu_id


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self.device = "cpu"
        self._lock = threading.Lock()  # ponytail: one OCR at a time per process; onnxruntime is multi-threaded inside
        want = pick_device()
        if want == "cuda":
            try:
                import onnxruntime
                onnxruntime.preload_dlls()  # finds the CUDA libraries installed through pip (nvidia-* packages)
            except Exception:
                pass
        if want != "cpu":
            try:
                _use_gpu_id(get_settings().ocr_gpu_id)
                flags = {f"{m}_use_{'cuda' if want == 'cuda' else 'dml'}": True for m in ("det", "cls", "rec")}
                eng = RapidOCR(**flags)
                active = eng.text_det.infer.session.get_providers()[0]
                if active != GPU_PROVIDERS[want]:
                    raise RuntimeError(f"onnxruntime fell back to {active}")
                eng(np.full((64, 256, 3), 255, dtype=np.uint8))  # a first run shows driver or library problems now
                self._ocr, self.device = eng, want
            except Exception as e:
                log.warning("The GPU (%s) could not be used (%s). Using the CPU instead.", want, str(e)[:200])
        if self.device == "cpu":
            self._ocr = RapidOCR()
        log.info("OCR running on %s", self.device)

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
