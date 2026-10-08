"""Ignoring only the question lines of a flagged item keeps the answers in play."""

import pymupdf
from sqlalchemy import select

from checker.app import main as M
from checker.core.db import Item, Match, session_scope
from checker.core.ingest import ingest_file, rescan
from checker.core.ocr import get_engine

QUESTION = ("Question 3. Describe in detail how the routing table of router R2 is populated when the network "
            "uses static routes between the three subnets shown in the topology.")


def typed(path, answer):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(50, 50, 545, 300), QUESTION + "\n\n" + answer, fontsize=11)
    doc.save(path)


def n_matches():
    with session_scope() as db:
        return len(db.scalars(select(Match)).all())


def test_ignore_question_lines_only(data_dir, tmp_path):
    ocr = get_engine()
    typed(tmp_path / "A1_lab.pdf",
          "I added routes manually on every router using the ip route command and verified with ping.")
    typed(tmp_path / "B2_lab.pdf",
          "The table gets entries from the administrator, nothing dynamic happens, and traceroute shows hops.")
    for n in ("A1_lab.pdf", "B2_lab.pdf"):
        ingest_file(tmp_path / n, "lab", ocr=ocr)
    assert n_matches() > 0  # the shared question alone links them

    with session_scope() as db:
        it = db.scalars(select(Item).where(Item.kind == "text_block")).first()
        iid, lines = it.id, M.item_lines(it)
    q = [i for i, ln in enumerate(lines) if ln.lower() in QUESTION.lower()]
    assert M.ignore_text(iid, [len(lines) + 5]).startswith("!")  # nothing valid selected
    assert M.ignore_text(iid, q) == "lab"
    rescan("lab")
    assert n_matches() == 0
