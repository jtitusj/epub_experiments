# PDF Processing Plan

This document describes how `epub_experiments` should process a source PDF book into a listening-friendly EPUB with chapter and subchapter navigation.

## Goal

Add a PDF ingestion path that:

1. reads text from a PDF book,
2. detects chapter boundaries,
3. splits long chapters into smaller daily-read parts,
4. builds a valid EPUB with NCX navigation by chapter and part.

## Scope

In scope:

- text-based PDF extraction (non-OCR)
- chapter detection from extracted text patterns
- chunking chapters into target-size subchapters
- EPUB generation with spine + NCX
- CLI command and tests

Out of scope for initial release:

- OCR for scanned/image-only PDFs
- advanced layout recovery for highly stylized PDFs
- language-specific chapter models

## Pipeline

```text
Input PDF
   |
   v
pdf_ingest.py
- extract text page-by-page
- normalize whitespace
- remove repeated headers/footers and page-noise lines
   |
   v
chapter detection
- detect headings (e.g. CHAPTER 1, Chapter One, Roman numeral styles)
- fallback to synthetic chaptering when headings are absent
   |
   v
subchapter splitter
- compute target words = target_minutes * words_per_minute
- split chapter paragraphs into Part 1..N
   |
   v
EPUB builder
- render XHTML parts
- generate OPF manifest/spine
- generate NCX grouped by chapter with child parts
   |
   v
Output EPUB
```

## CLI Contract

Add command:

```bash
conda run -p ./.conda/epub-exp epub-exp prepare-pdf \
  --input-pdf "Project Mary Hail.pdf" \
  --output-epub "data/processed/Project Mary Hail.audify.epub" \
  --target-minutes 10 \
  --words-per-minute 150
```

Arguments:

- `--input-pdf` (required): source PDF path
- `--output-epub` (required): output EPUB path
- `--title` (optional): override inferred title
- `--author` (optional): override inferred author, default `Unknown`
- `--target-minutes` (optional): desired minutes per part, default `10`
- `--words-per-minute` (optional): reading speed estimate, default `150`

## Text Extraction and Cleanup

Extraction:

- use `pypdf` to extract text per page
- preserve page order

Cleanup:

- normalize newlines and spaces
- strip empty lines and page-number-only lines
- detect repeated line patterns at page boundaries and remove them as potential headers/footers
- keep cleanup conservative to avoid dropping narrative text

## Chapter Detection

Primary heading patterns:

- `^chapter\s+\d+` (case-insensitive)
- `^chapter\s+[ivxlcdm]+$` (Roman numerals)
- `^chapter\s+[a-z-]+$` (spelled-out numbers)
- optional uppercase forms

Rules:

- heading starts a new chapter
- heading line becomes chapter title
- paragraph text until next heading belongs to the chapter

Fallback:

- if no headings found, split into synthetic chapters by word budget
- title synthetic chapters as `Chapter 1`, `Chapter 2`, ...

## Subchapter Chunking

- Compute `target_words = max(300, target_minutes * words_per_minute)`
- Chunk chapter paragraphs while preserving paragraph boundaries
- Prefer boundaries near heading transitions or paragraph edges
- Name single chunk as chapter title only
- Name multiple chunks as `<Chapter Title> - Part N`

## EPUB Construction

- Build EPUB2-compatible package:
- `mimetype`
- `META-INF/container.xml`
- `OEBPS/content.opf`
- `OEBPS/toc.ncx`
- `OEBPS/text/*.xhtml`

Metadata:

- use CLI-provided `title`/`author` when provided
- otherwise infer title from PDF stem and set author to `Unknown`

Navigation:

- NCX parent node per chapter
- child nodes for each part where chapter has multiple parts

## Testing Plan

Add tests for:

- chapter heading detection from normalized lines
- fallback synthetic chapters when headings are absent
- chunking behavior and `Part N` naming
- successful EPUB creation with expected chapter/part count and NCX entries

Use text fixtures and small generated PDFs where needed to keep tests deterministic.

## Risks and Mitigations

Risk: mixed formatting may produce weak chapter detection.
Mitigation: conservative regex + fallback synthetic chaptering.

Risk: repeated headers/footers may leak into output.
Mitigation: remove only high-confidence repeated boundary lines.

Risk: scanned PDFs return little or no text.
Mitigation: fail fast with clear error and note OCR is not yet supported.

## Completion Criteria

The feature is complete when:

1. `prepare-pdf` command creates a valid EPUB from a text PDF,
2. chapters are navigable in NCX,
3. long chapters are split into daily-read parts,
4. tests pass for the new PDF pipeline,
5. `README.md` and `AGENTS.md` are updated with usage and architecture notes.
