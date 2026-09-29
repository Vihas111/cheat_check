"""Candidate search + per-item attribution (plan.md §7).

`overlaps()` finds, for every content item of a submission, every other submission that contains
the same image or text (uncapped; also used for rarity weights). `match_submission()` caps it to the
top candidates, verifies, and stores symmetric Match rows."""

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import delete, func, or_, select

from checker.config import get_settings
from checker.core import fingerprint as fp
from checker.core.db import Assignment, Item, Match, Shingle, Submission, Whitelist
from checker.core.verify import orb_verify

log = logging.getLogger(__name__)

IMAGE_KINDS = ("image", "page_render")
VARIANT_NAMES = ["orig", *fp.VARIANTS]


@dataclass
class Index:
    """Assignment-wide lookup tables, built once per batch."""
    assignment_id: int
    subs: dict  # sub_id -> {student_pk, is_reference, filename}
    item_ids: np.ndarray
    item_sub: np.ndarray
    hashes: np.ndarray  # (n, w) uint64 pHash of stored content images
    item_sha: dict  # item_id -> pixel sha256
    wl_images: np.ndarray  # (m, w) uint64 whitelisted pHashes
    wl_shingles: set
    sha_subs: dict  # pixel sha256 -> {sub_id} (pixel-identical images)


def build_index(db, assignment_id: int) -> Index:
    s = get_settings()
    subs = {r.id: {"student_pk": r.student_pk, "is_reference": r.is_reference, "filename": r.filename}
            for r in db.execute(select(Submission.id, Submission.student_pk, Submission.is_reference,
                                       Submission.filename)
                                .where(Submission.assignment_id == assignment_id, Submission.status == "done"))}
    rows = db.execute(select(Item.id, Item.submission_id, Item.phash, Item.sha256)
                      .where(Item.submission_id.in_(subs), Item.is_content, Item.kind.in_(IMAGE_KINDS),
                             Item.phash.is_not(None))).all() if subs else []
    words = (s.phash_size ** 2 + 63) // 64
    sha_subs = defaultdict(set)
    for r in rows:
        sha_subs[r.sha256].add(r.submission_id)
    hashes = np.stack([fp.to_u64(r.phash) for r in rows]) if rows else np.zeros((0, words), np.uint64)
    aname = db.get(Assignment, assignment_id).name
    wl = db.scalars(select(Whitelist).where(or_(Whitelist.scope.is_(None), Whitelist.scope == aname))).all()
    wl_img = [fp.to_u64(bytes.fromhex(w.fingerprint)) for w in wl if w.kind == "image"]
    return Index(assignment_id, subs, np.array([r.id for r in rows], dtype=np.int64),
                 np.array([r.submission_id for r in rows], dtype=np.int64), hashes,
                 {r.id: r.sha256 for r in rows},
                 np.stack(wl_img) if wl_img else np.zeros((0, words), np.uint64),
                 {int(w.fingerprint) for w in wl if w.kind == "shingle"}, sha_subs)


def _whitelisted_image(item: Item, idx: Index) -> bool:
    if item.phash is None or not len(idx.wl_images):
        return False
    return bool(fp.hamming_many(fp.to_u64(item.phash), idx.wl_images).min() <= get_settings().phash_near)


def image_overlaps(item: Item, idx: Index, sub_id: int) -> list[dict]:
    """Every stored content image (other submissions) within the near-duplicate distance, any variant."""
    s = get_settings()
    if item.phash is None or not len(idx.hashes):
        return []
    queries = [item.phash] + [bytes.fromhex(item.hash_variants_json[k]) for k in fp.VARIANTS]
    dists = np.stack([fp.hamming_many(fp.to_u64(q), idx.hashes) for q in queries])  # (variants, n)
    best_v = dists.argmin(axis=0)
    best_d = dists.min(axis=0)
    exact = np.array([idx.item_sha.get(int(i)) == item.sha256 for i in idx.item_ids]) if item.sha256 else False
    best_d = np.where(exact, 0, best_d)
    best_v = np.where(exact, 0, best_v)
    hit = (best_d <= s.phash_near) & (idx.item_sub != sub_id)
    return [{"other_sub": int(idx.item_sub[j]), "other_item": int(idx.item_ids[j]), "distance": int(best_d[j]),
             "variant": VARIANT_NAMES[best_v[j]], "fraction": 1.0} for j in np.flatnonzero(hit)]


def text_overlaps(db, sub_id: int, idx: Index) -> tuple[dict, dict]:
    """-> ({item_id: [overlap]}, {item_id: shingle count}) via the shingle inverted index."""
    s = get_settings()
    own = db.execute(select(Shingle.hash, Shingle.item_id, Shingle.kind).where(Shingle.submission_id == sub_id)).all()
    by_hash: dict[int, list[tuple[int, str]]] = defaultdict(list)
    counts: dict[tuple[int, str], int] = defaultdict(int)
    for h, item_id, kind in own:
        if h in idx.wl_shingles:
            continue
        group = "code" if kind == "code" else "text"
        by_hash[h].append((item_id, group))
        counts[(item_id, group)] += 1
    shared: dict[tuple[int, str, int, int], int] = defaultdict(int)  # (item, group, other_sub, other_item)
    hashes = list(by_hash)
    for i in range(0, len(hashes), 900):
        rows = db.execute(select(Shingle.hash, Shingle.submission_id, Shingle.item_id, Shingle.kind)
                          .where(Shingle.hash.in_(hashes[i:i + 900]), Shingle.submission_id != sub_id,
                                 Shingle.submission_id.in_(idx.subs))).all()
        seen = set()
        for h, osub, oitem, okind in rows:
            ogroup = "code" if okind == "code" else "text"
            for item_id, group in by_hash[h]:
                key = (item_id, group, osub, oitem)
                if group == ogroup and (key, h) not in seen:  # a hash may be stored as word and line
                    seen.add((key, h))
                    shared[key] += 1
    other_items = {k[3] for k in shared}
    ocounts: dict[tuple[int, str], int] = defaultdict(int)
    if other_items:
        ids = list(other_items)
        for i in range(0, len(ids), 900):
            for oitem, okind, n in db.execute(select(Shingle.item_id, Shingle.kind, func.count())
                                              .where(Shingle.item_id.in_(ids[i:i + 900]))
                                              .group_by(Shingle.item_id, Shingle.kind)):
                ocounts[(oitem, "code" if okind == "code" else "text")] += n
    out: dict[int, list[dict]] = defaultdict(list)
    for (item_id, group, osub, oitem), n in shared.items():
        if n < s.min_shared_shingles:
            continue
        mine, theirs = counts[(item_id, group)], max(ocounts[(oitem, group)], n)
        containment = n / mine
        if containment < (s.code_containment_min if group == "code" else s.text_containment_min):
            continue
        out[item_id].append({"other_sub": osub, "other_item": oitem, "group": group, "shared": n,
                             "fraction": min(1.0, containment), "containment": round(containment, 3),
                             "containment_other": round(n / theirs, 3),
                             "jaccard": round(n / (mine + theirs - n), 3)})
    item_counts = defaultdict(int)
    for (item_id, _), n in counts.items():
        item_counts[item_id] += n
    return out, item_counts


def overlaps(db, sub: Submission, idx: Index) -> dict:
    """-> {item_id: {"item": Item, "whitelisted": bool, "hits": [overlap...]}} for all content items.
    Same-student submissions are excluded."""
    s = get_settings()
    items = db.scalars(select(Item).where(Item.submission_id == sub.id, Item.is_content)).all()
    text, _ = text_overlaps(db, sub.id, idx)
    img_hits = {it.id: image_overlaps(it, idx, sub.id) for it in items if not _whitelisted_image(it, idx)}
    # Screenshots with the same window layout but different text hash close together. When both images
    # carry real text, a near (not pixel-identical, not transformed) hash hit needs the text to agree too.
    wordy = {i for i, n in db.execute(select(Item.id, Item.norm_text).where(
        Item.id.in_({h["other_item"] for hs in img_hits.values() for h in hs} | {it.id for it in items})))
        if len(fp.TOKEN.findall(n or "")) >= s.min_text_tokens}
    out = {}
    for it in items:
        wl = it.id not in img_hits
        text_pairs = {h["other_item"] for h in text.get(it.id, [])}
        hits = [dict(h, kind="image_hash") for h in img_hits.get(it.id, [])
                if h["distance"] <= s.phash_exact or h["variant"] != "orig" or h["other_item"] in text_pairs
                or not (it.id in wordy and h["other_item"] in wordy)]
        hits += [dict(h, kind="code_structure" if h["group"] == "code" else "ocr_text") for h in text.get(it.id, [])]
        hits = [h for h in hits if not (sub.student_pk and idx.subs[h["other_sub"]]["student_pk"] == sub.student_pk)]
        out[it.id] = {"item": it, "whitelisted": wl, "hits": hits}
    return out


def _abs(p: str) -> Path:
    return get_settings().data_dir / p


def match_submission(db, sub: Submission, idx: Index, max_other_id: int | None = None) -> set[int]:
    """Recompute and store this submission's matches (both directions). Returns the other submission ids."""
    s = get_settings()
    db.execute(delete(Match).where(or_(Match.submission_id == sub.id, Match.other_submission_id == sub.id)))
    ov = overlaps(db, sub, idx)
    # top-N other submissions by amount of shared content
    per_sub = defaultdict(float)
    for rec in ov.values():
        for h in rec["hits"]:
            if max_other_id is None or h["other_sub"] < max_other_id:
                per_sub[h["other_sub"]] += h["fraction"]
    keep = set(sorted(per_sub, key=per_sub.get, reverse=True)[:s.top_n])
    item_cache: dict[int, Item] = {}

    def other(item_id):
        if item_id not in item_cache:
            item_cache[item_id] = db.get(Item, item_id)
        return item_cache[item_id]

    rows = []
    for rec in ov.values():
        it = rec["item"]
        hits = [h for h in rec["hits"] if h["other_sub"] in keep]
        img_pairs = {h["other_item"] for h in hits if h["kind"] == "image_hash"}
        for h in hits:
            detail = {k: v for k, v in h.items() if k not in ("other_sub", "other_item", "kind", "group")}
            kind, score = h["kind"], h["fraction"]
            o = other(h["other_item"])
            if kind == "image_hash":
                score = 1 - h["distance"] / s.phash_size ** 2
                if h["distance"] > s.phash_exact and h["variant"] == "orig" and it.thumb_path and o.thumb_path:
                    detail.update(orb_verify(_abs(it.thumb_path), _abs(o.thumb_path)))
                    if detail["inliers"] < s.orb_min_inliers and not any(
                            x["other_item"] == o.id and x["kind"] != "image_hash" for x in hits):
                        continue  # hash collision without feature or text support
            elif it.kind in IMAGE_KINDS and o.kind in IMAGE_KINDS and o.id not in img_pairs \
                    and it.thumb_path and o.thumb_path:
                # text match between two images the hashes missed (crop, pad, ...): try features
                orb = orb_verify(_abs(it.thumb_path), _abs(o.thumb_path))
                if orb["inliers"] >= s.orb_min_inliers:
                    img_pairs.add(o.id)
                    rows.append((it.id, h["other_sub"], o.id, "image_feature", 1.0, orb))
            rows.append((it.id, h["other_sub"], o.id, kind, score, detail))
    for item_id, osub, oitem, kind, score, detail in rows:
        db.add(Match(submission_id=sub.id, other_submission_id=osub, item_id=item_id, other_item_id=oitem,
                     kind=kind, score=round(score, 4), detail_json=detail))
        rev = dict(detail)
        if "containment_other" in rev:
            rev["containment"], rev["containment_other"] = rev["containment_other"], rev["containment"]
            rev["fraction"] = min(1.0, rev["containment"])
        db.add(Match(submission_id=osub, other_submission_id=sub.id, item_id=oitem, other_item_id=item_id,
                     kind=kind, score=round(rev.get("fraction", score) if kind in ("ocr_text", "code_structure")
                                        else score, 4), detail_json=rev))
    db.flush()
    return {r[1] for r in rows}
