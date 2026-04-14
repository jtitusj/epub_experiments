# AGENTS.md

This file gives AI coding agents and CLI assistants project-specific guidance
(for example: Gemini CLI, Codex CLI, Claude Code, and similar tools).

## Project Summary

`epub_experiments` is a Python CLI project for transforming Project Gutenberg
EPUBs into listening-friendly editions for TTS playback.

Current scope:

1. Download EPUBs from Project Gutenberg.
2. Name raw and processed files from Gutenberg title/author metadata.
3. Clean EPUB text for smoother TTS playback.
4. Split long works into shorter listening parts.
5. Generate EPUB navigation that works well in reader apps.
6. Extract text from PDF books and generate chaptered EPUB output.

This repo is not the Android app project. Keep mobile app planning outside the
core direction of this repository.

## Working Rules

- Optimize for listening quality, not visual fidelity.
- Preserve chapter structure before splitting into subparts.
- Prefer Gutenberg title/author metadata for naming files.
- Remove front matter, editorial notes, references, and TTS-disruptive markup
  when they reduce listening quality.
- Keep processed EPUB navigation valid so users can jump by chapter and part.
- Default to the repo-local Conda environment for all commands.
- Prefer explicit cleanup profiles for edition-specific behavior instead of
  broad heuristics that may break other books.

## Developer Commands

Setup:
```bash
conda create -y -p ./.conda/epub-exp python=3.11
conda run -p ./.conda/epub-exp python -m pip install -e ".[dev]"
```

Activate:
```bash
conda activate ./.conda/epub-exp
```

Test:
```bash
conda run -p ./.conda/epub-exp pytest
```

Download from Gutenberg:
```bash
conda run -p ./.conda/epub-exp epub-exp download-gutenberg \
  --ebook-id 20203 \
  --output-dir data/raw
```

Prepare an existing EPUB for Audify-style playback:
```bash
conda run -p ./.conda/epub-exp epub-exp prepare-audify \
  --input-epub "data/raw/Benjamin Franklin - Autobiography of Benjamin Franklin.epub" \
  --output-epub "data/processed/Benjamin Franklin - Autobiography of Benjamin Franklin.audify.epub" \
  --target-minutes 10 \
  --words-per-minute 150 \
  --profile benjamin-franklin
```

Download and process in one step:
```bash
conda run -p ./.conda/epub-exp epub-exp process-gutenberg \
  --ebook https://www.gutenberg.org/ebooks/2680 \
  --raw-dir data/raw \
  --processed-dir data/processed \
  --target-minutes 10 \
  --words-per-minute 150
```

Prepare a PDF book as an Audify-style EPUB:
```bash
conda run -p ./.conda/epub-exp epub-exp prepare-pdf \
  --input-pdf "Project Mary Hail.pdf" \
  --output-epub "data/processed/Project Mary Hail.audify.epub" \
  --target-minutes 10 \
  --words-per-minute 150
```

## Current Architecture

```text
Project Gutenberg page
        |
        v
  gutenberg.py
  - parse ebook metadata
  - find best EPUB link
  - download source EPUB
        |
        v
  pdf_ingest.py (PDF input path)
  - extract text from PDF pages
  - remove repeated page noise
  - detect chapter headings
  - split chapters into subparts
  - build EPUB package + NCX
        |
        v
  audify.py
  - extract readable text
  - remove notes/front matter
  - restore drop caps
  - split by chapter and subpart
  - rebuild NCX/spine
        |
        v
  processed EPUB
  - TTS-friendly text
  - chapter navigation
  - short listening parts
```

## Profiles

Supported profiles:

- `general`: generic cleanup and chunking
- `benjamin-franklin`: extra cleanup for Gutenberg ebook `20203`

The Benjamin Franklin profile additionally:

- removes contents, illustrations, and editor introduction
- strips the opening dateline before the autobiography text
- restores drop-cap first letters such as `DEAR`
- segments by actual chapter headings before splitting into subparts

## Output Behavior

Processed EPUBs are rewritten to improve listening:

- long chapters are split into shorter parts based on
  `target_minutes * words_per_minute`
- chapter headings are preserved and used as navigation structure
- an NCX table of contents is generated so readers can jump by chapter and part
- common TTS-disrupting references and note markup are removed
- PDF chapter headings are detected when available; fallback synthetic chapters are used otherwise

## Next Milestones

1. Generalize cleanup heuristics across more Gutenberg books.
2. Add more edition-specific profiles where markup differs substantially.
3. Extract structured metadata and processing summaries for each book.
4. Add retry/throttling around Gutenberg fetches.
5. Add more regression fixtures from real EPUB inputs.

## Guidance For Future Agents

- Keep `README.md` user-facing and keep `AGENTS.md` repo-operational.
- When adding EPUB processing behavior, add regression tests for the exact
  source format that motivated the change.
- Prefer stable transformations that preserve valid EPUB structure over
  aggressive text mutation.
