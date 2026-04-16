# EPUB Experiments

Python CLI tools for downloading EPUBs from Project Gutenberg and rewriting them into Audify-friendly listening editions.

## Current Scope

The project currently supports:

- downloading a Gutenberg EPUB
- naming downloaded and processed files from Gutenberg title/author metadata
- cleaning TTS-unfriendly content such as notes, references, and boilerplate
- splitting long books into shorter listening parts
- generating EPUB navigation/TOC entries for Audify
- extracting text from PDF books and creating chaptered EPUB output

Validated examples:

- Benjamin Franklin: `https://www.gutenberg.org/ebooks/20203`
- Marcus Aurelius: `https://www.gutenberg.org/ebooks/2680`

## Project Layout

- `src/epub_experiments/gutenberg.py`: Gutenberg page parsing, metadata extraction, and EPUB download
- `src/epub_experiments/audify.py`: EPUB cleanup, chunking, and TOC generation
- `src/epub_experiments/pdf_ingest.py`: PDF text extraction, chapter detection, and EPUB creation
- `src/epub_experiments/cli.py`: command-line entrypoint
- `data/raw/`: downloaded source EPUBs
- `data/processed/`: Audify-ready output EPUBs

## Setup

This repo is set up to use a repo-local Conda environment:

```bash
conda create -y -p ./.conda/epub-exp python=3.11
conda run -p ./.conda/epub-exp python -m pip install -e ".[dev]"
```

Activate it:

```bash
conda activate ./.conda/epub-exp
```

Or run commands without activating:

```bash
conda run -p ./.conda/epub-exp <command>
```

## Commands

Run tests:

```bash
conda run -p ./.conda/epub-exp pytest
```

Download an EPUB from Gutenberg:

```bash
conda run -p ./.conda/epub-exp epub-exp download-gutenberg \
  --ebook-id 20203 \
  --output-dir data/raw
```

This now uses Gutenberg metadata for the filename. Example output:

```text
data/raw/Benjamin Franklin - Autobiography of Benjamin Franklin.epub
```

Prepare an existing EPUB for Audify:

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

Example processed output:

```text
data/processed/Marcus Aurelius, Emperor of Rome, 121-180 - Meditations.audify.epub
```

Prepare a PDF for Audify:

```bash
conda run -p ./.conda/epub-exp epub-exp prepare-pdf \
  --input-pdf "test.pdf" \
  --output-epub "data/processed/test.epub" \
  --target-minutes 10 \
  --words-per-minute 150
```

## Profiles

`prepare-audify` and `process-gutenberg` support:

- `general`: generic cleanup and chunking
- `benjamin-franklin`: extra cleanup for Gutenberg ebook `20203`

The Benjamin Franklin profile additionally:

- removes front matter such as contents, illustrations, and editor introduction
- strips the opening dateline before the autobiography text
- restores drop-cap first letters such as `DEAR` from Gutenberg image-based initials
- segments by real chapter headings before splitting into subparts

## Output Behavior

Processed EPUBs are rewritten to improve listening:

- long chapters are split into shorter parts based on `target_minutes * words_per_minute`
- chapter headings are preserved and used as navigation structure
- an NCX table of contents is generated so Audify can jump by chapter and part
- common TTS-disrupting references and note markup are removed
- PDF chapter boundaries prefer embedded PDF outline/bookmark entries (for example `Chapter 1`, `Chapter 2`, ...)
- PDF front matter (for example contents pages) and back matter (for example dedication/author pages after the last chapter) are trimmed when detectable
- PDF extraction normalizes control characters/ligatures and repairs common split-word artifacts from glyph spacing
- PDF paragraph spacing is preserved with line-merge heuristics so dialogue/narrative breaks are retained better
- if no reliable chapter boundaries are available, synthetic chapter splits are generated
- non-text/image-only PDFs currently require OCR support (not yet implemented)

## Notes

- Project Gutenberg markup varies by book, so the generic path is intentionally conservative.
- The Franklin-specific cleanup is explicit because that edition contains editor material and annotation markup mixed into the reading flow.
- PDF extraction is conservative and removes only high-confidence repeated page headers/footers plus common ebook-export footer noise lines.
- Respect Project Gutenberg's Terms of Use when downloading and redistributing files.
