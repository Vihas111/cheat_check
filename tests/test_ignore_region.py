"""Ignoring part of an image: the shared header stops counting, and putting it back restores the match."""

from sqlalchemy import select

from checker.core import regions
from checker.core.db import Item, Match, Whitelist, session_scope
from checker.core.ingest import ingest_file, rescan
from checker.core.ocr import get_engine
from tests.synth.generate import make_pdf, screenshot

HEADER = ["Question 3. Describe how the routing table of router R2",
          "is populated when static routes are configured between",
          "the three subnets shown in the topology and explain",
          "what happens when one of the links goes down."]


def n_matches():
    with session_scope() as db:
        return len(db.scalars(select(Match)).all())


def test_ignored_region_removes_the_match_and_back(data_dir, tmp_path):
    ocr = get_engine()
    bodies = {"A1": ["I used ip route on every device", "ping works"],
              "B2": ["Traffic is rerouted by the backup link", "traceroute shows it"],
              "C3": ["Totally different photosynthesis notes", "chlorophyll absorbs light"]}
    for sid, body in bodies.items():
        f = tmp_path / f"{sid}_x.pdf"
        shots = [screenshot(HEADER + body if sid != "C3" else body + ["x", "y", "z", "w"], seed=5, title="lab")]
        make_pdf(f, [shots])
        ingest_file(f, "lab", ocr=ocr)
    assert n_matches() > 0  # the shared header links A1 and B2

    with session_scope() as db:
        item = db.scalars(select(Item).where(Item.thumb_path.is_not(None))).first()
        iid = item.id
    assert regions.add_region(iid, [0.0, 0.12, 1.0, 0.66]) == "lab"
    assert regions.add_region(iid, [0.1, 0.1, 0.105, 0.105]) is None  # too small
    rescan("lab")
    assert n_matches() == 0
    with session_scope() as db:
        masked = [i.masks_json for i in db.scalars(select(Item).where(Item.thumb_path.is_not(None)))]
        assert sum(1 for m in masked if m) == 2  # the source, and the other copy found by template matching

    with session_scope() as db:  # stop ignoring: the match comes back
        for w in db.scalars(select(Whitelist).where(Whitelist.kind == "region")):
            db.delete(w)
    rescan("lab")
    assert n_matches() > 0
    with session_scope() as db:
        assert all(not i.masks_json for i in db.scalars(select(Item)))
