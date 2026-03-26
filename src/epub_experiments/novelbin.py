import json
import re
import time
import uuid
import html
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import requests
from bs4 import BeautifulSoup

from .audify import TextBlock, ChunkEntry, render_chunk_xhtml, render_ncx

@dataclass(frozen=True)
class NovelChapter:
    title: str
    paragraphs: list[str]
    url: str
    next_url: str | None

class NovelBinClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def fetch_chapter(self, url: str) -> NovelChapter:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        content_div = soup.find("div", id="chr-content") or soup.find("div", class_="chr-content")
        if not content_div:
            raise ValueError(f"Could not find chapter content at {url}")
        
        # Remove noisy elements
        for noise in content_div(["script", "style", "div"]):
            classes = noise.get('class') or []
            if any(c in classes for c in ['ads', 'ads-holder', 'ads-content']) or \
               'ads' in (noise.get('id') or ''):
                noise.decompose()

        paragraphs = []
        for p in content_div.find_all("p"):
            text = p.get_text(strip=True)
            if text:
                # Basic cleaning
                text = text.replace("\xa0", " ")
                paragraphs.append(text)
                
        if not paragraphs:
            raise ValueError(f"No text content found in chapter at {url}")
            
        # Per user instruction: "the first sentence represents the title of the chapter"
        # In our scrape, paragraphs[0] is that first sentence/line.
        title = paragraphs[0]
        content_paragraphs = paragraphs[1:]
        
        next_link = soup.find("a", id="next_chap")
        next_url = next_link["href"] if next_link and next_link.get("href") else None
        if next_url and not next_url.startswith("http"):
            next_url = urljoin(url, next_url)
            
        return NovelChapter(
            title=title,
            paragraphs=content_paragraphs,
            url=url,
            next_url=next_url
        )

    def scrape_all_chapters(
        self, 
        start_url: str, 
        save_dir: Path | None = None,
        max_chapters: int | None = None
    ) -> list[NovelChapter]:
        chapters = []
        current_url = start_url
        
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            # Try to resume from the last saved chapter
            saved_files = sorted(save_dir.glob("chapter_*.json"))
            if saved_files:
                last_file = saved_files[-1]
                with open(last_file, "r") as f:
                    last_data = json.load(f)
                    last_chap = NovelChapter(**last_data)
                    print(f"Resuming from {last_chap.next_url} (last saved: {last_chap.title})")
                    current_url = last_chap.next_url
                    # We don't add existing chapters to the list here; we'll load them all at the end
        
        count = 0
        while current_url:
            print(f"Scraping {current_url}...")
            try:
                chapter = self.fetch_chapter(current_url)
                
                if save_dir:
                    chapter_idx = len(list(save_dir.glob("chapter_*.json"))) + 1
                    save_path = save_dir / f"chapter_{chapter_idx:04d}.json"
                    with open(save_path, "w") as f:
                        json.dump(asdict(chapter), f, indent=2)
                
                chapters.append(chapter)
                count += 1
            except Exception as e:
                print(f"Error scraping {current_url}: {e}")
                break
            
            if max_chapters and count >= max_chapters:
                break
                
            current_url = chapter.next_url
            if current_url:
                # Respectful delay
                time.sleep(1)
                
        return chapters

def load_chapters_from_disk(save_dir: Path) -> list[NovelChapter]:
    chapters = []
    for path in sorted(save_dir.glob("chapter_*.json")):
        with open(path, "r") as f:
            data = json.load(f)
            chapters.append(NovelChapter(**data))
    return chapters

def create_novel_epub(
    title: str,
    author: str,
    chapters: list[NovelChapter],
    output_path: Path
) -> Path:
    uid = str(uuid.uuid4())
    
    chunk_entries: list[ChunkEntry] = []
    for idx, chap in enumerate(chapters, start=1):
        blocks = [TextBlock(kind="paragraph", text=p) for p in chap.paragraphs]
        item_id = f"chap-{idx:04d}"
        rel_href = f"text/chap-{idx:04d}.xhtml"
        
        # Add chapter number to the title if not already present
        display_title = f"Chapter {idx}: {chap.title}"
        if chap.title.lower().startswith("chapter"):
             # Avoid "Chapter 1: Chapter 1"
             display_title = chap.title

        content = render_chunk_xhtml(book_title=title, section_title=display_title, blocks=blocks)
        
        chunk_entries.append(ChunkEntry(
            item_id=item_id,
            rel_href=rel_href,
            full_path=f"OEBPS/{rel_href}",
            title=display_title,
            chapter_title=display_title,
            part_number=None,
            content=content
        ))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with ZipFile(output_path, "w") as zout:
        zout.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)
        
        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        zout.writestr("META-INF/container.xml", container_xml.encode("utf-8"), compress_type=ZIP_DEFLATED)
        
        # Build OPF
        manifest_lines = []
        spine_lines = []
        for entry in chunk_entries:
            manifest_lines.append(f'    <item id="{entry.item_id}" href="{entry.rel_href}" media-type="application/xhtml+xml"/>')
            spine_lines.append(f'    <itemref idref="{entry.item_id}"/>')
            
        manifest_lines.append('    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
        
        manifest_xml = "\n".join(manifest_lines)
        spine_xml = "\n".join(spine_lines)

        opf_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{html.escape(title)}</dc:title>
    <dc:creator>{html.escape(author)}</dc:creator>
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
        zout.writestr("OEBPS/content.opf", opf_content.encode("utf-8"), compress_type=ZIP_DEFLATED)
        
        # Build NCX
        ncx_content = render_ncx(book_title=title, uid=uid, chunks=chunk_entries)
        zout.writestr("OEBPS/toc.ncx", ncx_content, compress_type=ZIP_DEFLATED)
        
        # Add chapters
        for entry in chunk_entries:
            zout.writestr(entry.full_path, entry.content.encode("utf-8"), compress_type=ZIP_DEFLATED)
            
    return output_path
