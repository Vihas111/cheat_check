"""Evasion and metadata signals (plan.md §8 METADATA, §9). Every flag carries its evidence."""

import re
from datetime import datetime

from checker.config import get_settings
from checker.core.normalize import has_zero_width, mixed_script_words


def pdf_date(v: str | None) -> datetime | None:
    """'D:20240305142200+01'00'' -> naive datetime (timezone dropped; good enough for closeness checks)."""
    m = re.match(r"D?:?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", v or "")
    if not m:
        return None
    parts = [int(p) if p else d for p, d in zip(m.groups(), (0, 1, 1, 0, 0, 0), strict=True)]
    try:
        return datetime(*parts)
    except ValueError:
        return None


def evasion_flags(sub, text_items, matches) -> list[dict]:
    out = []
    hidden = [dict(sp, page=p["page"]) for p in (sub.pdf_meta_json or {}).get("pages", [])
              for sp in p.get("hidden_spans", [])]
    if hidden:
        out.append({"type": "EVASION_HIDDEN_TEXT", "severity": "medium",
                    "summary": f"{len(hidden)} text span(s) in the PDF are invisible (white, tiny, or off-page).",
                    "evidence": {"spans": hidden[:50]}})
    raw = [(it.page, it.ocr_text or "") for it in text_items] + [(h["page"], h["text"]) for h in hidden]
    zw = [p for p, t in raw if has_zero_width(t)]
    if zw:
        out.append({"type": "EVASION_ZERO_WIDTH", "severity": "medium",
                    "summary": "Zero-width characters are hidden inside the typed text.",
                    "evidence": {"pages": sorted(set(zw))}})
    mixed = [(p, w) for p, t in raw for w in mixed_script_words(t)]
    if mixed:
        out.append({"type": "EVASION_HOMOGLYPH", "severity": "medium",
                    "summary": "Words mix Latin with look-alike Cyrillic/Greek letters.",
                    "evidence": {"words": [{"page": p, "word": w} for p, w in mixed[:50]]}})
    transformed = [m for m in matches
                   if m.kind == "image_hash" and (m.detail_json or {}).get("variant", "orig") != "orig"]
    if transformed:
        out.append({"type": "EVASION_TRANSFORM", "severity": "medium",
                    "summary": "Images match another submission only after flipping, rotating or inverting them.",
                    "evidence": {"matches": [{"match_id": m.id, "variant": m.detail_json["variant"],
                                              "other_submission_id": m.other_submission_id}
                                             for m in transformed[:50]]}})
    return out


def metadata_flags(sub, all_subs, deadline: datetime | None) -> list[dict]:
    """Weak signals only (severity low): never raise the tier to HIGH on their own."""
    s = get_settings()
    info = (sub.pdf_meta_json or {}).get("info", {})
    evidence = []

    def common(v):
        return any(c in v.lower() for c in s.common_producers)

    for key in ("author", "creator"):
        v = (info.get(key) or "").strip()
        if not v or common(v):
            continue
        same = [o for o in all_subs if o.id != sub.id and o.student_pk != sub.student_pk
                and ((o.pdf_meta_json or {}).get("info", {}).get(key) or "").strip() == v]
        if 0 < len(same) <= s.rare_max_submissions:
            evidence.append({"reason": f"same rare {key} string", "value": v,
                             "shared_with": [o.id for o in same]})
    created = pdf_date(info.get("creationDate"))
    if created:
        close = []
        for o in all_subs:
            oc = pdf_date((o.pdf_meta_json or {}).get("info", {}).get("creationDate"))
            if o.id != sub.id and o.student_pk != sub.student_pk and oc \
                    and abs((oc - created).total_seconds()) <= s.metadata_close_seconds:
                close.append(o.id)
        if 0 < len(close) <= s.rare_max_submissions:
            evidence.append({"reason": "creation time within "
                             f"{s.metadata_close_seconds}s of another student's PDF",
                             "value": info.get("creationDate"), "shared_with": close})
    modified = pdf_date(info.get("modDate"))
    if modified and deadline and modified > deadline.replace(tzinfo=None):
        evidence.append({"reason": "modified after the deadline", "value": info.get("modDate")})
    updates = (sub.pdf_meta_json or {}).get("incremental_updates", 0)
    if updates >= 3:
        evidence.append({"reason": "many incremental edits saved into the PDF", "value": updates})
    if not evidence:
        return []
    return [{"type": "METADATA", "severity": "low",
             "summary": "; ".join(e["reason"] for e in evidence) + " (weak signal).",
             "evidence": {"items": evidence}}]


if __name__ == "__main__":
    assert pdf_date("D:20240305142200+01'00'") == datetime(2024, 3, 5, 14, 22)
    assert pdf_date("") is None
    print("ok")
