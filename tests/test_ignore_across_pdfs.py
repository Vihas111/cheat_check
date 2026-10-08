"""An ignored part is recognised in OTHER PDFs too, even when they show it at another size or theme:
select the question in A, and B and C no longer match each other because of it."""

from sqlalchemy import select

from checker.app import main as M
from checker.core import regions
from checker.core.db import Item, Match, Submission, Whitelist, session_scope
from checker.core.ingest import ingest_file, rescan
from checker.core.ocr import get_engine
from tests.synth.generate import make_pdf, screenshot

Q = ["Question 3. Describe how the routing table of router R2",
     "is populated when static routes are configured between",
     "the three subnets shown in the topology and explain"]

LOOKS = {  # same question, shown differently
    "A1": dict(size=20, width=900, dark=True, body=["I used ip route on every device", "ping works"]),
    "B2": dict(size=26, width=1250, dark=True,
               body=["Traffic is rerouted by the backup link", "traceroute shows hops"]),
    "C3": dict(size=17, width=760, dark=False,
               body=["Static entries come from the administrator", "no dynamic updates"]),
}


def pair_count(a, b):
    with session_scope() as db:
        names = {s.id: s.filename[:2] for s in db.scalars(select(Submission))}
        return sum(1 for m in db.scalars(select(Match))
                   if {names[m.submission_id], names[m.other_submission_id]} == {a, b})


def ingest_all(tmp_path):
    ocr = get_engine()
    for sid, look in LOOKS.items():
        f = tmp_path / f"{sid}_x.pdf"
        shot = screenshot(Q + look["body"], seed=3, title="lab", size=look["size"], width=look["width"],
                          dark=look["dark"])
        make_pdf(f, [[shot]])
        ingest_file(f, "lab", ocr=ocr)


def a_item():
    with session_scope() as db:
        sub = db.scalars(select(Submission).where(Submission.filename.like("A1%"))).one()
        return db.scalars(select(Item).where(Item.submission_id == sub.id, Item.thumb_path.is_not(None))).first().id


def test_region_selected_in_a_hides_the_shared_question_in_b_and_c(data_dir, tmp_path):
    ingest_all(tmp_path)
    assert pair_count("B2", "C3") > 0  # they share only the question, at different sizes and themes
    assert regions.add_region(a_item(), [0.0, 0.16, 1.0, 0.54]) == "lab"
    rescan("lab")
    assert pair_count("B2", "C3") == 0 and pair_count("A1", "B2") == 0 and pair_count("A1", "C3") == 0
    with session_scope() as db:
        masked = [i.masks_json for i in db.scalars(select(Item).where(Item.thumb_path.is_not(None), Item.is_content))]
        rule = db.scalars(select(Whitelist).where(Whitelist.kind == "region")).one().fingerprint
    assert all(masked), masked  # found in all three PDFs, not only in A
    assert '"found": 3' in rule


def test_text_lines_selected_in_a_hide_the_shared_question_in_b_and_c(data_dir, tmp_path):
    ingest_all(tmp_path)
    assert pair_count("B2", "C3") > 0
    with session_scope() as db:
        it = db.get(Item, a_item())
        lines = M.item_lines(it)
    q = [i for i, ln in enumerate(lines) if any(w in ln.lower() for w in ("question", "populated", "subnets"))]
    assert M.ignore_text(a_item(), q) == "lab"
    rescan("lab")
    assert pair_count("B2", "C3") == 0 and pair_count("A1", "B2") == 0


def item_of(prefix):
    with session_scope() as db:
        sub = db.scalars(select(Submission).where(Submission.filename.like(f"{prefix}%"))).one()
        return db.scalars(select(Item).where(Item.submission_id == sub.id, Item.thumb_path.is_not(None),
                                             Item.is_content)).first().id


def test_works_whichever_pdf_the_rule_came_from(data_dir, tmp_path):
    ingest_all(tmp_path)
    assert regions.add_region(item_of("C3"), [0.0, 0.2, 1.0, 0.58]) == "lab"  # drawn in C, the smallest and lightest
    rescan("lab")
    assert pair_count("A1", "B2") == 0 and pair_count("B2", "C3") == 0 and pair_count("A1", "C3") == 0


def test_copied_answers_still_match_and_duplicates_are_not_added(data_dir, tmp_path):
    ocr = get_engine()
    shared_answer = ["Static routes were added with ip route on", "every router and checked with traceroute"]
    for sid, look in LOOKS.items():
        f = tmp_path / f"{sid}_x.pdf"
        body = shared_answer if sid in ("B2", "C3") else look["body"]  # B and C also copied the same answer
        make_pdf(f, [[screenshot(Q + body, seed=3, title="lab", size=look["size"], width=look["width"],
                                 dark=look["dark"])]])
        ingest_file(f, "lab", ocr=ocr)
    assert pair_count("B2", "C3") > 0
    box = [0.0, 0.16, 1.0, 0.54]
    regions.add_region(item_of("A1"), box)
    regions.add_region(item_of("A1"), box)  # the same box twice
    with session_scope() as db:
        assert len(db.scalars(select(Whitelist).where(Whitelist.kind == "region")).all()) == 1
    rescan("lab")
    assert pair_count("B2", "C3") > 0  # the question is ignored, the copied answer is not
    assert pair_count("A1", "B2") == 0 and pair_count("A1", "C3") == 0  # A shares nothing but the question


def test_whole_image_ignored_in_a_covers_resized_and_cropped_copies(data_dir, tmp_path):
    ocr = get_engine()
    shared = screenshot(["Router#show ip route", "C 192.168.1.0/24 is directly connected",
                         "S 10.0.0.0/8 [1/0] via 192.168.1.2", "Gateway of last resort is not set"],
                        seed=9, title="lab")
    variants = {"A1": shared, "B2": shared.resize((int(shared.width * 1.4), int(shared.height * 1.4))),
                "C3": shared.crop((0, 0, shared.width, int(shared.height * 0.85)))}
    for n, (sid, im) in enumerate(variants.items()):
        f = tmp_path / f"{sid}_x.pdf"
        make_pdf(f, [[im, screenshot([f"my own notes {n} {sid}"] * 3, seed=20 + n, title=f"n{n}")]])
        ingest_file(f, "lab", ocr=ocr)
    assert pair_count("A1", "B2") > 0 and pair_count("A1", "C3") > 0
    with session_scope() as db:
        sub = db.scalars(select(Submission).where(Submission.filename.like("A1%"))).one()
        first = db.scalars(select(Item).where(Item.submission_id == sub.id, Item.thumb_path.is_not(None),
                                              Item.is_content).order_by(Item.idx)).first().id
    M.ignore_item(first, "/")
    rescan("lab")
    assert pair_count("A1", "B2") == 0 and pair_count("A1", "C3") == 0 and pair_count("B2", "C3") == 0


def test_stop_ignoring_restores_the_match(data_dir, tmp_path):
    ingest_all(tmp_path)
    with session_scope() as db:
        lines = M.item_lines(db.get(Item, item_of("A1")))
    q = [i for i, ln in enumerate(lines) if any(w in ln.lower() for w in ("question", "populated", "subnets"))]
    assert M.ignore_text(item_of("A1"), q) == "lab"
    rescan("lab")
    assert pair_count("B2", "C3") == 0
    with session_scope() as db:
        for w in db.scalars(select(Whitelist).where(Whitelist.kind == "snippet")):
            db.delete(w)
    rescan("lab")
    assert pair_count("B2", "C3") > 0
    with session_scope() as db:
        assert all(not i.text_masks_json and not i.masks_json for i in db.scalars(select(Item)))
