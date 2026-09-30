# cheat_check

A local similarity checker for student PDF submissions, built for PDFs that are mostly screenshots.
It finds copied screenshots even after they were re-exported, cropped, resized, mirrored or inverted.
It also finds shared OCR text, and code that was copied with renamed identifiers.
Everything runs on your computer: no cloud OCR and no external APIs.

Results rank submissions for a person to review. Every signal links to its evidence.
A score is never a finding of misconduct.

## Start

```bash
uv sync
uv run python -m checker.cli serve        # opens http://127.0.0.1:8000
```

1. Create an assignment (optionally with open/deadline dates).
2. Drag PDFs onto the dashboard. Name them `studentid_anything.pdf` to link them to the roster.
   You can also copy files into `data/inbox/<assignment name>/`.
3. Files are processed in the background. The dashboard updates live and ranks submissions HIGH / MEDIUM / LOW.
4. Open a submission to see where its content came from, the signals with evidence, and side-by-side comparisons.
   Record your review as *reviewed*, *false positive* or *needs follow-up*.

Useful extras:

- **Boilerplate:** upload the assignment brief or starter code on the dashboard ("Assignment setup").
  Or click "Ignore everywhere" on a matched item. That content is then ignored for everyone.
- **Past cohorts:** upload them as *seed*. Seeds are compared against but never flagged.
- **Reference sources:** model answers or known online solutions.
- **Roster** (Settings): a CSV with `student_id,name,username,email`. With a roster, screenshots that show
  another student's name, ID, username or email are flagged.
- **Clusters:** groups of submissions that share distinctive content.
- **Calibrate:** score distributions with a suggested cutoff. Change thresholds in Settings, then Re-scan.
- **Export CSV** and **Print report** (from a submission page).

Content that most submissions share (such as the expected program output) gets little or no weight.
This keeps similar-but-honest work LOW.

## Front end

The web UI is a React Native app (Expo, running on react-native-web) in `checker/frontend/`. FastAPI serves its
build and a JSON API under `/api` (`checker/app/api.py`), which reuses the same grading and verification code
as the older server-rendered pages. Those pages are still there: they show when the build is missing, or with `?legacy=1`.

```bash
cd checker/frontend
npm install
npm run build        # writes checker/app/static/spa, which the server picks up on the next start
npm run dev          # development: starts the Python server and Expo with hot reload, open http://localhost:8081
```

Themes follow the PESUcoin design system (`src/theme`): light, dark, or system, from the icon in the top bar.

## Command line

```bash
uv run python -m checker.cli ingest path/to/pdfs --assignment HW1 [--roster roster.csv] [--seed]
uv run python -m checker.cli rescan HW1 [--all]
uv run python -m checker.cli boilerplate brief.pdf --assignment HW1
uv run python -m checker.cli calibrate HW1
uv run python -m checker.cli bench-ocr folder_of_pngs/
uv run python -m checker.cli synth tests/synth/out   # synthetic corpus with known copy cases
```

Data (database, stored images, settings overrides) lives in `data/`. Set `CHECKER_DATA_DIR` to change it.
Every setting can also be set as an environment variable, such as `CHECKER_OCR_ENGINE=tesseract`.

## Tests

```bash
uv run pytest                       # includes the synthetic-corpus test (a few minutes, runs OCR)
uv run pytest --ignore tests/test_corpus.py   # fast
```
