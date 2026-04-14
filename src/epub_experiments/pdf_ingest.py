from __future__ import annotations

import html
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from .audify import ChunkEntry, TextBlock, chunk_blocks, render_chunk_xhtml, render_ncx


CHAPTER_HEADING_PATTERNS = (
    re.compile(r"^chapter\s+\d+[\w\-:.]*$", flags=re.IGNORECASE),
    re.compile(r"^chapter\s+[ivxlcdm]+[\w\-:.]*$", flags=re.IGNORECASE),
    re.compile(r"^chapter\s+[a-z][a-z\-\s]*$", flags=re.IGNORECASE),
)


@dataclass(frozen=True)
class PdfChapter:
    title: str
    blocks: list[TextBlock]


@dataclass(frozen=True)
class _BoundaryNoise:
    repeated_first_lines: set[str]
    repeated_last_lines: set[str]


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _is_page_number_line(text: str) -> bool:
    compact = text.strip()
    if not compact:
        return False

    if re.fullmatch(r"\d{1,5}", compact):
        return True
    if re.fullmatch(r"(?:page\s+)?\d{1,5}(?:\s+of\s+\d{1,5})?", compact, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"[ivxlcdm]{1,12}", compact, flags=re.IGNORECASE):
        return True
    return False


def _scan_boundary_noise(pages: list[list[str]]) -> _BoundaryNoise:
    first_counter: Counter[str] = Counter()
    last_counter: Counter[str] = Counter()

    for lines in pages:
        non_empty = [line for line in lines if line]
        if not non_empty:
            continue
        first_counter[non_empty[0]] += 1
        last_counter[non_empty[-1]] += 1

    repeated_first_lines = {line for line, count in first_counter.items() if count >= 3}
    repeated_last_lines = {line for line, count in last_counter.items() if count >= 3}
    return _BoundaryNoise(
        repeated_first_lines=repeated_first_lines,
        repeated_last_lines=repeated_last_lines,
    )


def _is_chapter_heading(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return any(pattern.fullmatch(stripped) for pattern in CHAPTER_HEADING_PATTERNS)


def _format_chapter_title(text: str) -> str:
    compact = _normalize_line(text)
    if not compact:
        return "Chapter"

    if compact.isupper():
        return compact.title()

    return compact


def _build_blocks(lines: list[str]) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    current: str | None = None

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if current:
                blocks.append(TextBlock(kind="paragraph", text=current.strip()))
                current = None
            continue

        if _is_chapter_heading(stripped):
            if current:
                blocks.append(TextBlock(kind="paragraph", text=current.strip()))
                current = None
            blocks.append(TextBlock(kind="heading", text=_format_chapter_title(stripped)))
            continue

        if current is None:
            current = stripped
            continue

        if current.endswith("-"):
            current = f"{current[:-1]}{stripped}"
            continue

        current = f"{current} {stripped}"

    if current:
        blocks.append(TextBlock(kind="paragraph", text=current.strip()))

    return blocks


def split_pdf_into_chapters(blocks: list[TextBlock]) -> list[PdfChapter]:
    if not blocks:
        return []

    starts = [idx for idx, block in enumerate(blocks) if block.kind == "heading"]
    if not starts:
        return []

    chapters: list[PdfChapter] = []
    if starts[0] > 0:
        opening_blocks = [block for block in blocks[: starts[0]] if block.kind == "paragraph"]
        if opening_blocks:
            chapters.append(PdfChapter(title="Opening", blocks=opening_blocks))

    for pos, start_idx in enumerate(starts):
        end_idx = starts[pos + 1] if pos + 1 < len(starts) else len(blocks)
        heading = blocks[start_idx].text
        chapter_blocks = [block for block in blocks[start_idx + 1 : end_idx] if block.kind == "paragraph"]

        if not chapter_blocks:
            continue

        chapters.append(PdfChapter(title=heading, blocks=chapter_blocks))

    return chapters


def _synthetic_chapters_from_paragraphs(
    paragraph_blocks: list[TextBlock], target_words: int
) -> list[PdfChapter]:
    chunks = chunk_blocks(paragraph_blocks, target_words=target_words)
    chapters: list[PdfChapter] = []
    for idx, chunk in enumerate(chunks, start=1):
        chapters.append(PdfChapter(title=f"Chapter {idx}", blocks=chunk))
    return chapters


def _split_large_paragraph_blocks(blocks: list[TextBlock], target_words: int) -> list[TextBlock]:
    adjusted: list[TextBlock] = []

    for block in blocks:
        if block.kind != "paragraph" or block.word_count <= int(target_words * 1.3):
            adjusted.append(block)
            continue

        sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", block.text) if segment.strip()]
        if len(sentences) <= 1:
            words = block.text.split()
            cursor = 0
            while cursor < len(words):
                chunk_words = words[cursor : cursor + target_words]
                adjusted.append(TextBlock(kind="paragraph", text=" ".join(chunk_words)))
                cursor += target_words
            continue

        current: list[str] = []
        current_words = 0
        for sentence in sentences:
            sentence_words = len(sentence.split())
            if current and current_words + sentence_words > target_words:
                adjusted.append(TextBlock(kind="paragraph", text=" ".join(current)))
                current = []
                current_words = 0
            current.append(sentence)
            current_words += sentence_words

        if current:
            adjusted.append(TextBlock(kind="paragraph", text=" ".join(current)))

    return adjusted


def extract_pdf_text_blocks(input_pdf: Path) -> list[TextBlock]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'pypdf'. Install project dependencies before running prepare-pdf."
        ) from exc

    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    reader = PdfReader(str(input_pdf))
    raw_pages: list[list[str]] = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        lines = [_normalize_line(line) for line in page_text.splitlines()]
        raw_pages.append(lines)

    if not raw_pages:
        return []

    noise = _scan_boundary_noise(raw_pages)
    filtered_lines: list[str] = []

    for lines in raw_pages:
        if not lines:
            continue

        non_empty = [line for line in lines if line]
        first_line = non_empty[0] if non_empty else None
        last_line = non_empty[-1] if non_empty else None

        for line in lines:
            if not line:
                filtered_lines.append("")
                continue
            if _is_page_number_line(line):
                continue
            if first_line and line == first_line and line in noise.repeated_first_lines:
                continue
            if last_line and line == last_line and line in noise.repeated_last_lines:
                continue
            filtered_lines.append(line)

    return _build_blocks(filtered_lines)


def prepare_pdf_for_audify(
    input_pdf: Path,
    output_epub: Path,
    *,
    target_minutes: int = 10,
    words_per_minute: int = 150,
    title: str | None = None,
    author: str = "Unknown",
) -> tuple[Path, int]:
    blocks = extract_pdf_text_blocks(input_pdf)
    if not blocks:
        raise ValueError("No readable text extracted from PDF. The file may be image-based (OCR not yet supported).")

    target_words = max(300, target_minutes * words_per_minute)
    chapters = split_pdf_into_chapters(blocks)

    if not chapters:
        paragraph_blocks = [block for block in blocks if block.kind == "paragraph"]
        chapters = _synthetic_chapters_from_paragraphs(paragraph_blocks, target_words=target_words)

    if not chapters:
        raise ValueError("No chapter content could be derived from PDF text.")

    book_title = title.strip() if title else input_pdf.stem
    book_author = author.strip() if author else "Unknown"
    uid = str(uuid.uuid4())

    chunk_entries: list[ChunkEntry] = []
    chunk_count = 0

    for chapter in chapters:
        chapter_blocks = _split_large_paragraph_blocks(chapter.blocks, target_words=target_words)
        chapter_chunks = chunk_blocks(chapter_blocks, target_words=target_words)
        if not chapter_chunks:
            continue

        if len(chapter_chunks) == 1:
            chunk_count += 1
            item_id = f"pdf-part-{chunk_count:04d}"
            rel_href = f"text/part-{chunk_count:04d}.xhtml"
            full_path = f"OEBPS/{rel_href}"
            content = render_chunk_xhtml(book_title=book_title, section_title=chapter.title, blocks=chapter_chunks[0])
            chunk_entries.append(
                ChunkEntry(
                    item_id=item_id,
                    rel_href=rel_href,
                    full_path=full_path,
                    title=chapter.title,
                    chapter_title=chapter.title,
                    part_number=None,
                    content=content,
                )
            )
            continue

        for part_number, chapter_chunk in enumerate(chapter_chunks, start=1):
            chunk_count += 1
            part_title = f"{chapter.title} - Part {part_number}"
            item_id = f"pdf-part-{chunk_count:04d}"
            rel_href = f"text/part-{chunk_count:04d}.xhtml"
            full_path = f"OEBPS/{rel_href}"
            content = render_chunk_xhtml(
                book_title=book_title,
                section_title=part_title,
                blocks=chapter_chunk,
            )
            chunk_entries.append(
                ChunkEntry(
                    item_id=item_id,
                    rel_href=rel_href,
                    full_path=full_path,
                    title=part_title,
                    chapter_title=chapter.title,
                    part_number=part_number,
                    content=content,
                )
            )

    if not chunk_entries:
        raise ValueError("Failed to split PDF content into EPUB parts.")

    output_epub.parent.mkdir(parents=True, exist_ok=True)

    manifest_lines = []
    spine_lines = []
    for chunk in chunk_entries:
        manifest_lines.append(
            f'    <item id="{chunk.item_id}" href="{chunk.rel_href}" media-type="application/xhtml+xml"/>'
        )
        spine_lines.append(f'    <itemref idref="{chunk.item_id}"/>')

    manifest_lines.append('    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    manifest_xml = "\n".join(manifest_lines)
    spine_xml = "\n".join(spine_lines)

    opf_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{html.escape(book_title)}</dc:title>
    <dc:creator>{html.escape(book_author)}</dc:creator>
    <dc:identifier id="bookid">{uid}</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
{manifest_xml}
  </manifest>
  <spine toc="ncx">
{spine_xml}
  </spine>
</package>"""

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    ncx_content = render_ncx(book_title=book_title, uid=uid, chunks=chunk_entries)

    with ZipFile(output_epub, "w") as zout:
        zout.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)
        zout.writestr("META-INF/container.xml", container_xml.encode("utf-8"), compress_type=ZIP_DEFLATED)
        zout.writestr("OEBPS/content.opf", opf_content.encode("utf-8"), compress_type=ZIP_DEFLATED)
        zout.writestr("OEBPS/toc.ncx", ncx_content, compress_type=ZIP_DEFLATED)

        for chunk in chunk_entries:
            zout.writestr(chunk.full_path, chunk.content.encode("utf-8"), compress_type=ZIP_DEFLATED)

    return output_epub, len(chunk_entries)
