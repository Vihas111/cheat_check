"""Image hashes (with transform variants) and text shingles."""

import hashlib
import re

import imagehash
import numpy as np
from PIL import Image, ImageOps

# Variants of the *query* image compared against stored originals. pHash is computed on
# grayscale already, so a separate grayscale variant would be identical and is omitted.
VARIANTS = {
    "flip_h": lambda im: ImageOps.mirror(im),
    "flip_v": lambda im: ImageOps.flip(im),
    "rot90": lambda im: im.rotate(90, expand=True),
    "rot180": lambda im: im.rotate(180, expand=True),
    "rot270": lambda im: im.rotate(270, expand=True),
    "invert": lambda im: ImageOps.invert(im.convert("RGB")),
}


def hash_bytes(h: imagehash.ImageHash) -> bytes:
    return np.packbits(h.hash.flatten()).tobytes()


def phash(im: Image.Image, size: int = 12) -> bytes:
    return hash_bytes(imagehash.phash(im, hash_size=size))


def image_hashes(im: Image.Image, phash_size: int = 12) -> dict:
    return {
        "phash": phash(im, phash_size),
        "dhash": hash_bytes(imagehash.dhash(im)),
        "whash": hash_bytes(imagehash.whash(im)),
        "variants": {k: phash(f(im), phash_size).hex() for k, f in VARIANTS.items()},
    }


def pixel_sha256(im: Image.Image) -> str:
    arr = np.asarray(im.convert("RGB"))
    return hashlib.sha256(arr.tobytes() + str(arr.shape).encode()).hexdigest()


def to_u64(b: bytes) -> np.ndarray:
    """Pad hash bytes to a multiple of 8 and view as uint64 words, for vectorized Hamming."""
    pad = (-len(b)) % 8
    return np.frombuffer(b + b"\0" * pad, dtype=np.uint64)


def hamming_many(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query: (w,) uint64, matrix: (n, w) uint64 -> (n,) bit distances."""
    return np.bitwise_count(matrix ^ query).sum(axis=1)


# ---------------- text ----------------

TOKEN = re.compile(r"[a-z0-9_]+")


def h64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big", signed=True)


def word_shingles(norm_text: str, k: int = 5) -> set[int]:
    toks = TOKEN.findall(norm_text)
    if len(toks) < k:
        return {h64("w:" + " ".join(toks))} if len(toks) >= 3 else set()
    return {h64("w:" + " ".join(toks[i:i + k])) for i in range(len(toks) - k + 1)}


def line_hashes(norm_text: str, min_chars: int = 12) -> set[int]:
    return {h64("l:" + ln) for ln in norm_text.splitlines() if len(ln) >= min_chars}


# ---------------- code (MOSS-style winnowing) ----------------

CODE_CHARS = re.compile(r"[(){}\[\];]|^\s*(def|class|import|return|for|while|if|public|int|void|#include)\b")


def looks_like_code(text: str, min_lines: int = 3, min_fraction: float = 0.4) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(lines) >= min_lines and sum(bool(CODE_CHARS.search(ln)) for ln in lines) / len(lines) >= min_fraction


def code_tokens(text: str) -> list[str]:
    """Identifiers -> N, strings -> S, numbers -> 0; keywords/operators kept. Whitespace dropped."""
    from pygments.lexers import PythonLexer
    from pygments.token import Comment, Keyword, Name, Number, String, Text, Whitespace

    # ponytail: one fixed lexer. guess_lexer is unreliable on short OCR snippets, and a consistent
    # tokenization matters more than the right language. Per-language lexers if C/Java matching is weak.
    out = []
    for tt, val in PythonLexer().get_tokens(text):
        if tt in Comment or tt in Whitespace or tt in Text or not val.strip():
            continue
        if tt in Keyword:
            out.append(val.strip())
        elif tt in Name:
            out.append("N")
        elif tt in String:
            if not out or out[-1] != "S":  # a string literal lexes as several tokens
                out.append("S")
        elif tt in Number:
            out.append("0")
        else:
            out.append(val.strip())
    return out


def winnow(tokens: list[str], k: int = 10, w: int = 4) -> set[int]:
    """Robust winnowing: min hash of every window of w consecutive k-gram hashes."""
    grams = [h64("c:" + " ".join(tokens[i:i + k])) for i in range(len(tokens) - k + 1)]
    if len(grams) <= w:
        return set(grams)
    return {min(grams[i:i + w]) for i in range(len(grams) - w + 1)}


def code_fingerprints(text: str, k: int = 10, w: int = 4) -> set[int]:
    return winnow(code_tokens(text), k, w) if looks_like_code(text) else set()


if __name__ == "__main__":
    a = Image.new("RGB", (200, 120), "white")
    from PIL import ImageDraw
    ImageDraw.Draw(a).rectangle((20, 20, 120, 80), fill="black")
    h1, h2 = image_hashes(a), image_hashes(a.resize((400, 240)))
    d = hamming_many(to_u64(h1["phash"]), to_u64(h2["phash"])[None, :])[0]
    assert d <= 4, d
    flipped = image_hashes(ImageOps.mirror(a))["phash"]
    assert bytes.fromhex(h1["variants"]["flip_h"]) == flipped
    assert word_shingles("a b c d e f") and len(word_shingles("a b c d e f")) == 2
    a_src = "def total(items):\n    s = 0\n    for it in items:\n        s += it.price\n    return s\n" \
            "print(total(cart))"
    b_src = "def sum_up(xs):\n  acc=0\n  for x in xs:\n    acc+=x.price\n  return acc\nprint(sum_up(basket))"
    fa, fb = code_fingerprints(a_src), code_fingerprints(b_src)
    assert fa and fa == fb, (fa, fb)
    print("ok")
