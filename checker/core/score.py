"""Rarity weights, coverage, flags and risk tier (plan.md §8). Explainable: every number has evidence."""

import math
import re
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import delete, select

from checker.config import PIPELINE_VERSION, get_settings
from checker.core.db import Assignment, Entity, Flag, Item, Match, Student, Submission
from checker.core.forensics import evasion_flags, metadata_flags
from checker.core.match import IMAGE_KINDS, Index, build_index, overlaps

# One sentence per flag, shown in the UI next to the evidence.
FLAG_HELP = {
    "HIGH_SINGLE_SOURCE": "Half or more of this submission's distinctive content also appears in one other submission.",
    "HIGH_COLLAGE": "Most of this submission's distinctive content appears across three or more other submissions.",
    "FOREIGN_IDENTITY": "A screenshot shows another student's name, username, email or ID.",
    "SHARED_IDENTITY": "A username or hostname in these screenshots also appears in another student's screenshots.",
    "SHARED_RARE_CONTENT": "Content found in only a few submissions (not template material) is shared with others.",
    "TIMESTAMP_ANOMALY": "A timestamp in a screenshot is outside the assignment window or identical to one in "
                         "another student's screenshot.",
    "IDENTICAL_ANNOTATIONS": "Common content was cropped pixel-for-pixel identically to another student's screenshot.",
    "METADATA": "PDF metadata is unusually similar to another student's, or was edited late (weak signal).",
    "EVASION_HIDDEN_TEXT": "The PDF contains text that is invisible when printed or viewed.",
    "EVASION_ZERO_WIDTH": "Invisible zero-width characters are inserted in the typed text.",
    "EVASION_HOMOGLYPH": "Some words use look-alike letters from other alphabets.",
    "EVASION_TRANSFORM": "An image matches another submission only after being flipped, rotated or colour-inverted.",
}
SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1, "info": 0}


def rarity(df: int, n_eff: int, common_fraction: float) -> float:
    """IDF weight in 0..1: unique content = 1, content in > common_fraction of submissions = 0."""
    if df / n_eff > common_fraction:
        return 0.0
    return math.log(n_eff / df) / math.log(n_eff)


def _thresholds() -> dict:
    s = get_settings()
    return s.model_dump(mode="json", exclude={"data_dir", "host", "port", "workers"})


def _identity_flags(db, sub, items, idx: Index, students: list[Student]) -> list[dict]:
    out = []
    own = sub.student
    image_ids = {it.id for it in items if it.kind in IMAGE_KINDS}
    ents = db.scalars(select(Entity).where(Entity.submission_id == sub.id)).all()
    shot_ents = [e for e in ents if e.item_id in image_ids]
    text = "\n".join(it.norm_text or "" for it in items if it.kind in IMAGE_KINDS)
    tokens = set(re.findall(r"[\w.@-]+", text))
    own_vals = {v.lower() for v in (own.student_id, own.username, own.email) if own and v}
    ent_vals = {e.normalized for e in shot_ents if e.type in ("username", "email", "student_id")}
    hits = []
    for st in students:
        if own and st.id == own.id:
            continue
        for field, v in (("student_id", st.student_id), ("username", st.username), ("email", st.email)):
            v = (v or "").lower()
            if len(v) >= 4 and v not in own_vals and (v in ent_vals or (field != "username" and v in tokens)):
                hits.append({"student_id": st.student_id, "field": field, "value": v})
        name = (st.name or "").lower()
        if len(name.split()) >= 2 and re.search(rf"\b{re.escape(name)}\b", text):
            hits.append({"student_id": st.student_id, "field": "name", "value": st.name})
    if hits:
        out.append({"type": "FOREIGN_IDENTITY", "severity": "high",
                    "summary": "Screenshot shows " + ", ".join(f"{h['field']} '{h['value']}' of student "
                                                               f"{h['student_id']}" for h in hits[:3]) + ".",
                    "evidence": {"hits": hits}})
    # usernames/hostnames seen in another student's screenshots (no roster needed)
    mine = {(e.type, e.normalized) for e in shot_ents if e.type in ("username", "hostname")
            and e.normalized not in own_vals}
    if mine:
        others = db.execute(select(Entity.type, Entity.normalized, Entity.submission_id)
                            .where(Entity.submission_id.in_(idx.subs), Entity.submission_id != sub.id,
                                   Entity.type.in_(("username", "hostname")),
                                   Entity.normalized.in_([v for _, v in mine]))).all()
        by_val = defaultdict(set)
        for t, v, osid in others:
            if (t, v) in mine and idx.subs[osid]["student_pk"] != sub.student_pk:
                by_val[(t, v)].add(osid)
        shared = [{"type": t, "value": v, "submissions": sorted(ids)} for (t, v), ids in by_val.items()
                  if len(ids) <= get_settings().rare_max_submissions]
        if shared:
            out.append({"type": "SHARED_IDENTITY", "severity": "medium",
                        "summary": "Shares " + ", ".join(f"{x['type']} '{x['value']}'" for x in shared[:3])
                                   + " with another student's screenshots.",
                        "evidence": {"shared": shared}})
    return out


def _timestamp_flags(db, sub, idx: Index, assignment: Assignment) -> list[dict]:
    ents = db.scalars(select(Entity).where(Entity.submission_id == sub.id, Entity.type == "timestamp")).all()
    evidence = []
    lo, hi = assignment.start_at, assignment.deadline_at
    for e in ents:
        try:
            dt = datetime.fromisoformat(e.normalized)
        except ValueError:
            continue
        if "t" not in e.normalized:  # date only: compare whole days
            outside = (lo and dt.date() < lo.date()) or (hi and dt.date() > hi.date())
        else:
            outside = (lo and dt < lo.replace(tzinfo=None)) or (hi and dt > hi.replace(tzinfo=None))
        if outside:
            evidence.append({"reason": "outside assignment window", "raw": e.raw, "item_id": e.item_id})
    exact = [e for e in ents if "t" in e.normalized]  # has a time of day, not just a date
    if exact:
        rows = db.execute(select(Entity.normalized, Entity.submission_id, Entity.raw)
                          .where(Entity.type == "timestamp", Entity.submission_id.in_(idx.subs),
                                 Entity.submission_id != sub.id,
                                 Entity.normalized.in_([e.normalized for e in exact]))).all()
        for _norm, osid, raw in rows:
            if idx.subs[osid]["student_pk"] != sub.student_pk:
                evidence.append({"reason": "identical timestamp in another student's screenshot", "raw": raw,
                                 "other_submission_id": osid})
    if not evidence:
        return []
    return [{"type": "TIMESTAMP_ANOMALY", "severity": "medium",
             "summary": "; ".join(sorted({e["reason"] for e in evidence})) + ".", "evidence": {"items": evidence}}]


def score_submission(db, sub: Submission, idx: Index, all_subs: list[Submission], students: list[Student]) -> dict:
    s = get_settings()
    db.execute(delete(Flag).where(Flag.submission_id == sub.id))
    if sub.is_reference:
        sub.report_json = {"tier": "REF", "reasons": ["Reference material (not a student submission)."]}
        return sub.report_json
    ov = overlaps(db, sub, idx)
    population = sum(1 for v in idx.subs.values() if not v["is_reference"])
    n_eff = max(population, s.min_idf_population)
    weights, dfs = {}, {}
    for item_id, rec in ov.items():
        df = 1 + len({h["other_sub"] for h in rec["hits"] if not idx.subs[h["other_sub"]]["is_reference"]})
        dfs[item_id] = df
        weights[item_id] = 0.0 if rec["whitelisted"] else rarity(df, n_eff, s.common_fraction)
    total = sum(weights.values()) or 1e-9

    matches = db.scalars(select(Match).where(Match.submission_id == sub.id)).all()
    frac_item = defaultdict(float)
    frac_src = defaultdict(lambda: defaultdict(float))
    for m in matches:
        f = 1.0 if m.kind in ("image_hash", "image_feature") else m.score
        frac_item[m.item_id] = max(frac_item[m.item_id], f)
        frac_src[m.other_submission_id][m.item_id] = max(frac_src[m.other_submission_id][m.item_id], f)
    coverage = sum(weights.get(i, 0) * f for i, f in frac_item.items()) / total
    by_source = []
    for osid, items in frac_src.items():
        share = sum(weights.get(i, 0) * f for i, f in items.items()) / total
        if share <= 0:  # only template/whitelisted content in common
            continue
        info = idx.subs.get(osid, {})
        by_source.append({"submission_id": osid, "filename": info.get("filename"), "share": round(share, 4),
                          "items": len(items), "is_reference": info.get("is_reference", False)})
    by_source.sort(key=lambda x: -x["share"])
    num_sources = sum(1 for b in by_source if b["share"] >= s.min_source_share)

    flags = []
    top = by_source[0] if by_source else None
    if top and top["share"] >= s.single_source_high:
        flags.append({"type": "HIGH_SINGLE_SOURCE", "severity": "high",
                      "summary": f"{top['share']:.0%} of weighted content matches {top['filename']}.",
                      "evidence": {"source": top}})
    elif coverage >= s.collage_high and num_sources >= s.collage_min_sources:
        flags.append({"type": "HIGH_COLLAGE", "severity": "high",
                      "summary": f"{coverage:.0%} of weighted content matches {num_sources} different submissions.",
                      "evidence": {"sources": by_source[:10]}})

    rare = [i for i in frac_item if 1 < dfs.get(i, 1) <= s.rare_max_submissions and weights.get(i, 0) > 0]
    if rare:
        flags.append({"type": "SHARED_RARE_CONTENT", "severity": "medium" if len(rare) >= 2 else "low",
                      "summary": f"{len(rare)} item(s) shared with at most {s.rare_max_submissions} submissions.",
                      "evidence": {"item_ids": rare}})

    items = [rec["item"] for rec in ov.values()]
    annotated = []
    for it in items:
        if it.kind != "image" or not it.sha256 or dfs.get(it.id, 1) <= s.rare_max_submissions:
            continue
        same = {o for o in idx.sha_subs.get(it.sha256, set()) if o != sub.id
                and idx.subs[o]["student_pk"] != sub.student_pk}
        if 0 < len(same) < s.rare_max_submissions:
            annotated.append({"item_id": it.id, "page": it.page, "identical_in": sorted(same)})
    if len(annotated) >= 1:
        flags.append({"type": "IDENTICAL_ANNOTATIONS", "severity": "medium",
                      "summary": f"{len(annotated)} common screenshot(s) cropped pixel-identically to "
                                 "another student's.", "evidence": {"items": annotated}})

    flags += _identity_flags(db, sub, items, idx, students)
    assignment = db.get(Assignment, sub.assignment_id)
    flags += _timestamp_flags(db, sub, idx, assignment)
    text_items = db.scalars(select(Item).where(Item.submission_id == sub.id, Item.kind == "text_block")).all()
    flags += evasion_flags(sub, text_items, matches)
    flags += metadata_flags(sub, all_subs, assignment.deadline_at)

    sev = max((SEVERITY_ORDER[f["severity"]] for f in flags), default=0)
    tier = "HIGH" if sev >= 3 else "MEDIUM" if sev == 2 or coverage >= s.tier_medium_coverage else "LOW"
    reasons = [f["summary"] for f in sorted(flags, key=lambda f: -SEVERITY_ORDER[f["severity"]])]
    if coverage >= s.tier_medium_coverage and not any(f["severity"] == "high" for f in flags):
        reasons.insert(0, f"{coverage:.0%} of weighted content also appears in other submissions.")
    if sub.is_seed:
        tier, flags = "SEED", []
        reasons = ["Seed submission: indexed for comparison only, no alerts."]
    for f in flags:
        db.add(Flag(submission_id=sub.id, type=f["type"], severity=f["severity"],
                    evidence_json={"summary": f["summary"], **f["evidence"]}))
    sub.report_json = {
        "tier": tier, "coverage": round(coverage, 4), "num_sources": num_sources, "by_source": by_source,
        "reasons": reasons or ["No distinctive shared content found."],
        "item_weights": {str(k): round(v, 3) for k, v in weights.items()},
        "item_df": {str(k): v for k, v in dfs.items()}, "population": population,
        "pipeline_version": PIPELINE_VERSION, "thresholds": _thresholds(),
        "scored_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return sub.report_json


def score_many(db, assignment_id: int, sub_ids=None, idx: Index | None = None, on_progress=None):
    idx = idx or build_index(db, assignment_id)
    all_subs = db.scalars(select(Submission).where(Submission.id.in_(idx.subs))).all()
    students = db.scalars(select(Student)).all()
    todo = [s for s in all_subs if sub_ids is None or s.id in sub_ids]
    for i, sub in enumerate(todo):
        score_submission(db, sub, idx, all_subs, students)
        if on_progress:
            on_progress(i + 1, len(todo))
