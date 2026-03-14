from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from bs4 import BeautifulSoup
from bs4.element import Tag


HTML_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}
BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote")


@dataclass(frozen=True)
class TextBlock:
    kind: str
    text: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True)
class ChapterSection:
    title: str
    blocks: list[TextBlock]


@dataclass(frozen=True)
class ChunkSpec:
    chapter_title: str
    title: str
    blocks: list[TextBlock]
    part_number: int | None


@dataclass(frozen=True)
class ChunkEntry:
    item_id: str
    rel_href: str
    full_path: str
    title: str
    chapter_title: str
    part_number: int | None
    content: str


def clean_tts_text(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\bwww\.\S+", " ", text)
    text = re.sub(r"[†‡]", " ", text)
    text = re.sub(r"\((?:\d+|[ivxlcdm]+)\)", " ", text, flags=re.IGNORECASE)

    def bracket_filter(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        lowered = inner.lower()
        if re.fullmatch(r"\d+", inner):
            return " "
        noisy_tokens = ("footnote", "note", "illustration", "image", "fig", "plate")
        if any(token in lowered for token in noisy_tokens):
            return " "
        return match.group(0)

    text = re.sub(r"\[([^\]]{1,80})\]", bracket_filter, text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _is_noise_line(text: str) -> bool:
    lowered = text.lower()
    noise_snippets = (
        "project gutenberg",
        "gutenberg license",
        "start of the project gutenberg",
        "end of the project gutenberg",
        "this ebook is for the use of anyone",
    )
    return any(snippet in lowered for snippet in noise_snippets)


def _dropcap_letter(node: Tag) -> str | None:
    if node.name not in {"p", "li", "blockquote"}:
        return None

    first_img = node.find("img", recursive=False)
    if first_img is None:
        return None

    alt = first_img.get("alt", "") or ""
    src = first_img.get("src", "") or ""
    joined = f"{alt} {src}"

    match = re.search(r"block-([a-z])", joined, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def extract_text_blocks(html_content: str) -> list[TextBlock]:
    soup = BeautifulSoup(html_content, "html.parser")
    body = soup.body or soup

    # Remove common wrapper/content that causes TTS noise.
    for selector in (
        "div.footnote",
        ".footnote",
        ".pagenum",
        "#pg-header",
        "#pg-footer",
        ".pgheader",
        ".pgfooter",
    ):
        for tag in body.select(selector):
            tag.decompose()

    # Superscript and inline note anchors often force awkward TTS pauses.
    for tag in body.find_all(["sup"]):
        tag.decompose()
    for anchor in body.find_all("a"):
        href = anchor.get("href", "")
        cls = " ".join(anchor.get("class", []))
        if href.startswith("#") or "noteref" in cls:
            anchor.unwrap()

    blocks: list[TextBlock] = []
    for node in body.find_all(BLOCK_TAGS):
        text = clean_tts_text(node.get_text(" ", strip=True))
        dropcap = _dropcap_letter(node)
        if dropcap and text and not text.startswith(dropcap):
            text = f"{dropcap}{text}"
        if not text or _is_noise_line(text):
            continue

        kind = "heading" if node.name.startswith("h") else "paragraph"
        blocks.append(TextBlock(kind=kind, text=text))

    return blocks


def apply_profile_filter(blocks: list[TextBlock], profile: str) -> list[TextBlock]:
    if profile != "benjamin-franklin":
        return blocks

    start_idx: int | None = None
    for idx, block in enumerate(blocks):
        if re.search(r"\b(?:dear|ear)\s+son\b", block.text, flags=re.IGNORECASE):
            start_idx = idx
            break

    if start_idx is None:
        return blocks

    # Prefer the nearest chapter heading pair (Roman numeral + title) before the opening.
    story_start = start_idx
    chapter_pair_start: int | None = None
    for idx in range(0, start_idx - 1):
        if blocks[idx].kind != "heading":
            continue
        if not _is_roman_numeral(blocks[idx].text):
            continue
        if blocks[idx + 1].kind != "heading":
            continue
        chapter_pair_start = idx

    if chapter_pair_start is not None:
        story_start = chapter_pair_start
    else:
        # Fallback: keep heading run immediately before opening paragraph.
        cursor = start_idx - 1
        while cursor >= 0 and blocks[cursor].kind == "heading":
            cursor -= 1
        story_start = cursor + 1

    filtered = blocks[story_start:]

    cleaned: list[TextBlock] = []
    for block in filtered:
        lowered = block.text.lower()
        if "table of contents" in lowered or lowered == "contents":
            continue
        if "introduction" == lowered:
            continue
        if "illustrations" == lowered:
            continue
        if block.kind == "paragraph" and _looks_like_dateline(block.text):
            continue
        cleaned.append(block)

    return cleaned


def _looks_like_dateline(text: str) -> bool:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact.split()) > 20:
        return False
    if not re.search(r"\b(16|17|18|19|20)\d{2}\b", compact):
        return False
    if "," not in compact:
        return False
    alpha_words = re.findall(r"[A-Za-z][A-Za-z'.-]*", compact)
    if len(alpha_words) < 2:
        return False
    return True


def chunk_blocks(blocks: list[TextBlock], target_words: int) -> list[list[TextBlock]]:
    if not blocks:
        return []

    target_words = max(300, target_words)
    min_chunk_words = int(target_words * 0.6)

    chunks: list[list[TextBlock]] = []
    current: list[TextBlock] = []
    current_words = 0

    for block in blocks:
        if block.kind == "heading" and current_words >= min_chunk_words:
            chunks.append(current)
            current = []
            current_words = 0

        current.append(block)
        current_words += block.word_count

        if current_words >= target_words:
            chunks.append(current)
            current = []
            current_words = 0

    if current:
        chunks.append(current)

    return chunks


def _is_roman_numeral(text: str) -> bool:
    return bool(re.fullmatch(r"[IVXLCDM]+", text.strip(), flags=re.IGNORECASE))


def split_into_chapters(blocks: list[TextBlock]) -> list[ChapterSection]:
    if not blocks:
        return []

    starts: list[tuple[int, str]] = []
    idx = 0
    while idx < len(blocks):
        current = blocks[idx]
        if current.kind != "heading":
            idx += 1
            continue

        text = current.text.strip()
        next_block = blocks[idx + 1] if idx + 1 < len(blocks) else None
        if _is_roman_numeral(text) and next_block and next_block.kind == "heading":
            starts.append((idx, f"Chapter {text}: {next_block.text.strip()}"))
            idx += 2
            continue

        if re.match(r"(?i)^chapter\s+\w+", text):
            starts.append((idx, text))

        idx += 1

    if not starts:
        return [ChapterSection(title="Part", blocks=blocks)]

    sections: list[ChapterSection] = []
    if starts[0][0] > 0:
        sections.append(ChapterSection(title="Opening", blocks=blocks[: starts[0][0]]))

    for pos, (start_idx, title) in enumerate(starts):
        end_idx = starts[pos + 1][0] if pos + 1 < len(starts) else len(blocks)
        section_blocks = blocks[start_idx:end_idx]
        if section_blocks:
            sections.append(ChapterSection(title=title, blocks=section_blocks))

    return sections


def render_chunk_xhtml(book_title: str, section_title: str, blocks: list[TextBlock]) -> str:
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<html xmlns="http://www.w3.org/1999/xhtml">',
        "  <head>",
        f"    <title>{html.escape(book_title)} - {html.escape(section_title)}</title>",
        "  </head>",
        "  <body>",
        f"    <h2>{html.escape(section_title)}</h2>",
    ]

    for block in blocks:
        tag = "h3" if block.kind == "heading" else "p"
        lines.append(f"    <{tag}>{html.escape(block.text)}</{tag}>")

    lines += ["  </body>", "</html>"]
    return "\n".join(lines)


def _extract_book_uid(metadata_el: ET.Element | None) -> str:
    if metadata_el is None:
        return "audify-book"

    for child in list(metadata_el):
        if child.tag.endswith("identifier"):
            value = (child.text or "").strip()
            if value:
                return value
    return "audify-book"


def render_ncx(book_title: str, uid: str, chunks: list[ChunkEntry]) -> bytes:
    ns = "http://www.daisy.org/z3986/2005/ncx/"
    ncx = ET.Element("ncx", {"xmlns": ns, "version": "2005-1"})
    head = ET.SubElement(ncx, "head")
    ET.SubElement(head, "meta", {"name": "dtb:uid", "content": uid})
    ET.SubElement(head, "meta", {"name": "dtb:depth", "content": "2"})
    ET.SubElement(head, "meta", {"name": "dtb:totalPageCount", "content": "0"})
    ET.SubElement(head, "meta", {"name": "dtb:maxPageNumber", "content": "0"})

    doc_title = ET.SubElement(ncx, "docTitle")
    ET.SubElement(doc_title, "text").text = book_title
    nav_map = ET.SubElement(ncx, "navMap")

    chapter_groups: dict[str, list[ChunkEntry]] = {}
    for chunk in chunks:
        chapter_groups.setdefault(chunk.chapter_title, []).append(chunk)

    play_order = 1
    nav_index = 1
    for chapter_title, items in chapter_groups.items():
        if len(items) == 1:
            nav = ET.SubElement(
                nav_map, "navPoint", {"id": f"navPoint-{nav_index}", "playOrder": str(play_order)}
            )
            nav_index += 1
            play_order += 1
            nav_label = ET.SubElement(nav, "navLabel")
            ET.SubElement(nav_label, "text").text = chapter_title
            ET.SubElement(nav, "content", {"src": items[0].rel_href})
            continue

        parent = ET.SubElement(
            nav_map, "navPoint", {"id": f"navPoint-{nav_index}", "playOrder": str(play_order)}
        )
        nav_index += 1
        play_order += 1
        parent_label = ET.SubElement(parent, "navLabel")
        ET.SubElement(parent_label, "text").text = chapter_title
        ET.SubElement(parent, "content", {"src": items[0].rel_href})

        for item in items:
            child = ET.SubElement(
                parent, "navPoint", {"id": f"navPoint-{nav_index}", "playOrder": str(play_order)}
            )
            nav_index += 1
            play_order += 1
            child_label = ET.SubElement(child, "navLabel")
            label = f"Part {item.part_number}" if item.part_number is not None else item.title
            ET.SubElement(child_label, "text").text = label
            ET.SubElement(child, "content", {"src": item.rel_href})

    return ET.tostring(ncx, encoding="utf-8", xml_declaration=True)


def _namespace_uri(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1 : tag.find("}")]
    return ""


def _qname(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}" if ns else local


def _posix_join(base_dir: str, rel_path: str) -> str:
    if not base_dir:
        return str(PurePosixPath(rel_path))
    return str(PurePosixPath(base_dir) / PurePosixPath(rel_path))


def _relative_to(base_dir: str, full_path: str) -> str:
    if not base_dir:
        return str(PurePosixPath(full_path))
    return str(PurePosixPath(full_path).relative_to(PurePosixPath(base_dir)))


def _extract_book_title(metadata_el: ET.Element | None, ns: str) -> str:
    if metadata_el is None:
        return "Book"

    title_el = None
    for child in list(metadata_el):
        if child.tag.endswith("title") and (child.text or "").strip():
            title_el = child
            break

    if title_el is None:
        return "Book"
    return (title_el.text or "Book").strip()


def prepare_epub_for_audify(
    input_epub: Path,
    output_epub: Path,
    *,
    target_minutes: int = 10,
    words_per_minute: int = 150,
    profile: str = "general",
) -> tuple[Path, int]:
    if not input_epub.exists():
        raise FileNotFoundError(f"Input EPUB not found: {input_epub}")

    with ZipFile(input_epub, "r") as zin:
        names = zin.namelist()
        if "META-INF/container.xml" not in names:
            raise ValueError("Invalid EPUB: missing META-INF/container.xml")

        container_xml = zin.read("META-INF/container.xml")
        container_root = ET.fromstring(container_xml)
        container_ns = _namespace_uri(container_root.tag)
        rootfile_el = container_root.find(f".//{_qname(container_ns, 'rootfile')}")
        if rootfile_el is None:
            raise ValueError("Invalid EPUB: no rootfile entry in container.xml")

        opf_path = rootfile_el.attrib.get("full-path")
        if not opf_path:
            raise ValueError("Invalid EPUB: rootfile missing full-path")

        opf_xml = zin.read(opf_path)
        opf_root = ET.fromstring(opf_xml)
        opf_ns = _namespace_uri(opf_root.tag)
        manifest_el = opf_root.find(_qname(opf_ns, "manifest"))
        spine_el = opf_root.find(_qname(opf_ns, "spine"))
        metadata_el = opf_root.find(_qname(opf_ns, "metadata"))

        if manifest_el is None or spine_el is None:
            raise ValueError("Invalid EPUB: OPF missing manifest/spine")

        opf_dir = str(PurePosixPath(opf_path).parent)
        if opf_dir == ".":
            opf_dir = ""

        manifest_items: dict[str, ET.Element] = {}
        for item in list(manifest_el):
            item_id = item.attrib.get("id")
            if item_id:
                manifest_items[item_id] = item

        ordered_blocks: list[TextBlock] = []
        for itemref in list(spine_el):
            item_id = itemref.attrib.get("idref")
            if not item_id:
                continue
            item = manifest_items.get(item_id)
            if item is None:
                continue
            media_type = item.attrib.get("media-type", "")
            if media_type not in HTML_MEDIA_TYPES:
                continue

            href = item.attrib.get("href")
            if not href:
                continue
            doc_path = _posix_join(opf_dir, href)
            if doc_path not in names:
                continue

            blocks = extract_text_blocks(zin.read(doc_path).decode("utf-8", errors="ignore"))
            if not blocks:
                continue

            ordered_blocks.extend(blocks)

        if not ordered_blocks:
            raise ValueError("No readable text blocks found in EPUB spine documents.")

        ordered_blocks = apply_profile_filter(ordered_blocks, profile=profile)
        if not ordered_blocks:
            raise ValueError("No content left after applying profile filter.")

        target_words = max(300, target_minutes * words_per_minute)
        chapter_sections = split_into_chapters(ordered_blocks)
        if not chapter_sections:
            raise ValueError("Failed to split EPUB into chunks.")

        title = _extract_book_title(metadata_el, opf_ns)
        uid = _extract_book_uid(metadata_el)
        chunk_specs: list[ChunkSpec] = []
        for chapter in chapter_sections:
            chapter_chunks = chunk_blocks(chapter.blocks, target_words=target_words)
            if not chapter_chunks:
                continue
            if len(chapter_chunks) == 1:
                chunk_specs.append(
                    ChunkSpec(
                        chapter_title=chapter.title,
                        title=chapter.title,
                        blocks=chapter_chunks[0],
                        part_number=None,
                    )
                )
                continue

            for sub_idx, chapter_chunk in enumerate(chapter_chunks, start=1):
                chunk_title = f"{chapter.title} - Part {sub_idx}"
                chunk_specs.append(
                    ChunkSpec(
                        chapter_title=chapter.title,
                        title=chunk_title,
                        blocks=chapter_chunk,
                        part_number=sub_idx,
                    )
                )

        if not chunk_specs:
            raise ValueError("Failed to split EPUB into chunks.")

        chunk_entries: list[ChunkEntry] = []
        for idx, spec in enumerate(chunk_specs, start=1):
            item_id = f"audify-part-{idx:04d}"
            rel_href = f"audify/part-{idx:04d}.xhtml"
            full_path = _posix_join(opf_dir, rel_href)
            content = render_chunk_xhtml(book_title=title, section_title=spec.title, blocks=spec.blocks)
            chunk_entries.append(
                ChunkEntry(
                    item_id=item_id,
                    rel_href=rel_href,
                    full_path=full_path,
                    title=spec.title,
                    chapter_title=spec.chapter_title,
                    part_number=spec.part_number,
                    content=content,
                )
            )

        for itemref in list(spine_el):
            spine_el.remove(itemref)
        for chunk in chunk_entries:
            new_itemref = ET.Element(_qname(opf_ns, "itemref"))
            new_itemref.set("idref", chunk.item_id)
            spine_el.append(new_itemref)

        for chunk in chunk_entries:
            new_item = ET.Element(_qname(opf_ns, "item"))
            new_item.set("id", chunk.item_id)
            new_item.set("href", _relative_to(opf_dir, chunk.full_path))
            new_item.set("media-type", "application/xhtml+xml")
            manifest_el.append(new_item)

        ncx_item: ET.Element | None = None
        ncx_item_id: str | None = None
        ncx_path: str | None = None
        for item in list(manifest_el):
            if item.attrib.get("media-type") == "application/x-dtbncx+xml":
                ncx_item = item
                ncx_item_id = item.attrib.get("id")
                href = item.attrib.get("href")
                if href:
                    ncx_path = _posix_join(opf_dir, href)
                break

        if ncx_item is None or not ncx_item_id or not ncx_path:
            ncx_item_id = "audify-ncx"
            ncx_rel_href = "audify-toc.ncx"
            ncx_path = _posix_join(opf_dir, ncx_rel_href)
            ncx_item = ET.Element(_qname(opf_ns, "item"))
            ncx_item.set("id", ncx_item_id)
            ncx_item.set("href", ncx_rel_href)
            ncx_item.set("media-type", "application/x-dtbncx+xml")
            manifest_el.append(ncx_item)

        spine_el.set("toc", ncx_item_id)
        updated_ncx = render_ncx(book_title=title, uid=uid, chunks=chunk_entries)
        updated_opf = ET.tostring(opf_root, encoding="utf-8", xml_declaration=True)

        output_epub.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output_epub, "w") as zout:
            if "mimetype" in names:
                zout.writestr("mimetype", zin.read("mimetype"), compress_type=ZIP_STORED)
            else:
                zout.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)

            skip_names = {"mimetype", opf_path, ncx_path}
            for name in names:
                if name in skip_names:
                    continue
                zout.writestr(name, zin.read(name), compress_type=ZIP_DEFLATED)

            zout.writestr(opf_path, updated_opf, compress_type=ZIP_DEFLATED)
            zout.writestr(ncx_path, updated_ncx, compress_type=ZIP_DEFLATED)
            for chunk in chunk_entries:
                zout.writestr(chunk.full_path, chunk.content.encode("utf-8"), compress_type=ZIP_DEFLATED)

    return output_epub, len(chunk_specs)
