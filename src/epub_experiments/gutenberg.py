from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.gutenberg.org"


@dataclass(frozen=True)
class EbookMetadata:
    ebook_id: int
    title: str
    author: str

    @property
    def stem(self) -> str:
        return f"{self.author} - {self.title}"


class GutenbergClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def fetch_ebook_page(self, ebook_id: int) -> str:
        url = f"{BASE_URL}/ebooks/{ebook_id}"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.text

    def parse_download_links(self, html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        links: dict[str, str] = {}

        for anchor in soup.select("a.link"):
            href = anchor.get("href")
            if not href:
                continue

            absolute = urljoin(BASE_URL, href)
            fmt = href.split(".")[-2:] if "." in href else [href]
            key = ".".join(fmt)
            links[key] = absolute

        return links

    def parse_ebook_metadata(self, html: str, ebook_id: int) -> EbookMetadata:
        soup = BeautifulSoup(html, "html.parser")

        title = ""
        author = ""

        title_tag = soup.select_one('[itemprop="headline"]')
        if title_tag:
            title = title_tag.get_text(" ", strip=True)

        creator_tag = soup.select_one('[itemprop="creator"] a') or soup.select_one('[itemprop="creator"]')
        if creator_tag:
            author = creator_tag.get_text(" ", strip=True)

        if not title and soup.title:
            title_text = soup.title.get_text(" ", strip=True)
            title = re.sub(r"\s*-\s*Project Gutenberg.*$", "", title_text, flags=re.IGNORECASE).strip()

        if not author and " by " in title:
            parts = title.split(" by ", maxsplit=1)
            title = parts[0].strip()
            author = parts[1].strip()

        if not title:
            title = f"Ebook {ebook_id}"
        if not author:
            author = "Unknown Author"

        return EbookMetadata(ebook_id=ebook_id, title=title, author=author)

    def best_epub_link(self, links: dict[str, str]) -> str:
        preferences = ["epub.images", "epub.noimages", "epub"]

        for pref in preferences:
            for key, url in links.items():
                if pref in key:
                    return url

        for key, url in links.items():
            if ".epub" in key:
                return url

        raise ValueError("No EPUB download link found.")

    def safe_component(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^\w\s\-.,'()]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip(" .")
        normalized = normalized.replace("/", "-")
        return normalized or "untitled"

    def metadata_filename(self, metadata: EbookMetadata, suffix: str) -> str:
        author = self.safe_component(metadata.author)
        title = self.safe_component(metadata.title)
        return f"{author} - {title}{suffix}"

    def parse_ebook_id(self, ebook: str) -> int:
        ebook = ebook.strip()
        if ebook.isdigit():
            return int(ebook)
        match = re.search(r"/ebooks/(\d+)", ebook)
        if not match:
            raise ValueError(f"Could not parse ebook id from: {ebook}")
        return int(match.group(1))

    def download_file(self, url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.session.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with destination.open("wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return destination

    def download_ebook_epub(self, ebook_id: int, output_dir: Path) -> Path:
        html = self.fetch_ebook_page(ebook_id)
        links = self.parse_download_links(html)
        epub_url = self.best_epub_link(links)
        metadata = self.parse_ebook_metadata(html, ebook_id)

        filename = self.metadata_filename(metadata, ".epub")

        destination = output_dir / filename
        return self.download_file(epub_url, destination)
