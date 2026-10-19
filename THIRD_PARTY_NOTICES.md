# Third-party code notices

This project contains copied and adapted implementations from permissively licensed open-source projects. The copied logic is kept in ShengYue's own runtime path; these are not remote service integrations.

## Citadel

- Repository: https://github.com/everydaythingssoftware/citadel
- Pinned source commit: `f0ec58eee58185a770e9f174d6edf7255245adf6`
- License: MIT
- Copied/adapted into: `src/upstream_book_algorithms.py`, `src/book_search.py`
- Upstream files: `src/lib/isbn.ts`, `src/lib/metadata-providers/aggregate.ts`, `src-tauri/src/metadata/openlibrary.rs`
- Adopted behavior: ISBN normalization, ISBN-10 to ISBN-13 canonicalization, ISBN equivalence, preferred identifier selection, case-insensitive metadata dedupe, Open Library ISBN-specific lookup, subtitle and richer metadata mapping.
- Complete license text: `vendor/licenses/citadel-MIT.txt`

## Obsidian Book Search Plugin

- Repository: https://github.com/anpigon/obsidian-book-search-plugin
- Pinned source commit: `9bd8d0cad45196aed7fe5ab1dda62052718230eb`
- Copyright: Copyright (c) 2020 Jake Runzer
- License: MIT
- Copied/adapted into: `src/book_search.py`
- Upstream files: `src/apis/google_books_api.ts`, `src/apis/naver_books_api.ts`
- Adopted behavior: structured Google Books identifier extraction, subtitle mapping, canonical book link preference, and removal of the optional `edge=curl` cover parameter.
- Complete license text: `vendor/licenses/obsidian-book-search-plugin-MIT.txt`

## Gutendex

- Repository: https://github.com/garethbjohnson/gutendex
- Pinned source commit: `c3f75a8bd783ca91d9cd37d133028ff994e7ba4b`
- Copyright: Copyright (c) 2017 Gareth Johnson
- License: MIT
- Full upstream snapshot: `vendor/gutendex`
- Copied into: `src/upstream_book_algorithms.py`
- Adopted behavior: multi-line Gutenberg title/subtitle formatting.

## MIT permission notice

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files, to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies, subject to including the applicable copyright and permission notices. The software is provided “AS IS”, without warranty of any kind.

The complete original MIT text for Gutendex is retained at `vendor/gutendex/license`.
