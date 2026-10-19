"""Permissively licensed book-search algorithms copied into ShengYue.

This is application code, not a client wrapper around the upstream projects.
The ISBN functions and case-insensitive list dedupe are Python ports of
Citadel's metadata implementation (MIT, commit f0ec58e). ``fix_subtitles`` is
copied from Gutendex (MIT, commit c3f75a8). See THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any


LINE_BREAK_PATTERN = re.compile(r"[ \t]*[\n\r]+[ \t]*")


def fix_subtitles(title: str) -> str:
    """Format the first title line as a subtitle and later lines as details."""

    new_title = LINE_BREAK_PATTERN.sub(": ", title, count=1)
    return LINE_BREAK_PATTERN.sub("; ", new_title)


def normalize_isbn(raw: str) -> str | None:
    """Return a compact structurally valid ISBN-10 or ISBN-13."""

    trimmed = raw.strip()
    if not trimmed:
        return None

    lowered = trimmed.casefold()
    without_prefix = trimmed[5:].strip() if lowered.startswith("isbn:") else trimmed
    compact = re.sub(r"[^0-9xX]", "", without_prefix).upper()
    if re.fullmatch(r"\d{13}", compact):
        return compact
    if re.fullmatch(r"\d{9}[\dX]", compact):
        return compact
    return None


def to_isbn13(raw: str) -> str | None:
    """Canonicalize an ISBN-10/13 to its ISBN-13 representation."""

    normalized = normalize_isbn(raw)
    if not normalized:
        return None
    if len(normalized) == 13:
        return normalized

    core = f"978{normalized[:9]}"
    weighted_sum = sum(int(character) * (1 if index % 2 == 0 else 3) for index, character in enumerate(core))
    check_digit = (10 - (weighted_sum % 10)) % 10
    return f"{core}{check_digit}"


def isbn_equivalent(first: str | None, second: str | None) -> bool:
    """Return whether two ISBN strings identify the same edition."""

    if not first or not second:
        return False
    canonical = to_isbn13(first)
    return canonical is not None and canonical == to_isbn13(second)


def pick_preferred_isbn(values: Iterable[str]) -> str | None:
    """Prefer ISBN-13, otherwise return the first normalized ISBN."""

    normalized = [isbn for value in values if (isbn := normalize_isbn(value))]
    return next((isbn for isbn in normalized if len(isbn) == 13), normalized[0] if normalized else None)


def unique_casefolded(values: Iterable[Any], *, limit: int = 30) -> list[str]:
    """Dedupe trimmed text without losing first-seen display spelling."""

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        trimmed = str(value or "").strip()
        key = trimmed.casefold()
        if not trimmed or key in seen:
            continue
        seen.add(key)
        output.append(trimmed)
        if len(output) >= limit:
            break
    return output
