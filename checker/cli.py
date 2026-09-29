"""Command line: python -m checker.cli <command>."""

import argparse
import json
import logging
from pathlib import Path


def cmd_ingest(args):
    from checker.core.db import session_scope
    from checker.core.ingest import ingest_file, load_roster
    from checker.core.ocr import get_engine

    if args.roster:
        with session_scope() as db:
            print(f"roster: {load_roster(db, Path(args.roster))} students")
    target = Path(args.path)
    files = sorted(target.glob("*.pdf")) if target.is_dir() else [target]
    ocr = get_engine("none" if args.no_ocr else None)
    for f in files:
        summary = ingest_file(f, args.assignment, force=args.force, seed=args.seed, ocr=ocr)
        print(json.dumps(summary, indent=2 if args.verbose else None, default=str))


def cmd_serve(args):
    import webbrowser

    import uvicorn

    from checker.config import get_settings

    s = get_settings()
    url = f"http://{s.host}:{args.port or s.port}"
    print(f"Similarity checker running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run("checker.app.main:app", host=s.host, port=args.port or s.port, log_level="warning")


def cmd_rescan(args):
    from checker.core.ingest import rescan

    print(json.dumps(rescan(args.assignment, reprocess_all=args.all)))


def cmd_boilerplate(args):
    from checker.core.ingest import add_boilerplate

    print(f"{add_boilerplate(Path(args.path), args.assignment)} fingerprints whitelisted; run rescan to apply")


def cmd_calibrate(args):
    from sqlalchemy import select

    from checker.app.main import histogram, outlier_cutoff
    from checker.core.db import Assignment, Submission, session_scope

    with session_scope() as db:
        a = db.scalar(select(Assignment).where(Assignment.name == args.assignment))
        if not a:
            raise SystemExit(f"unknown assignment {args.assignment!r}")
        cov = [(x.report_json or {}).get("coverage", 0) for x in db.scalars(select(Submission).where(
            Submission.assignment_id == a.id, Submission.status == "done", Submission.is_reference.is_(False)))]
    for b in histogram(cov):
        print(f"{b['lo']:4.0%} {b['n']:4d} {'#' * round(b['h'] * 40)}")
    print(f"n={len(cov)} suggested tier_medium_coverage ~ {outlier_cutoff(cov)}")


def cmd_bench_ocr(args):
    import time

    from PIL import Image

    from checker.core.ocr import available_engines, get_engine

    files = sorted(Path(args.path).glob("*.png")) if Path(args.path).is_dir() else [Path(args.path)]
    for name in available_engines():
        eng = get_engine(name)
        t0 = time.perf_counter()
        words = sum(len(eng.extract(Image.open(f).convert("RGB"))["words"]) for f in files)
        print(f"{name:10s} {len(files)} images  {(time.perf_counter() - t0) / max(len(files), 1):.2f}s/image  "
              f"{words} words")


def cmd_synth(args):
    from tests.synth.corpus import build

    exp = build(Path(args.out))
    print(f"{len(exp)} PDFs + roster.csv + expected.json written to {args.out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="checker")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="ingest a PDF or a folder of PDFs")
    s.add_argument("path")
    s.add_argument("--assignment", required=True)
    s.add_argument("--seed", action="store_true", help="index only, no alerts")
    s.add_argument("--force", action="store_true", help="re-ingest even if the SHA-256 is known")
    s.add_argument("--roster", help="roster CSV (student_id,name,username,email)")
    s.add_argument("--no-ocr", action="store_true")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("serve", help="start the local web app")
    s.add_argument("--port", type=int)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("rescan", help="reprocess stale files and re-score an assignment")
    s.add_argument("assignment")
    s.add_argument("--all", action="store_true", help="re-extract every file, not only outdated ones")
    s.set_defaults(func=cmd_rescan)

    s = sub.add_parser("boilerplate", help="whitelist the brief / starter code (PDF or text file)")
    s.add_argument("path")
    s.add_argument("--assignment", help="default: all assignments")
    s.set_defaults(func=cmd_boilerplate)

    s = sub.add_parser("calibrate", help="coverage histogram and suggested cutoff")
    s.add_argument("assignment")
    s.set_defaults(func=cmd_calibrate)

    s = sub.add_parser("bench-ocr", help="time the installed OCR engines on PNG screenshots")
    s.add_argument("path")
    s.set_defaults(func=cmd_bench_ocr)

    s = sub.add_parser("synth", help="write the synthetic test corpus")
    s.add_argument("out", nargs="?", default="tests/synth/out")
    s.set_defaults(func=cmd_synth)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
