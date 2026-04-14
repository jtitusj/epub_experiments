from pathlib import Path
from zipfile import ZipFile

import pytest

from epub_experiments.audify import TextBlock
from epub_experiments.pdf_ingest import prepare_pdf_for_audify, split_pdf_into_chapters


def test_split_pdf_into_chapters_detects_headings() -> None:
    blocks = [
        TextBlock(kind="paragraph", text="Preface paragraph."),
        TextBlock(kind="heading", text="Chapter 1"),
        TextBlock(kind="paragraph", text="Alpha text."),
        TextBlock(kind="paragraph", text="Beta text."),
        TextBlock(kind="heading", text="Chapter 2"),
        TextBlock(kind="paragraph", text="Gamma text."),
    ]

    chapters = split_pdf_into_chapters(blocks)

    assert len(chapters) == 3
    assert chapters[0].title == "Opening"
    assert chapters[1].title == "Chapter 1"
    assert chapters[2].title == "Chapter 2"


def test_prepare_pdf_for_audify_falls_back_to_synthetic_chapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paragraph = " ".join(["word"] * 500)
    fake_blocks = [
        TextBlock(kind="paragraph", text=paragraph),
        TextBlock(kind="paragraph", text=paragraph),
        TextBlock(kind="paragraph", text=paragraph),
        TextBlock(kind="paragraph", text=paragraph),
    ]

    def fake_extract(_: Path) -> list[TextBlock]:
        return fake_blocks

    monkeypatch.setattr("epub_experiments.pdf_ingest.extract_pdf_text_blocks", fake_extract)

    output_epub = tmp_path / "synthetic.epub"
    out, parts = prepare_pdf_for_audify(
        input_pdf=tmp_path / "input.pdf",
        output_epub=output_epub,
        target_minutes=10,
        words_per_minute=150,
        title="Synthetic Book",
        author="Tester",
    )

    assert out == output_epub
    assert parts >= 2

    with ZipFile(output_epub, "r") as zin:
        names = set(zin.namelist())
        assert "OEBPS/content.opf" in names
        assert "OEBPS/toc.ncx" in names
        ncx = zin.read("OEBPS/toc.ncx").decode("utf-8")
        assert "Chapter 1" in ncx


def test_prepare_pdf_for_audify_creates_part_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chapter_text = " ".join(["Sentence one."] * 500)
    fake_blocks = [
        TextBlock(kind="heading", text="Chapter 1"),
        TextBlock(kind="paragraph", text=chapter_text),
    ]

    def fake_extract(_: Path) -> list[TextBlock]:
        return fake_blocks

    monkeypatch.setattr("epub_experiments.pdf_ingest.extract_pdf_text_blocks", fake_extract)

    output_epub = tmp_path / "parts.epub"
    _, parts = prepare_pdf_for_audify(
        input_pdf=tmp_path / "input.pdf",
        output_epub=output_epub,
        target_minutes=5,
        words_per_minute=120,
        title="Parts Book",
        author="Tester",
    )

    assert parts >= 2

    with ZipFile(output_epub, "r") as zin:
        ncx = zin.read("OEBPS/toc.ncx").decode("utf-8")
        assert "Chapter 1" in ncx
        assert "Part 1" in ncx
        assert "Part 2" in ncx
