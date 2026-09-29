"""Typed answers with a ruled table and a vector chart (no screenshots).

A copies B's table values and chart; C uses the same table layout and chart axes with its own numbers."""

import pymupdf
from sqlalchemy import select

from checker.core.db import Match, Submission, session_scope
from checker.core.ingest import ingest_file
from checker.core.ocr import get_engine


def typed_pdf(path, rows, points, prose):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(60, 50, 540, 140), prose, fontsize=11)
    x0, y0, cw, rh = 60, 160, 120, 24  # ruled table
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            page.insert_text((x0 + c * cw + 6, y0 + r * rh + 16), cell, fontsize=11)
    for r in range(len(rows) + 1):
        page.draw_line((x0, y0 + r * rh), (x0 + cw * len(rows[0]), y0 + r * rh), width=0.8)
    for c in range(len(rows[0]) + 1):
        page.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + rh * len(rows)), width=0.8)
    gx, gy, gw, gh = 80, 420, 420, 260  # line chart with axes
    page.draw_line((gx, gy + gh), (gx + gw, gy + gh), width=1)
    page.draw_line((gx, gy), (gx, gy + gh), width=1)
    pts = [pymupdf.Point(gx + i * gw / (len(points) - 1), gy + gh - v * gh) for i, v in enumerate(points)]
    page.draw_polyline(pts, color=(0.1, 0.3, 0.8), width=2)
    doc.save(path)


HEAD = ["trial", "time (s)", "speed"]
B_ROWS = [HEAD, ["1", "4.71", "2.12"], ["2", "5.03", "1.99"], ["3", "4.88", "2.05"], ["4", "6.40", "1.56"]]
C_ROWS = [HEAD, ["1", "3.95", "2.53"], ["2", "4.12", "2.43"], ["3", "4.40", "2.27"], ["4", "3.81", "2.62"]]
B_PTS = [0.1, 0.35, 0.3, 0.8, 0.55, 0.9]
C_PTS = [0.8, 0.2, 0.6, 0.15, 0.7, 0.4]


def test_typed_table_and_chart(data_dir, tmp_path):
    typed_pdf(tmp_path / "B1_lab.pdf", B_ROWS, B_PTS,
              "The cart slowed on the third ramp because the felt strip added friction near the bottom edge.")
    typed_pdf(tmp_path / "A1_lab.pdf", B_ROWS, B_PTS,
              "My measurements are below. I repeated the runs four times with the stopwatch app.")
    typed_pdf(tmp_path / "C1_lab.pdf", C_ROWS, C_PTS,
              "Results were steady across all trials, the smooth ramp gave nearly constant speed.")
    ocr = get_engine()
    ids = {}
    for name in ("B1_lab.pdf", "C1_lab.pdf", "A1_lab.pdf"):
        ids[name] = ingest_file(tmp_path / name, "lab", ocr=ocr)["submission_id"]
    with session_scope() as db:
        pairs = {(m.submission_id, m.other_submission_id) for m in db.scalars(select(Match))}
        tiers = {s.filename: s.report_json["tier"] for s in db.scalars(select(Submission))}
    assert (ids["A1_lab.pdf"], ids["B1_lab.pdf"]) in pairs, pairs
    assert (ids["C1_lab.pdf"], ids["B1_lab.pdf"]) not in pairs and (ids["C1_lab.pdf"], ids["A1_lab.pdf"]) not in pairs
    assert tiers["A1_lab.pdf"] != "LOW" and tiers["C1_lab.pdf"] == "LOW", tiers
