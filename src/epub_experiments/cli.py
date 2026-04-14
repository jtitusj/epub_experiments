from __future__ import annotations

import argparse
from pathlib import Path

from .audify import prepare_epub_for_audify
from .gutenberg import GutenbergClient
from .novelbin import NovelBinClient, create_novel_epub, load_chapters_from_disk
from .pdf_ingest import prepare_pdf_for_audify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EPUB Experiments CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser(
        "download-gutenberg", help="Download EPUB from a Project Gutenberg ebook page"
    )
    download_parser.add_argument("--ebook-id", type=int, required=True, help="Gutenberg ebook ID")
    download_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw"),
        help="Destination directory for downloaded files",
    )

    process_parser = subparsers.add_parser(
        "process-gutenberg",
        help="Download from Gutenberg and produce Audify-ready EPUB named from title/author metadata",
    )
    process_parser.add_argument(
        "--ebook",
        required=True,
        help="Gutenberg ebook ID or URL (for example: 20203 or https://www.gutenberg.org/ebooks/20203)",
    )
    process_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Destination directory for downloaded source EPUB",
    )
    process_parser.add_argument(
        "--processed-dir",
        type=Path,
        default=Path("data/processed"),
        help="Destination directory for processed EPUB",
    )
    process_parser.add_argument(
        "--target-minutes",
        type=int,
        default=10,
        help="Target reading time per part in minutes",
    )
    process_parser.add_argument(
        "--words-per-minute",
        type=int,
        default=150,
        help="Estimated TTS reading speed (words per minute)",
    )
    process_parser.add_argument(
        "--profile",
        choices=["general", "benjamin-franklin"],
        default="general",
        help="Optional cleanup profile for a specific book",
    )

    audify_parser = subparsers.add_parser(
        "prepare-audify",
        help="Clean and split EPUB content into short TTS-friendly parts for Audify",
    )
    audify_parser.add_argument("--input-epub", type=Path, required=True, help="Source EPUB file")
    audify_parser.add_argument("--output-epub", type=Path, required=True, help="Output EPUB file")
    audify_parser.add_argument(
        "--target-minutes",
        type=int,
        default=10,
        help="Target reading time per part in minutes",
    )
    audify_parser.add_argument(
        "--words-per-minute",
        type=int,
        default=150,
        help="Estimated TTS reading speed (words per minute)",
    )
    audify_parser.add_argument(
        "--profile",
        choices=["general", "benjamin-franklin"],
        default="general",
        help="Optional cleanup profile for a specific book",
    )

    novelbin_parser = subparsers.add_parser(
        "scrape-novelbin", help="Scrape chapters from NovelBin and create an EPUB"
    )
    novelbin_parser.add_argument(
        "--start-url", required=True, help="URL of the first chapter to scrape"
    )
    novelbin_parser.add_argument("--title", required=True, help="Title of the novel")
    novelbin_parser.add_argument("--author", default="Unknown", help="Author of the novel")
    novelbin_parser.add_argument(
        "--raw-dir",
        type=Path,
        help="Directory to save/load raw chapter JSON files (for incremental scraping)",
    )
    novelbin_parser.add_argument(
        "--output-epub",
        type=Path,
        default=Path("data/processed/novel.epub"),
        help="Path to the output EPUB file",
    )
    novelbin_parser.add_argument(
        "--max-chapters", type=int, help="Maximum number of chapters to scrape"
    )

    pdf_parser = subparsers.add_parser(
        "prepare-pdf",
        help="Extract text from a PDF and create a chaptered, Audify-friendly EPUB",
    )
    pdf_parser.add_argument("--input-pdf", type=Path, required=True, help="Source PDF file")
    pdf_parser.add_argument("--output-epub", type=Path, required=True, help="Output EPUB file")
    pdf_parser.add_argument("--title", help="Override title metadata (defaults to PDF filename)")
    pdf_parser.add_argument("--author", default="Unknown", help="Author metadata")
    pdf_parser.add_argument(
        "--target-minutes",
        type=int,
        default=10,
        help="Target reading time per part in minutes",
    )
    pdf_parser.add_argument(
        "--words-per-minute",
        type=int,
        default=150,
        help="Estimated TTS reading speed (words per minute)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "download-gutenberg":
        client = GutenbergClient()
        output_path = client.download_ebook_epub(args.ebook_id, args.output_dir)
        print(f"Downloaded: {output_path}")
    elif args.command == "process-gutenberg":
        client = GutenbergClient()
        ebook_id = client.parse_ebook_id(args.ebook)
        html = client.fetch_ebook_page(ebook_id)
        metadata = client.parse_ebook_metadata(html, ebook_id)
        links = client.parse_download_links(html)
        epub_url = client.best_epub_link(links)

        raw_path = args.raw_dir / client.metadata_filename(metadata, ".epub")
        client.download_file(epub_url, raw_path)

        processed_path = args.processed_dir / client.metadata_filename(metadata, ".audify.epub")
        output_path, parts = prepare_epub_for_audify(
            raw_path,
            processed_path,
            target_minutes=args.target_minutes,
            words_per_minute=args.words_per_minute,
            profile=args.profile,
        )
        print(f"Downloaded: {raw_path}")
        print(f"Prepared: {output_path} ({parts} parts)")
    elif args.command == "prepare-audify":
        output_path, parts = prepare_epub_for_audify(
            args.input_epub,
            args.output_epub,
            target_minutes=args.target_minutes,
            words_per_minute=args.words_per_minute,
            profile=args.profile,
        )
        print(f"Prepared: {output_path} ({parts} parts)")
    elif args.command == "scrape-novelbin":
        client = NovelBinClient()
        
        # Scrape new chapters (will resume if raw-dir has content)
        client.scrape_all_chapters(
            args.start_url, 
            save_dir=args.raw_dir, 
            max_chapters=args.max_chapters
        )
        
        # Load all chapters from disk if raw_dir was provided
        if args.raw_dir:
            chapters = load_chapters_from_disk(args.raw_dir)
        else:
            # If no raw_dir, we don't have persistence, but we still need chapters to build EPUB
            # This case is less common now that we support raw-dir.
            print("Warning: --raw-dir not provided. No incremental saving/resumability.")
            chapters = client.scrape_all_chapters(args.start_url, max_chapters=args.max_chapters)

        if not chapters:
            print("No chapters found to create EPUB.")
            return

        output_path = create_novel_epub(
            title=args.title, author=args.author, chapters=chapters, output_path=args.output_epub
        )
        print(f"Created EPUB: {output_path} with {len(chapters)} chapters")
    elif args.command == "prepare-pdf":
        output_path, parts = prepare_pdf_for_audify(
            args.input_pdf,
            args.output_epub,
            target_minutes=args.target_minutes,
            words_per_minute=args.words_per_minute,
            title=args.title,
            author=args.author,
        )
        print(f"Prepared: {output_path} ({parts} parts)")


if __name__ == "__main__":
    main()
