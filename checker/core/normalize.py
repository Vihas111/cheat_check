"""Text normalization applied identically to text-layer text and OCR text."""

import re
import unicodedata

import ftfy

ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff\u00ad\u180e]")

# Common Cyrillic/Greek lookalikes -> Latin (after lowercasing).
CONFUSABLES = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
    "т": "t", "у": "y", "х": "x", "ѕ": "s", "і": "i", "ј": "j", "ӏ": "l", "ԁ": "d", "ԛ": "q",
    "ԝ": "w", "ɡ": "g", "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "γ": "y",
})

LINE_NUMBER = re.compile(r"^\s*\d{1,4}\s*[|:.)]?\s+(?=\S)")
TRAILING_NOISE = re.compile(r"[\s|.,;:~`'\"_\-]+$")
SPACES = re.compile(r"[ \t\f\v]+")


def has_zero_width(s: str) -> bool:
    return bool(ZERO_WIDTH.search(s))


def mixed_script_words(s: str) -> list[str]:
    """Words that mix Latin letters with Cyrillic/Greek letters (homoglyph trick)."""
    out = []
    for w in re.findall(r"\w+", s):
        scripts = set()
        for ch in w:
            if ch.isalpha():
                name = unicodedata.name(ch, "")
                scripts.add("LATIN" if name.startswith("LATIN") else
                            "CYRILLIC" if name.startswith("CYRILLIC") else
                            "GREEK" if name.startswith("GREEK") else "OTHER")
        if "LATIN" in scripts and scripts & {"CYRILLIC", "GREEK"}:
            out.append(w)
    return out


def normalize_line(line: str) -> str:
    line = LINE_NUMBER.sub("", line)
    line = SPACES.sub(" ", line).strip()
    return TRAILING_NOISE.sub("", line)


def normalize_text(s: str | None) -> str:
    if not s:
        return ""
    s = ftfy.fix_text(s)
    s = unicodedata.normalize("NFKC", s)
    s = ZERO_WIDTH.sub("", s)
    s = s.lower().translate(CONFUSABLES)
    lines = (normalize_line(ln) for ln in s.splitlines())
    return "\n".join(ln for ln in lines if ln)


if __name__ == "__main__":
    assert normalize_text("  12 | Hеllo\u200bWorld ... ") == "helloworld"
    assert normalize_text("ﬁle") == "file"
    assert mixed_script_words("pаssword ok") == ["pаssword"]
    print("ok")
