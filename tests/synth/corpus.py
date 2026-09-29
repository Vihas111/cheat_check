"""Synthetic corpus with known relationships (plan.md §14) + expected.json manifest.

Students S01..S12 do their own work, H1..H6 are hard negatives, C1..C7 are the positive cases.
Everyone includes a screenshot of the same expected program output (template material)."""

import csv
import io
import json
import random
import shutil
from pathlib import Path

from PIL import Image, ImageOps

from tests.synth.generate import make_pdf, screenshot

WORDS = ("alpha bravo cedar delta ember falcon garnet harbor indigo jasper kettle lumen mosaic nectar orbit "
         "pepper quartz raven saffron timber umber velvet willow xenon yonder zephyr amber basil cobalt dune "
         "fjord glacier hollow ivory juniper kelp lagoon meadow nimbus onyx prairie quill ridge summit tundra").split()

CODE_A = ["def total_price(items):", "    subtotal = 0", "    for entry in items:",
          "        subtotal += entry.price * entry.qty", "    discount = subtotal * 0.1",
          "    return subtotal - discount", "print(total_price(cart))"]
# Same program, identifiers renamed and reformatted (case 5).
CODE_A_RENAMED = ["def compute_cost(things):", "  acc=0", "  for t in things:", "    acc+=t.price*t.qty",
                  "  off=acc*0.1", "  return acc-off", "print(compute_cost(basket))"]
SOLUTION_LOOP = ["prices = load('cart.csv')", "running = 0", "while prices:", "    running += prices.pop()",
                 "print('total:', round(running, 2))"]
SOLUTION_COMPREHENSION = ["import csv", "with open('cart.csv') as fh:",
                          "    rows = [float(r[1]) for r in csv.reader(fh)]", "print(f'total: {sum(rows):.2f}')"]
TEMPLATE = ["$ python grader.py --check", "test_parse ........ PASSED", "test_total ........ PASSED",
            "test_report ....... PASSED", "3 passed in 0.42s"]


def own_shot(sid: str, n: int) -> Image.Image:
    """A screenshot nobody else has: random words seeded by student and index."""
    rnd = random.Random(f"{sid}-{n}")
    lines = [f"$ python task{n}.py --input {rnd.choice(WORDS)}_{rnd.randint(10, 99)}.csv"]
    lines += [" ".join(rnd.sample(WORDS, 4)) + f" = {rnd.randint(100, 9999)}" for _ in range(4)]
    return screenshot(lines, width=680, size=18, seed=hash(sid) % 1000 + n, dark=n % 2 == 0)


def template_shot(sid: str) -> Image.Image:
    """Everyone screenshots the same expected output, each with their own window title."""
    return screenshot(TEMPLATE, width=680, size=18, title=f"terminal {sid.lower()}")


def jpeg(im: Image.Image, q=60) -> Image.Image:
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    return Image.open(io.BytesIO(b.getvalue())).convert("RGB")


def build(out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    roster, expected, shots = [], {}, {}

    def student(sid, name, username):
        roster.append({"student_id": sid, "name": name, "username": username, "email": f"{username}@uni.test"})

    def pdf(sid, images, **kw):
        path = out / f"{sid}_hw.pdf"
        make_pdf(path, [images[i:i + 2] for i in range(0, len(images), 2)], **kw)
        return path.name

    for i in range(1, 13):
        sid = f"S{i:02d}"
        student(sid, f"Student {WORDS[i].title()} {WORDS[-i].title()}", f"{WORDS[i]}{i:02d}x")
        n = 5 if sid in ("S04", "S05", "S06") else 3
        shots[sid] = [own_shot(sid, k) for k in range(n)]
        if sid == "S07":
            shots[sid][0] = screenshot(CODE_A, width=680, size=18, title="main.py - editor")
        pdf(sid, [template_shot(sid)] + shots[sid])
        expected[f"{sid}_hw.pdf"] = {"case": "independent"}
    for sid, tier in (("S01", "HIGH"), ("S02", "HIGH"), ("S03", "HIGH"), ("S04", "MEDIUM"), ("S05", "MEDIUM"),
                      ("S06", "MEDIUM")):  # sources of the positive cases: matches are stored symmetrically
        expected[f"{sid}_hw.pdf"] = {"case": "source_of_copy", "min_tier": tier}
    for i in range(1, 7):
        sid = f"H{i}"
        student(sid, f"Hard Negative {WORDS[20 + i].title()}", f"{WORDS[20 + i]}{i}h")
        imgs = [template_shot(sid), own_shot(sid, 0), own_shot(sid, 1)]
        if sid in ("H1", "H2"):  # independent solutions to the same task, same correct output line
            code = SOLUTION_LOOP if sid == "H1" else SOLUTION_COMPREHENSION
            imgs[1] = screenshot(code + ["total: 42.50"], width=680, size=18, title=f"{sid} solution")
        pdf(sid, imgs)
        expected[f"{sid}_hw.pdf"] = {"case": "hard_negative", "max_tier": "LOW"}

    for i in range(1, 8):
        student(f"C{i}", f"Case Student {WORDS[30 + i].title()}", f"{WORDS[30 + i]}{i}c")

    # 1. exact copy of S01's PDF
    shutil.copyfile(out / "S01_hw.pdf", out / "C1_hw.pdf")
    expected["C1_hw.pdf"] = {"case": "exact_copy", "min_tier": "HIGH", "flags": ["HIGH_SINGLE_SOURCE"],
                             "source": "S01_hw.pdf"}
    # 2. same screenshots, re-exported as JPEG through another producer
    pdf("C2", [jpeg(template_shot("C2"))] + [jpeg(im) for im in shots["S02"]],
        meta={"producer": "Microsoft: Print To PDF", "creator": "Microsoft Word", "author": "c2"})
    expected["C2_hw.pdf"] = {"case": "reexport", "min_tier": "HIGH", "flags": ["HIGH_SINGLE_SOURCE"],
                             "source": "S02_hw.pdf"}
    # 3. transformed screenshots
    a, b, c = shots["S03"]
    w, h = b.size
    transformed = [a.resize((a.width * 3 // 4, a.height * 3 // 4)), b.crop((20, 12, w - 20, h - 8)),
                   ImageOps.expand(c, border=30, fill=(255, 255, 255)), ImageOps.mirror(a),
                   ImageOps.invert(b), jpeg(c, 35)]
    pdf("C3", [template_shot("C3")] + transformed)
    expected["C3_hw.pdf"] = {"case": "transformed", "min_tier": "HIGH", "flags": ["HIGH_SINGLE_SOURCE"],
                             "source": "S03_hw.pdf"}
    # 4. collage from three sources + one original
    pdf("C4", [template_shot("C4")] + shots["S04"][:2] + shots["S05"][2:4] + shots["S06"][1:3] + [own_shot("C4", 0)])
    expected["C4_hw.pdf"] = {"case": "collage", "min_tier": "HIGH", "flags": ["HIGH_COLLAGE"]}
    # 5. code with renamed identifiers and different formatting
    pdf("C5", [template_shot("C5"), screenshot(CODE_A_RENAMED, width=680, size=18, dark=False, title="cost.py")])
    expected["C5_hw.pdf"] = {"case": "renamed_code", "min_tier": "MEDIUM", "match_kind": "code_structure",
                             "source": "S07_hw.pdf"}
    # 6. hidden white text, homoglyphs, zero-width characters in the typed answer
    pdf("C6", [template_shot("C6"), own_shot("C6", 0)], text="My аnswer is the\u200b following result",
        hidden_text="keywords keywords stuffing to pad the text similarity")
    expected["C6_hw.pdf"] = {"case": "evasion", "min_tier": "MEDIUM",
                             "flags": ["EVASION_HIDDEN_TEXT", "EVASION_HOMOGLYPH"]}
    # 7. screenshot showing another student's (S08) username in a path
    s08 = next(r for r in roster if r["student_id"] == "S08")["username"]
    pdf("C7", [template_shot("C7"), screenshot([f"PS C:\\Users\\{s08}\\Desktop\\hw2> python main.py",
                                                "Loading data ... done", "rows processed: 1284"],
                                               width=680, size=18, title="Windows PowerShell"), own_shot("C7", 0)])
    expected["C7_hw.pdf"] = {"case": "foreign_identity", "min_tier": "HIGH", "flags": ["FOREIGN_IDENTITY"]}

    with open(out / "roster.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["student_id", "name", "username", "email"])
        wr.writeheader()
        wr.writerows(roster)
    (out / "expected.json").write_text(json.dumps(expected, indent=2))
    return expected


TIERS = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def evaluate(expected: dict, results: dict) -> list[dict]:
    """results: filename -> {tier, flags:set, sources:set(filenames), match_kinds:set}. One row per file."""
    rows = []
    for fn, exp in sorted(expected.items()):
        r = results[fn]
        problems = []
        t = TIERS.get(r["tier"], -1)
        if "min_tier" in exp and t < TIERS[exp["min_tier"]]:
            problems.append(f"tier {r['tier']} < {exp['min_tier']}")
        if "max_tier" in exp and t > TIERS[exp["max_tier"]]:
            problems.append(f"tier {r['tier']} > {exp['max_tier']}")
        problems += [f"missing flag {f}" for f in exp.get("flags", []) if f not in r["flags"]]
        if "source" in exp and exp["source"] not in r["sources"]:
            problems.append(f"source {exp['source']} not found")
        if "match_kind" in exp and exp["match_kind"] not in r["match_kinds"]:
            problems.append(f"no {exp['match_kind']} match")
        rows.append({"file": fn, "case": exp["case"], "tier": r["tier"], "ok": not problems, "problems": problems})
    return rows


def summary(rows: list[dict]) -> str:
    """Per case type: positives flagged (recall) and hard negatives kept LOW."""
    by_case = {}
    for r in rows:
        by_case.setdefault(r["case"], []).append(r["ok"])
    return "\n".join(f"{case:18s} {sum(v)}/{len(v)} as expected" for case, v in sorted(by_case.items()))
