"""Structure-aware chunking with overlap.

Chunks never cross a page boundary, so each chunk has exactly one page number, and every
chunk's text is the exact substring page.text[char_start:char_end].
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from app.services.parsing import ParsedPage



@dataclass
class Chunk:
    page_number: int
    char_start: int
    char_end: int
    text: str
    section_title: str | None
    line_start: int | None
    line_end: int | None


def _sentences(text: str, base: int) -> list[tuple[int, int]]:
    """Split a paragraph into sentence spans (absolute offsets)."""
    spans: list[tuple[int, int]] = []
    # Split on CJK / Latin sentence terminators while keeping them attached.
    for m in re.finditer(r".+?(?:[。！？!?；;]+|\.(?=\s)|\n|$)", text, re.S):
        s, e = m.start(), m.end()
        if not text[s:e].strip():
            continue
        # trim whitespace
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            spans.append((base + s, base + e))
    if not spans and text.strip():
        spans.append((base, base + len(text)))
    return spans


def _units(page_text: str, max_unit: int) -> list[tuple[int, int, bool]]:
    """(start, end, is_paragraph_start) sentence units; packing them gives sentence-level overlap."""
    units: list[tuple[int, int, bool]] = []
    for m in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", page_text):
        start, end = m.start(), m.end()
        para = page_text[start:end]
        if not para.strip():
            continue
        first = True
        for s, e in _sentences(para, start):
            # Hard-split pathological sentences.
            while e - s > max_unit:
                units.append((s, s + max_unit, first))
                first = False
                s += max_unit
            if e > s:
                units.append((s, e, first))
                first = False
    return units


def _section_at(headings: list[tuple[int, str]], offset: int, inherited: str | None) -> str | None:
    current = inherited
    for pos, title in headings:
        if pos <= offset:
            current = title
        else:
            break
    return current


def chunk_pages(
    pages: list[ParsedPage], target_chars: int = 700, overlap_chars: int = 120, track_lines: bool = False
) -> list[Chunk]:
    chunks: list[Chunk] = []
    inherited_section: str | None = None
    for page in pages:
        text = page.text
        headings = sorted(page.headings)
        heading_starts = {pos for pos, _ in headings}
        units = _units(text, max_unit=target_chars)
        newlines = [m.start() for m in re.finditer("\n", text)] if track_lines else []
        i = 0
        while i < len(units):
            start = units[i][0]
            end = units[i][1]
            j = i + 1
            while j < len(units):
                nxt_start, nxt_end, _ = units[j]
                # Start a new chunk at a heading (keeps sections semantically coherent).
                if nxt_start in heading_starts and end - start >= target_chars * 0.3:
                    break
                if nxt_end - start > target_chars:
                    break
                end = nxt_end
                j += 1
            chunk_text = text[start:end]
            line_start = line_end = None
            if track_lines:
                line_start = page.line_offset + bisect.bisect_left(newlines, start) + 1
                line_end = page.line_offset + bisect.bisect_left(newlines, end) + 1
            chunks.append(
                Chunk(
                    page_number=page.page_number,
                    char_start=start,
                    char_end=end,
                    text=chunk_text,
                    section_title=_section_at(headings, start, inherited_section),
                    line_start=line_start,
                    line_end=line_end,
                )
            )
            if j >= len(units):
                break
            # Overlap: step back over trailing units totalling <= overlap_chars.
            k = j
            while k - 1 > i and end - units[k - 1][0] <= overlap_chars:
                k -= 1
            # Do not carry overlap across a heading boundary.
            if units[j][0] in heading_starts:
                k = j
            i = k
        if headings:
            inherited_section = headings[-1][1]
    return chunks
