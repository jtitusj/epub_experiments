from epub_experiments.audify import (
    TextBlock,
    apply_profile_filter,
    chunk_blocks,
    clean_tts_text,
    extract_text_blocks,
    render_ncx,
    split_into_chapters,
    ChunkEntry,
)


def test_clean_tts_text_removes_common_reference_noise() -> None:
    raw = "Hello [12] world (3) see https://example.com and [Footnote 7: note]."
    cleaned = clean_tts_text(raw)

    assert "[12]" not in cleaned
    assert "(3)" not in cleaned
    assert "https://" not in cleaned
    assert "Footnote" not in cleaned


def test_extract_text_blocks_skips_gutenberg_license_lines() -> None:
    html = """
    <html><body>
      <p>The Project Gutenberg eBook of Something</p>
      <h1>Chapter 1</h1>
      <p>This is normal readable text.</p>
    </body></html>
    """
    blocks = extract_text_blocks(html)

    assert len(blocks) == 2
    assert blocks[0].kind == "heading"
    assert "Chapter 1" in blocks[0].text


def test_chunk_blocks_splits_near_target_words() -> None:
    blocks = [TextBlock(kind="paragraph", text=("word " * 350).strip()) for _ in range(5)]
    chunks = chunk_blocks(blocks, target_words=700)

    assert len(chunks) >= 2
    assert sum(len(chunk) for chunk in chunks) == len(blocks)


def test_benjamin_franklin_profile_trims_to_author_start() -> None:
    blocks = [
        TextBlock(kind="heading", text="CONTENTS"),
        TextBlock(kind="paragraph", text="Ancestry and Early Life in Boston"),
        TextBlock(kind="heading", text="I"),
        TextBlock(kind="heading", text="ANCESTRY AND EARLY YOUTH IN BOSTON"),
        TextBlock(kind="paragraph", text="EAR SON: I have ever had pleasure in obtaining..."),
        TextBlock(kind="paragraph", text="I was born in Boston."),
    ]
    filtered = apply_profile_filter(blocks, profile="benjamin-franklin")

    assert filtered[0].text == "I"
    assert filtered[1].text == "ANCESTRY AND EARLY YOUTH IN BOSTON"
    assert "EAR SON" in filtered[2].text


def test_benjamin_franklin_profile_drops_dateline() -> None:
    blocks = [
        TextBlock(kind="heading", text="I"),
        TextBlock(kind="heading", text="ANCESTRY AND EARLY YOUTH IN BOSTON"),
        TextBlock(kind="paragraph", text="Twyford, at the Bishop of St. Asaph's, 1771."),
        TextBlock(kind="paragraph", text="DEAR SON: I have ever had pleasure..."),
    ]
    filtered = apply_profile_filter(blocks, profile="benjamin-franklin")

    assert all("Twyford" not in block.text for block in filtered)
    assert any("DEAR SON" in block.text for block in filtered)


def test_extract_text_blocks_restores_dropcap_letter() -> None:
    html = """
    <html><body>
      <p><img alt="block-d" src="block-d.jpg"/>EAR SON: I write to you.</p>
    </body></html>
    """
    blocks = extract_text_blocks(html)
    assert blocks[0].text.startswith("DEAR SON")


def test_split_into_chapters_uses_roman_headings() -> None:
    blocks = [
        TextBlock(kind="heading", text="I"),
        TextBlock(kind="heading", text="ANCESTRY AND EARLY YOUTH IN BOSTON"),
        TextBlock(kind="paragraph", text="DEAR SON: I have ever had pleasure..."),
        TextBlock(kind="heading", text="II"),
        TextBlock(kind="heading", text="BEGINNING LIFE AS A PRINTER"),
        TextBlock(kind="paragraph", text="FROM a child I was fond of reading..."),
    ]

    chapters = split_into_chapters(blocks)

    assert len(chapters) == 2
    assert chapters[0].title == "Chapter I: ANCESTRY AND EARLY YOUTH IN BOSTON"
    assert chapters[1].title == "Chapter II: BEGINNING LIFE AS A PRINTER"


def test_render_ncx_groups_chapter_parts() -> None:
    chunks = [
        ChunkEntry(
            item_id="audify-part-0001",
            rel_href="audify/part-0001.xhtml",
            full_path="OEBPS/audify/part-0001.xhtml",
            title="Chapter I: A - Part 1",
            chapter_title="Chapter I: A",
            part_number=1,
            content="",
        ),
        ChunkEntry(
            item_id="audify-part-0002",
            rel_href="audify/part-0002.xhtml",
            full_path="OEBPS/audify/part-0002.xhtml",
            title="Chapter I: A - Part 2",
            chapter_title="Chapter I: A",
            part_number=2,
            content="",
        ),
        ChunkEntry(
            item_id="audify-part-0003",
            rel_href="audify/part-0003.xhtml",
            full_path="OEBPS/audify/part-0003.xhtml",
            title="Chapter II: B",
            chapter_title="Chapter II: B",
            part_number=None,
            content="",
        ),
    ]
    ncx = render_ncx(book_title="Book", uid="uid-1", chunks=chunks).decode("utf-8")

    assert "Chapter I: A" in ncx
    assert "Part 1" in ncx
    assert "Part 2" in ncx
    assert "Chapter II: B" in ncx
