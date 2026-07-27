#!/usr/bin/env python3
"""Run parser and chunking checks against full public-domain Chinese novels."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402


CORPUS = {
    "sanguo": {
        "title": "三國志演義",
        "url": "https://www.gutenberg.org/cache/epub/23950/pg23950.txt",
        "ebook": "https://www.gutenberg.org/ebooks/23950",
        "minimum_sections": 100,
    },
    "liaozhai": {
        "title": "聊齋志異",
        "url": "https://www.gutenberg.org/cache/epub/51828/pg51828.txt",
        "ebook": "https://www.gutenberg.org/ebooks/51828",
        "minimum_sections": 450,
    },
    "rulin": {
        "title": "儒林外史",
        "url": "https://www.gutenberg.org/cache/epub/24032/pg24032.txt",
        "ebook": "https://www.gutenberg.org/ebooks/24032",
        # This Gutenberg transcription contains several chapter headings joined
        # to prose on the same physical line, so only standalone headings count.
        "minimum_sections": 40,
    },
}


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "curl",
            "--location",
            "--fail",
            "--silent",
            "--show-error",
            "--user-agent",
            "ai-novel-reader-public-domain-test/1.0",
            "--output",
            str(destination),
            url,
        ],
        check=True,
    )


def analyze(name: str, metadata: dict, cache_dir: Path, max_units: int) -> dict:
    path = cache_dir / f"{name}.txt"
    if not path.exists():
        _download(metadata["url"], path)

    text = path.read_text(encoding="utf-8-sig").strip()
    books = list(app.BOOK_HEADING_PATTERN.finditer(text))
    sections = list(app._build_section_heading_pattern().finditer(text))
    chunks = app._chunk_text_by_paragraph_words(text, max_units)
    chunk_units = [app._count_reading_units(chunk) for chunk in chunks]

    source_compact = re.sub(r"\s+", "", text)
    chunked_compact = re.sub(r"\s+", "", "".join(chunks))
    failures = []
    if source_compact != chunked_compact:
        failures.append("non-whitespace source text changed during chunking")
    if not chunks:
        failures.append("no chunks produced")
    if chunk_units and max(chunk_units) > max_units:
        failures.append(f"chunk exceeded {max_units} reading units")
    if len(sections) < metadata["minimum_sections"]:
        failures.append(
            f"only {len(sections)} section headings detected; "
            f"expected at least {metadata['minimum_sections']}"
        )

    return {
        "title": metadata["title"],
        "source": metadata["ebook"],
        "characters": len(text),
        "book_headings": len(books),
        "section_headings": len(sections),
        "chunks": len(chunks),
        "maximum_chunk_units": max(chunk_units) if chunk_units else 0,
        "source_text_preserved": source_compact == chunked_compact,
        "passed": not failures,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=ROOT / ".cache" / "public-domain-novels",
    )
    parser.add_argument("--max-units", type=int, default=500)
    args = parser.parse_args()

    results = [
        analyze(name, metadata, args.cache_dir, args.max_units)
        for name, metadata in CORPUS.items()
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
