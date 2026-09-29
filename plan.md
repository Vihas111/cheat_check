# Build prompt: Incremental submission similarity checker (PDF + screenshots)

Paste everything below the line into your coding assistant (Claude Code, Cursor, etc.). Ask it to work phase by phase and to stop after each phase for you to test.

---

## 1. Role and goal

You are a senior Python engineer. Build a **local web app** that helps a marker detect copied work among student submissions.

Submissions are **PDF files that contain mostly screenshots** (code, terminal output, app UI, sometimes typed answers). A marker drops new PDFs into a watched folder (or uploads them in the browser). For every new file the app must compare it against **everything it has already seen** and report:

1. Which earlier submissions it overlaps with, and exactly which images and passages match.
2. **Total coverage**: what fraction of this submission is matched to *any* earlier source, even if each single source only explains a small part. This catches students who collage screenshots from several people.
3. Extra evidence signals (identity clues, timestamps, shared mistakes, evasion tricks, metadata).
4. Groups of submissions that share material (clusters).

The output is an **explainable evidence report for human review**. It must never say "X copied Y" or apply any penalty. It says "these submissions share this content" and shows the evidence. Upload order is not proof of who copied whom.

## 2. Assumptions (make these configurable, do not hardcode)

- Runs on the marker's own machine, bound to `127.0.0.1`. No auth in v1. Student work must not leave the machine (no cloud OCR, no external APIs by default).
- No model training. Only algorithms and **pre-trained** models that are downloaded once.
- Typical scale: 50 to 2,000 submissions per assignment, 3 to 40 images each.
- The student identity comes from a **roster CSV** (`student_id, name, username, email`) and a configurable filename regex (e.g. `^(?P<student_id>\w+)_.*\.pdf$`). If neither is available, fall back to the filename stem.
- The PDFs are downloaded copies. Filesystem dates are meaningless; only metadata **inside** the PDF is used.

## 3. Tech stack

- Python 3.11+, managed with `uv` or `pip` + `requirements.txt`.
- **PDF:** `pymupdf` (import as `pymupdf`).
- **OCR:** pluggable interface `OcrEngine.extract(image) -> {text, words:[{text, bbox, conf}]}`. Default backend is Tesseract via `pytesseract` (light, fast). Optional backends: PaddleOCR and RapidOCR. Public benchmarks I found are single-document tests, so add a `bench-ocr` CLI command that runs each installed engine on a sample of the marker's own screenshots and prints speed plus how many known strings were recovered.
- **Images:** `Pillow`, `numpy`, `opencv-python-headless`, `imagehash`.
- **Optional deep image descriptor:** SSCD (Meta's self-supervised copy-detection model, pre-trained, TorchScript, 512-d, use `sscd_disc_mixup`) behind a feature flag `ENABLE_SSCD`. Use `faiss-cpu` or plain numpy cosine for lookup. It was trained for photo copy detection, so treat it as a **candidate generator only** for screenshots and always confirm with OCR text or feature matching.
- **Text:** `scikit-learn` (TF-IDF), `rapidfuzz`, `ftfy`, `unicodedata`, `pygments` (code tokenizing), `dateparser`.
- **Backend:** FastAPI + SQLAlchemy 2 + SQLite (WAL mode). **Frontend:** Jinja2 templates + HTMX + a little vanilla JS (no SPA build step). **Jobs:** a persistent job table processed by a worker thread pool (`concurrent.futures`), so a restart resumes unfinished jobs. **Watcher:** `watchdog`.
- **Tests:** `pytest`. **Lint:** `ruff`.

## 4. Project layout

```
checker/
  app/                # FastAPI app, routes, templates, static
  core/
    ingest.py         # PDF -> ExtractedSubmission
    pdf_extract.py    # images, page renders, text layer, metadata, hidden text
    ocr.py            # OcrEngine interface + backends
    normalize.py      # unicode/text normalization, boilerplate stripping
    fingerprint.py    # image hashes, transforms, shingles, winnowing
    entities.py       # usernames, paths, emails, IDs, timestamps from OCR text
    index.py          # image hash index, shingle inverted index, embedding index
    match.py          # candidate search + per-item attribution
    verify.py         # ORB/SIFT + RANSAC verification, text diff alignment
    score.py          # coverage, IDF weighting, risk tiers, reasons
    cluster.py        # graph + connected components / communities
    forensics.py      # metadata, evasion, tamper (ELA) checks
  cli.py              # ingest, rescan, calibrate, bench-ocr, serve
  config.py           # pydantic-settings, all thresholds here
tests/
  synth/              # synthetic PDF generator + expected-result manifest
  test_*.py
```

## 5. Data model (SQLite)

- `assignments(id, name, start_at, deadline_at, notes)`
- `students(id, student_id, name, username, email)`
- `submissions(id, assignment_id, student_pk, filename, sha256, page_count, pdf_meta_json, ingested_at, pipeline_version, status)`
- `items(id, submission_id, page, idx, kind['image'|'page_render'|'text_block'], source['embedded'|'render_crop'], bbox, width, height, sha256, phash, dhash, whash, hash_variants_json, sscd_vec BLOB NULL, ocr_text, ocr_conf, thumb_path)`
- `shingles(hash INTEGER, submission_id, item_id)` with an index on `hash` (inverted index; this is what makes lookup fast)
- `entities(id, submission_id, item_id, type['username'|'hostname'|'path'|'email'|'student_id'|'timestamp'], raw, normalized)`
- `matches(id, submission_id, other_submission_id, item_id, other_item_id, kind['image_hash'|'image_feature'|'ocr_text'|'code_structure'], score, detail_json)` — **store symmetric**: when B is ingested and matches A, both A and B show the match.
- `flags(id, submission_id, type, severity, evidence_json)`
- `whitelist(id, kind['image'|'shingle'|'entity'], fingerprint, scope, reason, created_at)`
- `reviews(id, submission_id, status['unreviewed'|'reviewed'|'false_positive'|'confirmed'], note, ts)`
- `jobs(id, submission_id, state, error, attempts, updated_at)`

Store `pipeline_version` on every submission so changing the algorithm marks old rows stale and `rescan` can recompute them. Ingest must be **idempotent** (skip a file whose SHA-256 already exists unless `--force`).

## 6. Pipeline for one new PDF

### 6.1 Extraction (`pdf_extract.py`)

1. Extract embedded images per page with `page.get_images(full=True)` and `doc.extract_image(xref)`. **Handle soft masks (SMask)** by combining with the mask before hashing, otherwise transparent screenshots come out wrong.
2. **Do not trust `get_images()` alone.** PyMuPDF can return zero images for some screenshot-style PDFs (there is an open upstream issue about exactly this). So **always also render every page** at 150 to 200 DPI (`page.get_pixmap`) and store it as a `page_render` item. If a page has no extractable images, or its embedded images cover less than about 60% of the page area, also crop the rendered page into regions (`page.get_image_info()` bboxes when available, otherwise contour-based segmentation of non-background regions). Log which path was used.
3. Extract the text layer with `page.get_text("dict")`, keeping span font size, color, and render mode.
4. Extract PDF metadata: Info dictionary, XMP, producer/creator/author, creation and modification dates, number of incremental updates (count `%%EOF` markers), and embedded font names.
5. Skip decorative junk: images below a minimum size (default 80x80 px) or nearly uniform color. Keep a count of skipped images.

### 6.2 OCR and normalization

- OCR every image and page render. Store word-level boxes and confidences.
- Pre-process for screenshots: upscale small images 2x, convert to grayscale, optionally invert dark-theme screenshots, then OCR. Keep raw OCR text and normalized text separately.
- **Normalization (`normalize.py`), applied to text-layer text and OCR text alike:** NFKC, strip zero-width characters and BOM, map common confusables (Cyrillic/Greek lookalikes to Latin), lowercase, collapse whitespace, strip line numbers and trailing punctuation noise.
- **Boilerplate stripping:** the marker can upload the assignment brief and starter code as "reference boilerplate". Shingles found in it are excluded from matching.

### 6.3 Fingerprints (`fingerprint.py`)

- **Image hashes:** pHash (use a larger hash, e.g. 12x12 = 144 bit), dHash, and wHash. Also store pHash for these variants: horizontal flip, vertical flip, 90/180/270 rotations, grayscale, color-inverted. Pack hashes as uint64 arrays so Hamming distance is vectorized in numpy.
- **Exact:** SHA-256 of raw image bytes and of the decoded pixel array.
- **Text shingles:** word 5-grams of normalized OCR text, hashed to 64-bit ints, into the inverted index. Also line-level hashes (whole normalized lines) because screenshots of terminal output match well on lines.
- **Code-aware matching:** if an image's OCR looks like code (pygments guess with a confidence heuristic), tokenize it, replace identifiers with a placeholder and literals with a type token, then run **winnowing** (MOSS-style k-gram fingerprinting) so renamed variables and reformatting do not hide copying.
- **Optional SSCD embedding** per image when enabled.

### 6.4 Entity extraction (`entities.py`)

From OCR text extract: usernames, hostnames, Windows/Unix paths (`C:\Users\<name>\`, `/home/<name>/`), emails, student-ID patterns (configurable regex), and timestamps/dates (taskbar clocks, `ls -l` output, terminal logs, browser tabs). Normalize timestamps with `dateparser` and keep the raw string.

## 7. Matching (`match.py`, `verify.py`)

For the new submission S, for each item:

1. **Image candidates:** Hamming distance to all stored hashes (all variants). Thresholds are in config (start with pHash distance ≤ 10 of 144 bits for "near duplicate", ≤ 2 for "exact"). Add SSCD cosine candidates if enabled.
2. **Text candidates:** look up S's shingle hashes in the inverted index, count shared shingles per other submission, keep the top N (default 25), and compute a containment score (shared shingles / S's shingles) and Jaccard.
3. **Verification of shortlisted pairs only:**
   - Images: ORB (or SIFT) feature matching with a ratio test and RANSAC homography. Report inlier count and the estimated transform, so crops, shifts, and scaling are confirmed.
   - Text: aligned diff (`difflib` / `rapidfuzz`) to produce the exact matching passages for side-by-side display.
4. **Skip** matches where both submissions have the same `student_id`.
5. **Attribution:** each item of S gets a list of `(other_submission, other_item, kind, score)`. An item can match several sources.

**Cross-item matching is required.** An image in S may match an image on a *different page or position* in another submission. Never compare page N to page N only.

## 8. Scoring and risk (`score.py`)

Produce an explainable report, not one opaque number.

- **Rarity weighting (IDF for images and passages):** an item that appears in more than `COMMON_FRACTION` (default 25%) of submissions in the assignment is treated as template/expected output and gets a weight near zero. Weight = `log(N / df)` normalized to 0..1. Whitelisted items get weight 0.
- **Coverage:** `coverage = sum(weight_i for matched items) / sum(weight_i for all items)`, where each item counts once regardless of how many sources match it. Also report `coverage_by_source` (each source's share) and `num_sources`.
- **Flags** (each with severity and the evidence attached):
  - `HIGH_SINGLE_SOURCE`: one source explains ≥ 50% of weighted content.
  - `HIGH_COLLAGE`: total coverage ≥ 60% from ≥ 3 sources, even if no single source is high.
  - `FOREIGN_IDENTITY`: another student's roster name, username, email, or ID appears in a screenshot of S (this is strong evidence).
  - `SHARED_RARE_CONTENT`: passages, error messages, or typos shared with ≤ 3 submissions in total and absent from boilerplate. Rare shared *mistakes* are much stronger than shared correct content. If the marker supplies an optional answer key/expected-output file, also flag identical **wrong** answers.
  - `TIMESTAMP_ANOMALY`: an in-screenshot timestamp outside the assignment window, or an identical timestamp shared with another student's screenshot.
  - `IDENTICAL_ANNOTATIONS`: same crop boundaries, arrows, or highlight boxes and the same screenshot ordering, even when the underlying content is common.
  - `METADATA`: same rare author string, near-identical creation timestamps, modification long after deadline, unusual incremental edits. Weak signal; never HIGH alone. Do not flag a shared common producer such as "Microsoft: Print To PDF".
  - `EVASION_*`: see section 9.
- **Risk tier:** LOW / MEDIUM / HIGH derived from transparent rules over the flags (config file), always displayed with the list of reasons. No penalty logic anywhere.
- **Symmetry and rescans:** when a new file arrives, earlier submissions gain matches to it too, so update their flags and coverage. `rescan` recomputes IDF weights and everything else across the assignment, because early files have too little context when they are first ingested.

## 9. Evasion and tamper detection (`forensics.py`)

- **Transformed images:** handled by the hash variants (flip, rotate, grayscale, invert) plus resize/recompression tolerance. Also test: cropped borders, added padding, and slight color shifts. Flag `EVASION_TRANSFORM` when a match only exists via a transformed variant.
- **Text-layer vs OCR mismatch:** compare the PDF text layer with OCR of the rendered page. Flag hidden text (white or near-background color, font size < 3 pt, render mode 3, text outside the page box), homoglyph substitution (mixed-script words), and zero-width characters.
- **Paraphrase/reorder:** bag-of-shingles containment (order-insensitive) and, optionally, sentence embeddings (`sentence-transformers`, `all-MiniLM-L6-v2`) behind a flag. Report as "possible paraphrase", lower confidence.
- **Screenshot tampering (optional, flag `ENABLE_TAMPER`):** Error Level Analysis, double-JPEG-compression hint, clone-region detection. These are noisy; output only "take a closer look" flags with a heatmap and never contribute to HIGH alone.
- **Inconsistent rendering:** region with different sharpness, font, or noise than the rest of the same screenshot (only as a hint).

## 10. External and reference sources

- `reference/` folder: previous cohorts' submissions, known solutions, and **LLM-generated sample answers** the marker creates for this assignment. Indexed exactly like submissions but labelled `reference` in the UI. Do **not** build or ship an "AI-written text detector"; those produce false accusations.
- Optional plug-in interface `WebLookup` (disabled by default) that would search distinctive OCR phrases online. If implemented, show a clear warning that snippets of student work leave the machine.
- Optional stylometry comparison with the same student's earlier submissions: low weight, informational only, must never raise the tier by itself.

## 11. Clustering (`cluster.py`)

Build a graph (submissions = nodes, edges weighted by shared rare content, excluding whitelisted and common items). Compute connected components and, for large components, community detection (`networkx` Louvain). Show each cluster with its members, the shared items, and the likely "hub" (the submission whose content appears in the most others), worded as "shared source candidate", not as an accusation.

## 12. Web UI

- **Dashboard:** table of submissions with risk badge, coverage %, number of sources, top flags, review status; filters by assignment, tier, and status; live job status (queued / processing / done / failed with error).
- **Submission detail:**
  - Source breakdown: a bar showing coverage by source, and a per-item provenance list ("image 3, page 2 -> Submission B, image 5, ORB inliers 84").
  - **Side-by-side viewer** for matched images with the ORB match overlay, and for text with highlighted matching passages.
  - Evidence panel listing every flag with its raw evidence, and the metadata comparison table.
  - Buttons: **mark reviewed**, **false positive**, **confirmed**, **ignore this image/passage** (adds to whitelist and recomputes), add a note.
- **Clusters page** and an **Export** button (CSV of scores plus a printable HTML report for one submission, which the marker can attach to an academic-integrity case).
- **Settings page:** thresholds, weights, roster upload, boilerplate upload, reference upload, assignment window dates.
- **Calibration page** (`calibrate` CLI equivalent): histograms of pairwise image distance, text containment, and coverage across the current assignment, with a suggested cutoff at the point where outliers separate from the crowd.

## 13. CLI

```
python -m checker.cli serve                      # start the web app + watcher
python -m checker.cli ingest <folder> --assignment "A1" [--seed]   # --seed = index only, no alerts
python -m checker.cli rescan --assignment "A1"
python -m checker.cli calibrate --assignment "A1"
python -m checker.cli bench-ocr <sample_images_dir>
python -m checker.cli synth --out tests/synth/out   # generate the test corpus
```

`--seed` is for first use: index a folder of already-marked work without generating alerts for it.

## 14. Testing and acceptance criteria

Build a **synthetic corpus generator** (`tests/synth`) that creates PDFs with known relationships and an `expected.json` manifest. Include at least:

1. Exact copy of another student's PDF.
2. Same screenshots, re-exported through a different PDF producer, with different metadata.
3. Screenshots resized, JPEG-recompressed, cropped, padded, flipped, and color-inverted.
4. **Collage:** student X built from 3 images of A, 3 of B, 2 of C, plus 1 original. Pairwise overlap with each is small; total coverage must be flagged.
5. Code screenshot with renamed variables and changed formatting.
6. Hidden white text, homoglyphs, and zero-width characters.
7. A screenshot showing another student's username/path.
8. **Hard negatives:** many students submitting the identical expected-output screenshot or template; independent submissions with the same correct answer. These must **not** reach HIGH.
9. A PDF where `get_images()` returns nothing but the page is a screenshot (exercise the render fallback).

Acceptance: every positive case above is flagged at the right tier; hard negatives stay LOW; report precision/recall per case type in a test summary; ingesting a new file into a 500-submission database (excluding OCR time) completes in under 10 seconds on a laptop; re-ingesting an already-seen file is a no-op; killing the process mid-ingest and restarting resumes the job.

## 15. Non-goals and safeguards

- No automated penalties, no accusations, no "AI-generated" verdicts.
- No transmitting student data off the machine unless the user explicitly enables an external plug-in.
- Every flag must show its evidence. If a flag cannot be explained to a student in one sentence with the evidence in front of them, it should not exist.
- Log the pipeline version and thresholds used for each report so results are reproducible.

## 16. Delivery plan (stop after each phase)

1. **Phase 1:** project scaffold, DB, PDF extraction with render fallback, OCR interface (Tesseract), normalization, image hashes. CLI `ingest` prints what was extracted for one PDF. Tests for extraction.
2. **Phase 2:** shingle index, image hash index, matching, coverage, per-source attribution, `--seed`, symmetric matches, `rescan`. Synthetic corpus cases 1 to 4 and 8 passing.
3. **Phase 3:** FastAPI + HTMX UI (dashboard, detail with side-by-side viewer, review buttons, whitelist), background jobs, folder watcher.
4. **Phase 4:** ORB/RANSAC verification, entity extraction (identity, timestamps), rare-content weighting, metadata flags, clustering.
5. **Phase 5:** evasion checks (hidden text, homoglyphs, transforms), code-aware winnowing, reference sources, calibration page, export.
6. **Phase 6 (optional):** SSCD embeddings, sentence embeddings, tamper analysis, alternate OCR backends, stylometry.

Before writing code, restate your plan and list any assumption you are unsure about. Then start Phase 1.
