"""Section-aware chunking (SRS Step 6). Every chunk keeps chunk ID, document ID, section,
heading, page reference and version: chunk_uid = <DOC_ID>@<version>#<section>-c<n>."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parsers import ParsedSection

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


@dataclass
class Chunk:
    chunk_uid: str
    section_id: str
    heading: str
    page_start: int | None
    page_end: int | None
    text: str
    token_count: int
    order_index: int


def _words(text: str) -> int:
    return len(text.split())


def _split_long(paragraph: str, max_words: int) -> list[str]:
    sentences = _SENTENCE.split(paragraph)
    parts: list[str] = []
    buf: list[str] = []
    for sentence in sentences:
        if buf and _words(" ".join([*buf, sentence])) > max_words:
            parts.append(" ".join(buf))
            buf = []
        buf.append(sentence)
    if buf:
        parts.append(" ".join(buf))
    return parts


def chunk_sections(doc_id: str, version: str, sections: list[ParsedSection], *, max_words: int = 180) -> list[Chunk]:
    chunks: list[Chunk] = []
    order = 0
    for section in sections:
        body = (section.text or "").strip()
        if not body:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n(?=- )", body) if p.strip()]
        pieces: list[str] = []
        buf: list[str] = []
        for para in paragraphs:
            if _words(para) > max_words:
                if buf:
                    pieces.append("\n".join(buf))
                    buf = []
                pieces.extend(_split_long(para, max_words))
                continue
            if buf and _words("\n".join([*buf, para])) > max_words:
                pieces.append("\n".join(buf))
                buf = []
            buf.append(para)
        if buf:
            pieces.append("\n".join(buf))
        for n, piece in enumerate(pieces, start=1):
            chunks.append(Chunk(
                chunk_uid=f"{doc_id}@{version}#{section.section_id}-c{n}",
                section_id=section.section_id,
                heading=section.heading,
                page_start=section.page_start,
                page_end=section.page_end,
                text=piece,
                token_count=_words(piece),
                order_index=order,
            ))
            order += 1
    return chunks
