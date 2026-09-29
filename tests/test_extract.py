import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import func, select

from checker.core.db import Item, Shingle, Submission, session_scope
from checker.core.ingest import ingest_file
from checker.core.normalize import normalize_text
from checker.core.ocr import get_engine
from checker.core.pdf_extract import extract
from tests.synth.generate import make_inline_image_pdf, make_pdf, make_vector_pdf, screenshot

CODE = ["def total_price(items):", "    s = 0", "    for it in items:", "        s += it.price",
        "    return s", "print(total_price(cart))  # 42.50"]


def test_embedded_images_and_render(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [[screenshot(CODE), screenshot(CODE[:3], dark=False)]])
    ex = extract(pdf)
    kinds = [(i.kind, i.source, i.is_content) for i in ex.images]
    assert kinds.count(("image", "embedded", True)) == 2
    assert ("page_render", "render", False) in kinds  # rendered, but not counted as content
    assert ex.pages[0].path == "embedded"


def test_smask_composited_on_white(tmp_path):
    im = Image.new("RGBA", (200, 150), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle((50, 40, 150, 110), fill=(200, 0, 0, 255))
    ex = extract(make_pdf(tmp_path / "t.pdf", [[im]]))
    img = next(i.image for i in ex.images if i.source == "embedded")
    arr = np.asarray(img)
    assert tuple(arr[5, 5]) == (255, 255, 255)  # transparent corner -> white, not black
    assert arr[75, 100, 0] > 150 and arr[75, 100, 1] < 60


def test_inline_image_fallback(tmp_path):
    """Case 9: get_images() returns nothing, page is still a screenshot."""
    pdf = make_inline_image_pdf(tmp_path / "inline.pdf", screenshot(CODE))
    import pymupdf
    assert pymupdf.open(pdf)[0].get_images() == []
    ex = extract(pdf)
    crops = [i for i in ex.images if i.source == "render_crop"]
    assert len(crops) == 1 and ex.pages[0].path == "image_info"
    assert crops[0].image.width > 700


def test_vector_page_contour_fallback(tmp_path):
    ex = extract(make_vector_pdf(tmp_path / "v.pdf"))
    assert any(i.source == "render_crop" for i in ex.images)
    assert "contours" in ex.pages[0].path


def test_hidden_text_split_from_visible(tmp_path):
    pdf = make_pdf(tmp_path / "h.pdf", [[screenshot(CODE)]], text="My visible answer text here",
                   hidden_text="secret white padding words")
    ex = extract(pdf)
    assert "visible answer" in ex.pages[0].text
    assert "secret" not in ex.pages[0].text
    assert any("secret" in s["text"] for s in ex.pages[0].hidden_spans)


def test_junk_images_skipped(tmp_path):
    ex = extract(make_pdf(tmp_path / "j.pdf", [[Image.new("RGB", (40, 40), "red"), screenshot(CODE)]]))
    assert ex.skipped_images == 1


def test_ocr_reads_screenshot():
    res = get_engine("rapidocr").extract(screenshot(CODE))
    norm = normalize_text(res["text"])
    assert "total_price" in norm.replace(" ", "")
    assert res["words"] and all(len(w["bbox"]) == 4 for w in res["words"])


def test_ingest_persists_and_is_idempotent(tmp_path, data_dir):
    pdf = make_pdf(tmp_path / "S123_hw.pdf", [[screenshot(CODE)]])
    first = ingest_file(pdf, "A1", ocr=get_engine("rapidocr"))
    assert "skipped" not in first
    again = ingest_file(pdf, "A1")
    assert again["skipped"] == "already ingested"
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Submission)) == 1
        sub = db.scalars(select(Submission)).one()
        assert sub.student.student_id == "S123" and sub.status == "done"
        assert db.scalar(select(func.count()).select_from(Item)) >= 2
        assert db.scalar(select(func.count()).select_from(Shingle)) > 5
