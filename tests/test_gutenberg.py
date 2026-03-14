from pathlib import Path

from epub_experiments.gutenberg import GutenbergClient


def test_parse_download_links_extracts_link_hrefs() -> None:
    html = Path("tests/fixtures/gutenberg_20203_sample.html").read_text()
    client = GutenbergClient()

    links = client.parse_download_links(html)

    assert "epub.images" in links
    assert links["epub.images"].endswith("/ebooks/20203.epub.images")


def test_best_epub_link_prefers_images() -> None:
    client = GutenbergClient()
    links = {
        "epub.noimages": "https://www.gutenberg.org/ebooks/20203.epub.noimages",
        "epub.images": "https://www.gutenberg.org/ebooks/20203.epub.images",
    }

    chosen = client.best_epub_link(links)

    assert chosen.endswith("epub.images")
