from epub_experiments.gutenberg import GutenbergClient


SAMPLE = """
<html>
  <head><title>Meditations by Marcus Aurelius - Project Gutenberg</title></head>
  <body>
    <table>
      <tr><td itemprop=\"headline\">Meditations</td></tr>
      <tr><td itemprop=\"creator\"><a>Marcus Aurelius</a></td></tr>
      <tr><td><a class=\"link\" href=\"/ebooks/2680.epub.images\">EPUB</a></td></tr>
    </table>
  </body>
</html>
"""


def test_parse_ebook_metadata_extracts_title_author() -> None:
    client = GutenbergClient()
    metadata = client.parse_ebook_metadata(SAMPLE, ebook_id=2680)

    assert metadata.title == "Meditations"
    assert metadata.author == "Marcus Aurelius"
    assert client.metadata_filename(metadata, ".audify.epub") == "Marcus Aurelius - Meditations.audify.epub"


def test_parse_ebook_id_from_url_and_digits() -> None:
    client = GutenbergClient()

    assert client.parse_ebook_id("2680") == 2680
    assert client.parse_ebook_id("https://www.gutenberg.org/ebooks/2680") == 2680
