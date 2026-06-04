"""
Extract title-block metadata (title, revision, author, date, sheet, company)
from a schematic's recovered raw text.

EDA tools render the title block as plain text near the bottom-right of each
sheet. The keys are highly conventional ("Title", "Rev", "Sheet", "Date",
"Drawn by", "Designed by", "Company"). We scan the whole raw_text for these
keys and capture the immediately-following value.

This is intentionally regex-based — robust enough for the formats we have
seen (Altium, KiCad, EAGLE PDF exports). For OCR-quality text we tolerate
missing punctuation and case differences.
"""

from __future__ import annotations

import re


# Each pattern returns the captured value in group 1. We try them in order.
_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "title":    [re.compile(r"\bTitle[:\s]+([^\r\n]{2,80}?)\s{2,}", re.IGNORECASE),
                 re.compile(r"\bTitle[:\s]+([^\r\n]{2,80})", re.IGNORECASE)],
    "revision": [re.compile(r"\bRev(?:ision)?[:\s]+([A-Za-z0-9._\-]{1,20})", re.IGNORECASE)],
    "author":   [re.compile(r"\bDrawn\s*by[:\s]+([^\r\n]{2,80})", re.IGNORECASE),
                 re.compile(r"\bDesigned\s*by[:\s]+([^\r\n]{2,80})", re.IGNORECASE),
                 re.compile(r"\bAuthor[:\s]+([^\r\n]{2,80})", re.IGNORECASE)],
    "company":  [re.compile(r"\bCompany[:\s]+([^\r\n]{2,80})", re.IGNORECASE)],
    "date":     [re.compile(r"\bDate[:\s]+([0-9./\-]{6,12})", re.IGNORECASE),
                 re.compile(r"\b(20\d{2}[-./]\d{1,2}[-./]\d{1,2})\b")],
    "sheet":    [re.compile(r"\bSheet[:\s]+([0-9]+\s*(?:of\s*[0-9]+)?)", re.IGNORECASE)],
}


def extract_title_block(text: str) -> dict[str, str]:
    """Return a dict with whatever title-block fields could be recovered."""
    out: dict[str, str] = {}
    if not text:
        return out
    for field, patterns in _PATTERNS.items():
        for pat in patterns:
            m = pat.search(text)
            if not m:
                continue
            val = m.group(1).strip(" ,;:|\t")
            if val:
                out[field] = val
                break
    return out


__all__ = ["extract_title_block"]
