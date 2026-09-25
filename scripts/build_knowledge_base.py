#!/usr/bin/env python
"""Build the Lumora Home Technologies knowledge base for SupportNova.

The knowledge base is authored as Markdown sources with YAML front matter, one
file per document version (``<DOC_ID>_v<VERSION>.md``). This script:

1. parses every source: the YAML front matter plus a small Markdown subset
   (``#`` / ``##`` / ``###`` headings, paragraphs, ``- `` bullets, ``**bold**``,
   pipe tables and ``::: hidden`` blocks used only by security samples);
2. renders it to the format named in its front matter - PDF (fpdf2), DOCX
   (python-docx) or Markdown (copied as-is);
3. writes a ``manifest.yaml`` with the metadata, SHA-256 and size of each file;
4. verifies the result: the sources are validated against
   ``knowledge_base/kb_spec.yaml`` (versions, metadata, section ids and
   headings, must-state facts, the routing table) and every rendered file is
   re-opened to confirm that it has text and that every section heading
   survived rendering (DOCX headings must use the Heading 1 / Heading 2 styles).

Build targets::

    kb        knowledge_base/source/                  -> knowledge_base/sample_documents/ (+ manifest.yaml)
    security  knowledge_base/security_samples/source/ -> knowledge_base/security_samples/
    hidden    data/hidden_test_ready/documents/source/ -> data/hidden_test_ready/documents/ (+ manifest.yaml)

Usage (from the repository root)::

    python scripts/build_knowledge_base.py              # build every target, then verify
    python scripts/build_knowledge_base.py --target kb  # build one target, then verify
    python scripts/build_knowledge_base.py --check      # verify existing outputs only

The process exits with status 1 when any verification fails.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import re
import shutil
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docx
import pymupdf
import yaml
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.text.paragraph import Paragraph as DocxParagraph
from fpdf import FPDF, XPos, YPos
from fpdf.fonts import FontFace

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "knowledge_base" / "kb_spec.yaml"
DEPARTMENTS_PATH = REPO_ROOT / "config" / "departments.yaml"
TAXONOMY_PATH = REPO_ROOT / "config" / "taxonomy.yaml"
ROUTING_RULES_PATH = REPO_ROOT / "rules" / "routing_rules" / "routing_rules.yaml"

ORGANIZATION_NAME = "Lumora Home Technologies"
GENERATOR = "SupportNova scripts/build_knowledge_base.py"

DOC_TYPES = ("policy", "rules", "sop", "guideline", "faq", "template")
STATUSES = ("Active", "Previous", "Superseded", "Draft")
FORMATS = ("pdf", "docx", "md")
REQUIRED_FRONT_MATTER = (
    "doc_id", "title", "doc_type", "version", "status", "effective_date",
    "expiry_date", "owner_department", "topics", "format",
)
# Wording that a non-Active document must display prominently near the top.
STATUS_NOTICE_KEYWORDS = {
    "Previous": "PREVIOUS VERSION",
    "Superseded": "SUPERSEDED",
    "Draft": "DRAFT - NOT FOR OPERATIONAL USE",
}

DOC_ID_RE = re.compile(r"^[A-Z]{3}-[A-Z]{3}-\d{2}$")
VERSION_RE = re.compile(r"^\d+\.\d+$")
HEADING_RE = re.compile(r"^(?P<hashes>#+)\s+(?P<text>.*?)\s*$")
SECTION_HEADING_RE = re.compile(r"^(?P<id>\d+(?:\.\d+)*)\s+(?P<heading>\S.*)$")
TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
HIDDEN_FENCE_OPEN = "::: hidden"
HIDDEN_FENCE_CLOSE = ":::"

# Unicode punctuation that must never reach the PDF core fonts (Latin-1 only),
# listed by code point so that this file stays pure ASCII.
_REPLACEMENT_GROUPS: tuple[tuple[tuple[int, ...], str], ...] = (
    ((0x2018, 0x2019, 0x201A, 0x201B, 0x2032), "'"),               # single quotes, prime
    ((0x201C, 0x201D, 0x201E, 0x2033), '"'),                        # double quotes
    ((0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212), "-"),  # hyphens, dashes, minus
    ((0x2022, 0x2023, 0x2043), "-"),                                # bullets
    ((0x00A0, 0x2002, 0x2003, 0x2009, 0x200A, 0x202F), " "),        # non-breaking / thin spaces
    ((0x200B, 0xFEFF), ""),                                         # zero-width space, BOM
    ((0x2026,), "..."),
    ((0x2192,), "->"), ((0x2190,), "<-"),
    ((0x2264,), "<="), ((0x2265,), ">="), ((0x2260,), "!="),
    ((0x00D7,), "x"),
)
UNICODE_REPLACEMENTS: dict[str, str] = {
    chr(code): replacement for codes, replacement in _REPLACEMENT_GROUPS for code in codes
}

# PDF layout (millimetres / points)
PDF_FONT = "Helvetica"
PDF_MARGIN_MM = 20.0
PDF_TOP_MARGIN_MM = 22.0
PDF_BOTTOM_MARGIN_MM = 20.0
PDF_TITLE_PT = 18
PDF_META_PT = 9
PDF_H2_PT = 13
PDF_H3_PT = 11
PDF_BODY_PT = 10
PDF_TABLE_PT = 9
PDF_HEADER_PT = 8

# DOCX layout
DOCX_FONT = "Calibri"
DOCX_BODY_PT = 10.5
DOCX_META_PT = 9
DOCX_TABLE_PT = 9
NOTICE_RGB = (0xA0, 0x10, 0x10)


# ---------------------------------------------------------------------------
# Build targets
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BuildTarget:
    """A group of sources rendered into one output folder."""

    key: str
    label: str
    source_dir: Path
    output_dir: Path
    manifest_path: Path | None
    validate_against_spec: bool


TARGETS: dict[str, BuildTarget] = {
    "kb": BuildTarget(
        key="kb",
        label="Knowledge base",
        source_dir=REPO_ROOT / "knowledge_base" / "source",
        output_dir=REPO_ROOT / "knowledge_base" / "sample_documents",
        manifest_path=REPO_ROOT / "knowledge_base" / "manifest.yaml",
        validate_against_spec=True,
    ),
    "security": BuildTarget(
        key="security",
        label="Security samples",
        source_dir=REPO_ROOT / "knowledge_base" / "security_samples" / "source",
        output_dir=REPO_ROOT / "knowledge_base" / "security_samples",
        manifest_path=None,
        validate_against_spec=False,
    ),
    "hidden": BuildTarget(
        key="hidden",
        label="Hidden test pack",
        source_dir=REPO_ROOT / "data" / "hidden_test_ready" / "documents" / "source",
        output_dir=REPO_ROOT / "data" / "hidden_test_ready" / "documents",
        manifest_path=REPO_ROOT / "data" / "hidden_test_ready" / "documents" / "manifest.yaml",
        validate_against_spec=False,
    ),
}


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------

class SourceError(ValueError):
    """Raised when a source file cannot be parsed."""


@dataclass(frozen=True)
class HeadingBlock:
    """A heading. Level 1 is the document title, 2 is ``##`` and 3 is ``###``."""

    level: int
    text: str
    section_id: str | None = None

    @property
    def display(self) -> str:
        """Heading text as rendered, including the section id."""
        return f"{self.section_id} {self.text}" if self.section_id else self.text


@dataclass(frozen=True)
class ParagraphBlock:
    """A paragraph. ``role`` is one of body, meta, notice or hidden."""

    text: str
    role: str = "body"


@dataclass(frozen=True)
class BulletBlock:
    """A bullet list; every item is one line of inline text."""

    items: tuple[str, ...]


@dataclass(frozen=True)
class TableBlock:
    """A pipe table with one header row."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


Block = HeadingBlock | ParagraphBlock | BulletBlock | TableBlock


@dataclass(frozen=True)
class FrontMatter:
    """Validated document metadata taken from the YAML front matter."""

    doc_id: str
    title: str
    doc_type: str
    version: str
    status: str
    effective_date: dt.date
    expiry_date: dt.date | None
    owner_department: str
    topics: tuple[str, ...]
    supersedes: str | None
    superseded_by: str | None
    format: str

    @classmethod
    def from_mapping(cls, data: Any, source: Path) -> FrontMatter:
        """Validate the raw YAML mapping and convert it to a ``FrontMatter``."""
        if not isinstance(data, dict):
            raise SourceError(f"{source.name}: front matter must be a YAML mapping")
        missing = [key for key in REQUIRED_FRONT_MATTER if key not in data]
        if missing:
            raise SourceError(f"{source.name}: front matter is missing {', '.join(missing)}")

        def text(key: str) -> str:
            value = data[key]
            if not isinstance(value, str) or not value.strip():
                raise SourceError(f"{source.name}: '{key}' must be a non-empty string (quote versions)")
            return value.strip()

        def optional_text(key: str) -> str | None:
            value = data.get(key)
            if value is None:
                return None
            if not isinstance(value, str):
                raise SourceError(f"{source.name}: '{key}' must be a quoted string or null")
            return value.strip()

        def date_value(key: str, allow_null: bool) -> dt.date | None:
            value = data[key]
            if value is None and allow_null:
                return None
            if isinstance(value, dt.datetime):
                return value.date()
            if isinstance(value, dt.date):
                return value
            if isinstance(value, str):
                try:
                    return dt.date.fromisoformat(value)
                except ValueError as exc:
                    raise SourceError(f"{source.name}: '{key}' is not an ISO date") from exc
            raise SourceError(f"{source.name}: '{key}' must be an ISO date{' or null' if allow_null else ''}")

        front = cls(
            doc_id=text("doc_id"),
            title=text("title"),
            doc_type=text("doc_type"),
            version=text("version"),
            status=text("status"),
            effective_date=date_value("effective_date", allow_null=False),  # type: ignore[arg-type]
            expiry_date=date_value("expiry_date", allow_null=True),
            owner_department=text("owner_department"),
            topics=tuple(str(topic) for topic in (data.get("topics") or [])),
            supersedes=optional_text("supersedes"),
            superseded_by=optional_text("superseded_by"),
            format=text("format"),
        )
        problems: list[str] = []
        if not DOC_ID_RE.match(front.doc_id):
            problems.append(f"doc_id '{front.doc_id}' does not match AAA-AAA-00")
        if not VERSION_RE.match(front.version):
            problems.append(f"version '{front.version}' must look like 1.0")
        if front.doc_type not in DOC_TYPES:
            problems.append(f"doc_type '{front.doc_type}' is not one of {', '.join(DOC_TYPES)}")
        if front.status not in STATUSES:
            problems.append(f"status '{front.status}' is not one of {', '.join(STATUSES)}")
        if front.format not in FORMATS:
            problems.append(f"format '{front.format}' is not one of {', '.join(FORMATS)}")
        if not front.topics:
            problems.append("topics must list at least one topic")
        if front.expiry_date and front.expiry_date < front.effective_date:
            problems.append("expiry_date is before effective_date")
        if problems:
            raise SourceError(f"{source.name}: " + "; ".join(problems))
        return front


@dataclass(frozen=True)
class Section:
    """A numbered section: its heading and the blocks up to the next heading."""

    section_id: str
    heading: str
    level: int
    blocks: tuple[Block, ...]

    @property
    def display(self) -> str:
        return f"{self.section_id} {self.heading}"

    @property
    def plain_text(self) -> str:
        """All text of the section with inline markup removed."""
        return " ".join(block_plain_text(block) for block in self.blocks)


@dataclass
class SourceDocument:
    """A parsed Markdown source."""

    path: Path
    raw_text: str
    front: FrontMatter
    blocks: list[Block]

    @property
    def stem(self) -> str:
        return f"{self.front.doc_id}_v{self.front.version}"

    @property
    def header_text(self) -> str:
        """Running page header, e.g. ``REF-POL-02 v2.0 - Refund Policy``."""
        text = f"{self.front.doc_id} v{self.front.version} - {self.front.title}"
        if self.front.status != "Active":
            text += f" - {self.front.status.upper()}"
        return text

    @property
    def title(self) -> str:
        for block in self.blocks:
            if isinstance(block, HeadingBlock) and block.level == 1:
                return block.text
        return self.front.title

    @property
    def sections(self) -> list[Section]:
        sections: list[Section] = []
        current: HeadingBlock | None = None
        body: list[Block] = []
        for block in self.blocks:
            if isinstance(block, HeadingBlock) and block.level >= 2:
                if current is not None:
                    sections.append(_make_section(current, body))
                current, body = block, []
            elif current is not None:
                body.append(block)
        if current is not None:
            sections.append(_make_section(current, body))
        return sections

    def output_path(self, output_dir: Path) -> Path:
        return output_dir / f"{self.stem}.{self.front.format}"


def _make_section(heading: HeadingBlock, blocks: list[Block]) -> Section:
    assert heading.section_id is not None
    return Section(heading.section_id, heading.text, heading.level, tuple(blocks))


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def sanitize_latin1(text: str) -> str:
    """Replace typographic Unicode punctuation and drop anything outside Latin-1.

    fpdf2's core fonts can only encode Latin-1, so smart quotes, dashes and
    similar characters that slipped into a source are mapped to ASCII.
    """
    for bad, good in UNICODE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def split_bold(text: str) -> list[tuple[str, bool]]:
    """Split inline text into ``(fragment, is_bold)`` pairs on ``**`` markers."""
    parts: list[tuple[str, bool]] = []
    position = 0
    for match in BOLD_RE.finditer(text):
        if match.start() > position:
            parts.append((text[position:match.start()], False))
        parts.append((match.group(1), True))
        position = match.end()
    if position < len(text):
        parts.append((text[position:], False))
    return parts or [("", False)]


def strip_inline(text: str) -> str:
    """Remove inline markup (``**bold**``) from a fragment."""
    return BOLD_RE.sub(r"\1", text)


def block_plain_text(block: Block) -> str:
    if isinstance(block, HeadingBlock):
        return block.display
    if isinstance(block, ParagraphBlock):
        return strip_inline(block.text)
    if isinstance(block, BulletBlock):
        return " ".join(strip_inline(item) for item in block.items)
    return " ".join(" ".join(strip_inline(cell) for cell in row) for row in (block.header, *block.rows))


def normalise(text: str) -> str:
    """Lower-case, markup-free, single-spaced text used for robust comparisons."""
    text = sanitize_latin1(strip_inline(text))
    return re.sub(r"\s+", " ", text).strip().lower()


def expected_meta_line(front: FrontMatter, department_names: dict[str, str]) -> str:
    """The metadata line every document shows directly below its title."""
    owner = department_names.get(front.owner_department, front.owner_department)
    expiry = front.expiry_date.isoformat() if front.expiry_date else "none"
    return (
        f"Document ID: {front.doc_id} | Version: {front.version} | Status: {front.status} | "
        f"Effective date: {front.effective_date.isoformat()} | Expiry date: {expiry} | Owner: {owner}"
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def split_front_matter(raw_text: str, source: Path) -> tuple[dict[str, Any], list[str], int]:
    """Return the YAML front matter, the body lines and the body's first line number."""
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SourceError(f"{source.name}: the file must start with a '---' front-matter line")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            data = yaml.safe_load("\n".join(lines[1:index])) or {}
            return data, lines[index + 1:], index + 2
    raise SourceError(f"{source.name}: the front matter is not closed with '---'")


def parse_table(lines: list[str], source: Path, line_no: int) -> TableBlock:
    """Parse pipe-table lines (header, separator, rows) into a ``TableBlock``."""
    if len(lines) < 2 or not TABLE_SEPARATOR_RE.match(lines[1]):
        raise SourceError(f"{source.name}:{line_no}: a table needs a header row and a '|---|' separator row")

    def cells(line: str) -> tuple[str, ...]:
        inner = line.strip()
        inner = inner[1:] if inner.startswith("|") else inner
        inner = inner[:-1] if inner.endswith("|") else inner
        return tuple(cell.strip() for cell in inner.split("|"))

    header = cells(lines[0])
    rows = tuple(cells(line) for line in lines[2:])
    for offset, row in enumerate(rows, start=2):
        if len(row) != len(header):
            raise SourceError(
                f"{source.name}:{line_no + offset}: table row has {len(row)} cells, header has {len(header)}"
            )
    return TableBlock(header, rows)


def parse_body(lines: list[str], source: Path, first_line_no: int) -> list[Block]:
    """Parse the Markdown subset used by the knowledge-base sources."""
    blocks: list[Block] = []
    paragraph: list[str] = []
    bullets: list[str] = []
    table: list[str] = []
    table_start = 0
    hidden: list[str] | None = None

    def flush() -> None:
        nonlocal paragraph, bullets, table
        if paragraph:
            blocks.append(ParagraphBlock(" ".join(paragraph)))
            paragraph = []
        if bullets:
            blocks.append(BulletBlock(tuple(bullets)))
            bullets = []
        if table:
            blocks.append(parse_table(table, source, table_start))
            table = []

    for line_no, raw_line in enumerate(lines, start=first_line_no):
        line = raw_line.rstrip()
        stripped = line.strip()
        if hidden is not None:
            if stripped == HIDDEN_FENCE_CLOSE:
                blocks.append(ParagraphBlock(" ".join(hidden), role="hidden"))
                hidden = None
            elif stripped:
                hidden.append(stripped)
            continue
        if not stripped:
            flush()
            continue
        if stripped == HIDDEN_FENCE_OPEN:
            flush()
            hidden = []
            continue
        heading = HEADING_RE.match(line) if line.startswith("#") else None
        if heading:
            flush()
            blocks.append(parse_heading(len(heading["hashes"]), heading["text"], source, line_no))
            continue
        if line.startswith("- "):
            if paragraph or table:
                flush()
            bullets.append(line[2:].strip())
            continue
        if bullets and line.startswith("  "):
            bullets[-1] = f"{bullets[-1]} {stripped}"
            continue
        if stripped.startswith("|"):
            if paragraph or bullets:
                flush()
            if not table:
                table_start = line_no
            table.append(stripped)
            continue
        if bullets or table:
            flush()
        paragraph.append(stripped)
    if hidden is not None:
        raise SourceError(f"{source.name}: a '::: hidden' block is not closed with ':::'")
    flush()
    return assign_roles(blocks)


def parse_heading(level: int, text: str, source: Path, line_no: int) -> HeadingBlock:
    """Validate a heading line: ``# Title``, ``## <id> <Heading>`` or ``### <id.sub> <Heading>``."""
    if level == 1:
        return HeadingBlock(1, text)
    if level > 3:
        raise SourceError(f"{source.name}:{line_no}: only #, ## and ### headings are allowed")
    match = SECTION_HEADING_RE.match(text)
    if not match:
        raise SourceError(f"{source.name}:{line_no}: a section heading must be '<id> <Heading>'")
    section_id = match["id"]
    if level == 2 and "." in section_id:
        raise SourceError(f"{source.name}:{line_no}: '##' headings take top-level ids (got {section_id})")
    if level == 3 and "." not in section_id:
        raise SourceError(f"{source.name}:{line_no}: '###' headings take dotted ids (got {section_id})")
    return HeadingBlock(level, match["heading"], section_id)


def assign_roles(blocks: list[Block]) -> list[Block]:
    """Mark the metadata line and the status notices that precede the first section."""
    result: list[Block] = []
    seen_title = seen_meta = seen_section = False
    for block in blocks:
        if isinstance(block, HeadingBlock):
            seen_title = seen_title or block.level == 1
            seen_section = seen_section or block.level >= 2
        elif isinstance(block, ParagraphBlock) and block.role == "body" and seen_title and not seen_section:
            text = block.text.strip()
            if not seen_meta and text.startswith("Document ID:"):
                block, seen_meta = ParagraphBlock(text, role="meta"), True
            elif text.startswith("**") and text.endswith("**") and text.count("**") == 2:
                block = ParagraphBlock(text, role="notice")
        result.append(block)
    return result


def parse_source(path: Path) -> SourceDocument:
    """Read and parse one Markdown source file."""
    raw_text = path.read_text(encoding="utf-8")
    data, body_lines, first_line_no = split_front_matter(raw_text, path)
    front = FrontMatter.from_mapping(data, path)
    blocks = parse_body(body_lines, path, first_line_no)
    return SourceDocument(path=path, raw_text=raw_text, front=front, blocks=blocks)


def load_sources(target: BuildTarget) -> list[SourceDocument]:
    """Parse every ``*.md`` source of a target, sorted by document id and version."""
    if not target.source_dir.is_dir():
        raise SourceError(f"source folder not found: {rel(target.source_dir)}")
    documents = [parse_source(path) for path in sorted(target.source_dir.glob("*.md"))]
    documents.sort(key=lambda d: (d.front.doc_id, tuple(int(p) for p in d.front.version.split("."))))
    return documents


# ---------------------------------------------------------------------------
# PDF rendering (fpdf2, core fonts)
# ---------------------------------------------------------------------------

class KnowledgeBasePDF(FPDF):
    """A4 document with a running header and a ``Page X of Y`` footer."""

    def __init__(self, header_text: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.header_text = sanitize_latin1(header_text)

    def header(self) -> None:
        self.set_y(10)
        self.set_font(PDF_FONT, size=PDF_HEADER_PT)
        self.set_text_color(90, 90, 90)
        self.cell(0, 5, self.header_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
        self.set_draw_color(170, 170, 170)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y() + 0.5, self.w - self.r_margin, self.get_y() + 0.5)
        self.set_text_color(0, 0, 0)
        self.set_y(PDF_TOP_MARGIN_MM)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font(PDF_FONT, size=PDF_HEADER_PT)
        self.set_text_color(90, 90, 90)
        self.cell(0, 6, f"Page {self.page_no()} of {{nb}}", align="C")
        self.set_text_color(0, 0, 0)


def _pdf_markup(text: str) -> str:
    """Prepare inline text for ``multi_cell(markdown=True)``: keep ``**bold**`` only."""
    text = sanitize_latin1(text)
    for marker in ("--", "__", "~~"):
        text = text.replace(marker, "\\" + marker)
    return text


def _pdf_column_widths(pdf: FPDF, table: TableBlock, padding: float) -> list[float]:
    """Column widths (mm) that fill the page width without breaking any single word.

    Each column gets at least the width of its longest word (so identifiers such
    as ``RTE-001`` never wrap); the remaining width is shared in proportion to how
    much wider each column would be if its longest cell were not wrapped.
    """
    def width(text: str, bold: bool) -> float:
        pdf.set_font(PDF_FONT, style="B" if bold else "", size=PDF_TABLE_PT)
        return pdf.get_string_width(sanitize_latin1(strip_inline(text))) + 2 * padding + 1.0

    minimum: list[float] = []
    natural: list[float] = []
    for column in range(len(table.header)):
        cells = [(table.header[column], True), *((row[column], False) for row in table.rows)]
        minimum.append(max(width(word, bold) for text, bold in cells for word in (text.split() or [""])))
        natural.append(max(width(text, bold) for text, bold in cells))
    pdf.set_font(PDF_FONT, size=PDF_TABLE_PT)
    available = pdf.epw
    if sum(natural) <= available:
        return [w * available / sum(natural) for w in natural]
    spare = max(available - sum(minimum), 0.0)
    stretch = [n - m for n, m in zip(natural, minimum, strict=True)]
    total_stretch = sum(stretch) or 1.0
    return [m + spare * s / total_stretch for m, s in zip(minimum, stretch, strict=True)]


def render_pdf(document: SourceDocument, out_path: Path) -> None:
    """Render a source to PDF with fpdf2."""
    front = document.front
    pdf = KnowledgeBasePDF(document.header_text)
    pdf.set_margins(PDF_MARGIN_MM, PDF_TOP_MARGIN_MM, PDF_MARGIN_MM)
    pdf.set_auto_page_break(auto=True, margin=PDF_BOTTOM_MARGIN_MM)
    pdf.set_title(sanitize_latin1(front.title))
    pdf.set_subject(front.doc_id)
    pdf.set_keywords(sanitize_latin1(", ".join(front.topics)))
    pdf.set_author(ORGANIZATION_NAME)
    pdf.set_creator(GENERATOR)
    pdf.set_lang("en-US")
    pdf.set_creation_date(dt.datetime.combine(front.effective_date, dt.time(), tzinfo=dt.UTC))
    pdf.add_page()

    for block in document.blocks:
        if isinstance(block, HeadingBlock):
            _pdf_heading(pdf, block)
        elif isinstance(block, ParagraphBlock):
            _pdf_paragraph(pdf, block)
        elif isinstance(block, BulletBlock):
            _pdf_bullets(pdf, block)
        else:
            _pdf_table(pdf, block)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))


def _pdf_heading(pdf: FPDF, block: HeadingBlock) -> None:
    text = sanitize_latin1(block.display)
    if block.level == 1:
        pdf.set_font(PDF_FONT, style="B", size=PDF_TITLE_PT)
        pdf.multi_cell(0, 9, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)
        return
    size, line_height, space_before = (PDF_H2_PT, 7.0, 4.0) if block.level == 2 else (PDF_H3_PT, 6.0, 2.5)
    # Keep a heading together with the start of the text that follows it.
    if pdf.will_page_break(space_before + line_height + 12):
        pdf.add_page()
    else:
        pdf.ln(space_before)
    pdf.set_font(PDF_FONT, style="B", size=size)
    pdf.multi_cell(0, line_height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)


def _pdf_paragraph(pdf: FPDF, block: ParagraphBlock) -> None:
    if block.role == "meta":
        pdf.set_font(PDF_FONT, size=PDF_META_PT)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 4.5, sanitize_latin1(block.text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.set_draw_color(120, 120, 120)
        pdf.line(pdf.l_margin, pdf.get_y() + 1.5, pdf.w - pdf.r_margin, pdf.get_y() + 1.5)
        pdf.ln(4)
        return
    if block.role == "notice":
        pdf.set_font(PDF_FONT, style="B", size=PDF_BODY_PT)
        pdf.set_text_color(*NOTICE_RGB)
        pdf.set_draw_color(*NOTICE_RGB)
        pdf.multi_cell(0, 5.5, sanitize_latin1(strip_inline(block.text)), border=1, padding=2,
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)
        return
    if block.role == "hidden":
        pdf.set_font(PDF_FONT, size=2)
        pdf.set_text_color(255, 255, 255)
        pdf.multi_cell(0, 1, sanitize_latin1(strip_inline(block.text)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        return
    pdf.set_font(PDF_FONT, size=PDF_BODY_PT)
    pdf.multi_cell(0, 5, _pdf_markup(block.text), markdown=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)


def _pdf_bullets(pdf: FPDF, block: BulletBlock) -> None:
    pdf.set_font(PDF_FONT, size=PDF_BODY_PT)
    indent, marker_width = 3.0, 4.0
    for item in block.items:
        pdf.set_x(pdf.l_margin + indent)
        pdf.cell(marker_width, 5, "-")
        pdf.multi_cell(pdf.epw - indent - marker_width, 5, _pdf_markup(item), markdown=True,
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(0.8)
    pdf.ln(1.5)


def _pdf_table(pdf: FPDF, block: TableBlock) -> None:
    padding = 1.2
    widths = _pdf_column_widths(pdf, block, padding)
    pdf.set_font(PDF_FONT, size=PDF_TABLE_PT)
    pdf.set_draw_color(90, 90, 90)
    with pdf.table(
        col_widths=widths,
        width=pdf.epw,
        text_align="LEFT",
        line_height=pdf.font_size * 1.45,
        borders_layout="ALL",
        headings_style=FontFace(emphasis="BOLD", fill_color=(232, 232, 232)),
        padding=padding,
        first_row_as_headings=True,
    ) as table:
        for values in (block.header, *block.rows):
            row = table.row()
            for value in values:
                row.cell(sanitize_latin1(strip_inline(value)))
    pdf.ln(3)


# ---------------------------------------------------------------------------
# DOCX rendering (python-docx)
# ---------------------------------------------------------------------------

def render_docx(document: SourceDocument, out_path: Path) -> None:
    """Render a source to DOCX with python-docx (Title / Heading 1 / Heading 2 styles)."""
    word = docx.Document()
    _docx_page_setup(word, document.header_text)
    for block in document.blocks:
        if isinstance(block, HeadingBlock):
            if block.level == 1:
                word.add_paragraph(block.text, style="Title")
            else:
                word.add_heading(block.display, level=block.level - 1)
        elif isinstance(block, ParagraphBlock):
            _docx_paragraph(word, block)
        elif isinstance(block, BulletBlock):
            for item in block.items:
                _docx_add_runs(word.add_paragraph(style="List Bullet"), item)
        else:
            _docx_table(word, block)
    _docx_core_properties(word, document.front)
    buffer = io.BytesIO()
    word.save(buffer)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_reproducible_zip(buffer.getvalue(), document.front.effective_date))


def _docx_page_setup(word: Any, header_text: str) -> None:
    normal = word.styles["Normal"]
    normal.font.name = DOCX_FONT
    normal.font.size = Pt(DOCX_BODY_PT)
    section = word.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(20)
    section.top_margin = section.bottom_margin = Mm(20)

    header_paragraph = section.header.paragraphs[0]
    header_run = header_paragraph.add_run(header_text)
    header_run.font.size = Pt(8)
    header_run.font.color.rgb = RGBColor(0x5A, 0x5A, 0x5A)

    footer_paragraph = section.footer.paragraphs[0]
    footer_paragraph.alignment = 1  # centre
    for piece in ("Page ", ("PAGE",), " of ", ("NUMPAGES",)):
        if isinstance(piece, tuple):
            _docx_add_field(footer_paragraph, piece[0])
        else:
            run = footer_paragraph.add_run(piece)
            run.font.size = Pt(8)


def _docx_add_field(paragraph: DocxParagraph, instruction: str) -> None:
    """Append a Word field (e.g. PAGE, NUMPAGES) to a paragraph."""
    def element(tag: str, **attributes: str) -> Any:
        node = OxmlElement(tag)
        for name, value in attributes.items():
            node.set(qn(name), value)
        return node

    begin = paragraph.add_run()
    begin._r.append(element("w:fldChar", **{"w:fldCharType": "begin"}))
    code = paragraph.add_run()
    instr = element("w:instrText", **{"xml:space": "preserve"})
    instr.text = f" {instruction} "
    code._r.append(instr)
    separate = paragraph.add_run()
    separate._r.append(element("w:fldChar", **{"w:fldCharType": "separate"}))
    placeholder = paragraph.add_run("1")
    placeholder.font.size = Pt(8)
    end = paragraph.add_run()
    end._r.append(element("w:fldChar", **{"w:fldCharType": "end"}))


def _docx_add_runs(paragraph: DocxParagraph, text: str, size: float | None = None,
                   bold: bool = False, rgb: tuple[int, int, int] | None = None) -> None:
    for fragment, is_bold in split_bold(text):
        if not fragment:
            continue
        run = paragraph.add_run(fragment)
        run.bold = bold or is_bold
        if size is not None:
            run.font.size = Pt(size)
        if rgb is not None:
            run.font.color.rgb = RGBColor(*rgb)


def _docx_paragraph(word: Any, block: ParagraphBlock) -> None:
    paragraph = word.add_paragraph()
    if block.role == "meta":
        _docx_add_runs(paragraph, block.text, size=DOCX_META_PT, rgb=(0x3C, 0x3C, 0x3C))
    elif block.role == "notice":
        _docx_add_runs(paragraph, strip_inline(block.text), bold=True, rgb=NOTICE_RGB)
    elif block.role == "hidden":
        # Security samples only: text that a reader will not notice but a parser will extract.
        _docx_add_runs(paragraph, strip_inline(block.text), size=1, rgb=(0xFF, 0xFF, 0xFF))
    else:
        _docx_add_runs(paragraph, block.text)


def _docx_table(word: Any, block: TableBlock) -> None:
    table = word.add_table(rows=1 + len(block.rows), cols=len(block.header))
    table.style = "Table Grid"
    for row_index, values in enumerate((block.header, *block.rows)):
        row = table.rows[row_index]
        for column_index, value in enumerate(values):
            cell = row.cells[column_index]
            _docx_add_runs(cell.paragraphs[0], value, size=DOCX_TABLE_PT, bold=row_index == 0)
    # Repeat the header row on every page.
    header_properties = table.rows[0]._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    header_properties.append(repeat)
    word.add_paragraph()


def _docx_core_properties(word: Any, front: FrontMatter) -> None:
    stamp = dt.datetime.combine(front.effective_date, dt.time())
    properties = word.core_properties
    properties.title = front.title
    properties.subject = front.doc_id
    properties.keywords = ", ".join(front.topics)
    properties.comments = f"version={front.version};status={front.status};effective={front.effective_date.isoformat()}"
    properties.author = ORGANIZATION_NAME
    properties.last_modified_by = GENERATOR
    properties.category = front.doc_type
    properties.content_status = front.status
    properties.identifier = f"{front.doc_id}_v{front.version}"
    properties.version = front.version
    properties.language = "en-US"
    properties.revision = 1
    properties.created = stamp
    properties.modified = stamp
    properties.last_printed = stamp


def _reproducible_zip(data: bytes, when: dt.date) -> bytes:
    """Rewrite a DOCX package with fixed timestamps so rebuilds are byte-identical."""
    timestamp = (when.year, when.month, when.day, 0, 0, 0)
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=timestamp)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            target.writestr(entry, source.read(info.filename))
    return output.getvalue()


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(document: SourceDocument, out_path: Path) -> None:
    """Markdown documents are published as-is, front matter included."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(document.path, out_path)


RENDERERS: dict[str, Callable[[SourceDocument, Path], None]] = {
    "pdf": render_pdf,
    "docx": render_docx,
    "md": render_markdown,
}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def manifest_entry(document: SourceDocument, out_path: Path, base_dir: Path) -> dict[str, Any]:
    front = document.front
    data = out_path.read_bytes()
    return {
        "file": out_path.relative_to(base_dir).as_posix(),
        "doc_id": front.doc_id,
        "title": front.title,
        "doc_type": front.doc_type,
        "version": front.version,
        "status": front.status,
        "effective_date": front.effective_date,
        "expiry_date": front.expiry_date,
        "owner_department": front.owner_department,
        "topics": list(front.topics),
        "supersedes": front.supersedes,
        "superseded_by": front.superseded_by,
        "format": front.format,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def write_manifest(target: BuildTarget, documents: list[SourceDocument]) -> None:
    assert target.manifest_path is not None
    base_dir = target.manifest_path.parent
    entries = [manifest_entry(d, d.output_path(target.output_dir), base_dir) for d in documents]
    header = (
        f"# {target.label} manifest - generated by scripts/build_knowledge_base.py; do not edit by hand.\n"
        "# One entry per document version. 'file' is relative to this manifest's directory.\n"
    )
    body = yaml.safe_dump(entries, sort_keys=False, default_flow_style=None, width=140, allow_unicode=False)
    target.manifest_path.write_text(header + body, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Outcome of verifying one rendered file."""

    file: str
    fmt: str
    status: str
    units: str
    sections_found: int
    sections_total: int
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def verify_output(document: SourceDocument, out_path: Path) -> CheckResult:
    """Re-open a rendered file and confirm its text and section headings."""
    sections = document.sections
    result = CheckResult(rel(out_path), document.front.format, document.front.status, "-", 0, len(sections))
    if not out_path.is_file():
        result.errors.append("output file is missing")
        return result
    try:
        if document.front.format == "pdf":
            _verify_pdf(document, out_path, result)
        elif document.front.format == "docx":
            _verify_docx(document, out_path, result)
        else:
            _verify_markdown(document, out_path, result)
    except Exception as exc:
        result.errors.append(f"could not read file: {exc}")
    return result


def _check_headings_in_text(document: SourceDocument, text: str, result: CheckResult) -> None:
    """Every section heading, and the key (first) cell of every table row, must be extractable."""
    haystack = normalise(text)
    for section in document.sections:
        if normalise(section.display) in haystack:
            result.sections_found += 1
        else:
            result.errors.append(f"heading not found in extracted text: '{section.display}'")
    for block in document.blocks:
        if isinstance(block, TableBlock):
            for row in block.rows:
                if normalise(row[0]) not in haystack:
                    result.errors.append(f"table row key not found in extracted text: '{row[0]}'")


def _verify_pdf(document: SourceDocument, out_path: Path, result: CheckResult) -> None:
    with pymupdf.open(out_path) as pdf:
        pages = [page.get_text() for page in pdf]
        metadata = pdf.metadata or {}
    result.units = f"{len(pages)} pp"
    text = "\n".join(pages)
    if not text.strip():
        result.errors.append("no extractable text")
        return
    _check_headings_in_text(document, text, result)
    header = normalise(document.header_text)
    for number, page_text in enumerate(pages, start=1):
        page_text_n = normalise(page_text)
        if header not in page_text_n:
            result.errors.append(f"page {number}: running header missing")
        if f"page {number} of {len(pages)}" not in page_text_n:
            result.errors.append(f"page {number}: footer 'Page {number} of {len(pages)}' missing")
    if normalise(document.title) not in normalise(text):
        result.errors.append("title not found in extracted text")
    if metadata.get("title") != sanitize_latin1(document.front.title):
        result.errors.append(f"PDF metadata title is '{metadata.get('title')}'")
    if metadata.get("subject") != document.front.doc_id:
        result.errors.append(f"PDF metadata subject is '{metadata.get('subject')}'")
    if not metadata.get("keywords"):
        result.errors.append("PDF metadata keywords are empty")


def _verify_docx(document: SourceDocument, out_path: Path, result: CheckResult) -> None:
    word = docx.Document(str(out_path))
    paragraphs = [(p.style.name if p.style is not None else "", p.text) for p in word.paragraphs]
    table_text = [cell.text for table in word.tables for row in table.rows for cell in row.cells]
    result.units = f"{len(paragraphs)} paras"
    text = "\n".join([t for _, t in paragraphs] + table_text)
    if not text.strip():
        result.errors.append("no extractable text")
        return
    _check_headings_in_text(document, text, result)
    styled = {(style, text.strip()) for style, text in paragraphs}
    for section in document.sections:
        style = "Heading 1" if section.level == 2 else "Heading 2"
        if (style, section.display) not in styled:
            result.errors.append(f"heading '{section.display}' is not a '{style}' paragraph")
    if ("Title", document.title) not in styled:
        result.errors.append("title paragraph does not use the 'Title' style")
    heading_count = sum(1 for style, _ in paragraphs if style in ("Heading 1", "Heading 2"))
    if heading_count != len(document.sections):
        result.errors.append(f"{heading_count} heading paragraphs, expected {len(document.sections)}")
    properties = word.core_properties
    expected_comments = (
        f"version={document.front.version};status={document.front.status};"
        f"effective={document.front.effective_date.isoformat()}"
    )
    if properties.title != document.front.title or properties.subject != document.front.doc_id:
        result.errors.append("core properties title/subject do not match the front matter")
    if properties.comments != expected_comments:
        result.errors.append(f"core properties comments are '{properties.comments}'")
    if properties.keywords != ", ".join(document.front.topics):
        result.errors.append("core properties keywords do not match the topics")


def _verify_markdown(document: SourceDocument, out_path: Path, result: CheckResult) -> None:
    text = out_path.read_text(encoding="utf-8")
    result.units = f"{len(text.splitlines())} lines"
    if not text.strip():
        result.errors.append("file is empty")
        return
    if text != document.raw_text:
        result.errors.append("published Markdown differs from its source")
    lines = {line.strip() for line in text.splitlines()}
    for section in document.sections:
        marker = "##" if section.level == 2 else "###"
        if f"{marker} {section.display}" in lines:
            result.sections_found += 1
        else:
            result.errors.append(f"heading line not found: '{marker} {section.display}'")


def verify_manifest(target: BuildTarget, documents: list[SourceDocument]) -> list[str]:
    """Confirm that the manifest lists every document with the current hash and size."""
    if target.manifest_path is None:
        return []
    if not target.manifest_path.is_file():
        return [f"{rel(target.manifest_path)} is missing"]
    entries = yaml.safe_load(target.manifest_path.read_text(encoding="utf-8")) or []
    base_dir = target.manifest_path.parent
    by_file = {entry.get("file"): entry for entry in entries if isinstance(entry, dict)}
    errors: list[str] = []
    for document in documents:
        out_path = document.output_path(target.output_dir)
        key = out_path.relative_to(base_dir).as_posix()
        entry = by_file.pop(key, None)
        if entry is None:
            errors.append(f"manifest has no entry for {key}")
            continue
        if not out_path.is_file():
            continue
        expected = manifest_entry(document, out_path, base_dir)
        for name, value in expected.items():
            if entry.get(name) != value:
                errors.append(f"manifest entry {key}: '{name}' is {entry.get(name)!r}, expected {value!r}")
    errors.extend(f"manifest lists an unknown file: {name}" for name in by_file)
    return errors


# ---------------------------------------------------------------------------
# Source validation (structure, metadata line, kb_spec.yaml conformance)
# ---------------------------------------------------------------------------

@dataclass
class ReferenceData:
    """Configuration files the sources are validated against."""

    spec_documents: dict[str, dict[str, Any]]
    department_names: dict[str, str]
    subcategories: dict[str, tuple[str, str]]  # code -> (category name, subcategory name)
    routing_rules: list[dict[str, Any]]

    @classmethod
    def load(cls) -> ReferenceData:
        spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
        departments = yaml.safe_load(DEPARTMENTS_PATH.read_text(encoding="utf-8"))["departments"]
        taxonomy = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))["categories"]
        routing = yaml.safe_load(ROUTING_RULES_PATH.read_text(encoding="utf-8"))["routing_rules"]
        return cls(
            spec_documents={d["doc_id"]: d for d in spec["documents"]},
            department_names={d["code"]: d["name"] for d in departments},
            subcategories={
                sub["code"]: (category["name"], sub["name"])
                for category in taxonomy for sub in category["subcategories"]
            },
            routing_rules=routing,
        )


def lint_source(document: SourceDocument, reference: ReferenceData) -> tuple[list[str], list[str]]:
    """Structural checks that apply to every source. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    front = document.front
    expected_name = f"{document.stem}.md"
    if document.path.name != expected_name:
        errors.append(f"file name should be {expected_name}")
    if front.owner_department not in reference.department_names:
        errors.append(f"unknown owner_department {front.owner_department}")

    headings = [b for b in document.blocks if isinstance(b, HeadingBlock)]
    titles = [h for h in headings if h.level == 1]
    if len(titles) != 1 or document.blocks[0] != titles[0]:
        errors.append("the body must start with exactly one '# Title' heading")
    elif titles[0].text != front.title:
        errors.append(f"title heading '{titles[0].text}' differs from front matter '{front.title}'")

    metas = [b for b in document.blocks if isinstance(b, ParagraphBlock) and b.role == "meta"]
    expected_meta = expected_meta_line(front, reference.department_names)
    if not metas:
        errors.append("metadata line ('Document ID: ... | Owner: ...') is missing below the title")
    elif metas[0].text != expected_meta:
        errors.append(f"metadata line differs from front matter; expected: {expected_meta}")

    if front.status != "Active":
        keyword = STATUS_NOTICE_KEYWORDS[front.status]
        notices = [b.text for b in document.blocks if isinstance(b, ParagraphBlock) and b.role == "notice"]
        if not any(keyword in strip_inline(text) for text in notices):
            errors.append(f"a bold notice containing '{keyword}' is required under the metadata line")

    seen: set[str] = set()
    parent: str | None = None
    for section in document.sections:
        if section.section_id in seen:
            errors.append(f"duplicate section id {section.section_id}")
        seen.add(section.section_id)
        if section.level == 2:
            parent = section.section_id
        elif section.section_id.rsplit(".", 1)[0] != parent:
            errors.append(f"section {section.section_id} is not inside section {parent}")
    if not document.sections:
        errors.append("document has no sections")

    for line_no, line in enumerate(document.raw_text.splitlines(), start=1):
        odd = sorted({char for char in line if ord(char) > 126 or (ord(char) < 32 and char != "\t")})
        if odd:
            codes = ", ".join(f"U+{ord(char):04X}" for char in odd)
            warnings.append(f"line {line_no}: non-ASCII characters {codes} (sanitised for PDF)")
    return errors, warnings


def validate_against_spec(documents: list[SourceDocument], reference: ReferenceData) -> dict[str, list[str]]:
    """Validate the knowledge-base sources against kb_spec.yaml. Returns errors keyed by source."""
    problems: dict[str, list[str]] = {}
    expected_versions = {
        (doc_id, str(version["version"]))
        for doc_id, spec in reference.spec_documents.items() for version in spec["versions"]
    }
    present = {(d.front.doc_id, d.front.version) for d in documents}
    for doc_id, version in sorted(expected_versions - present):
        problems.setdefault("kb_spec.yaml", []).append(f"no source for {doc_id} v{version}")
    for doc_id, version in sorted(present - expected_versions):
        problems.setdefault("kb_spec.yaml", []).append(f"{doc_id} v{version} is not in the spec")

    for document in documents:
        spec = reference.spec_documents.get(document.front.doc_id)
        if spec is None:
            continue
        errors = problems.setdefault(document.path.name, [])
        errors.extend(_compare_front_matter(document, spec))
        errors.extend(_compare_sections(document, spec))
        if document.front.status == "Active":
            errors.extend(_check_must_state(document, spec, reference))
    return {name: errs for name, errs in problems.items() if errs}


def _spec_version(spec: dict[str, Any], version: str) -> dict[str, Any] | None:
    return next((v for v in spec["versions"] if str(v["version"]) == version), None)


def _compare_front_matter(document: SourceDocument, spec: dict[str, Any]) -> list[str]:
    front = document.front
    version = _spec_version(spec, front.version)
    if version is None:
        return []
    expected: dict[str, Any] = {
        "title": spec["title"],
        "doc_type": spec["doc_type"],
        "owner_department": spec["owner"],
        "topics": tuple(spec["topics"]),
        "status": version["status"],
        "effective_date": version["effective_date"],
        "expiry_date": version.get("expiry_date"),
        "format": version["format"],
        "supersedes": version.get("supersedes"),
        "superseded_by": version.get("superseded_by"),
    }
    return [
        f"front matter '{name}' is {getattr(front, name)!r}, spec says {value!r}"
        for name, value in expected.items() if getattr(front, name) != value
    ]


def _compare_sections(document: SourceDocument, spec: dict[str, Any]) -> list[str]:
    """Active versions must match the spec exactly; older versions reuse its numbering."""
    expected = [(str(s["id"]), str(s["heading"])) for s in spec["sections"]]
    actual = [(s.section_id, s.heading) for s in document.sections]
    has_active = any(v["status"] == "Active" for v in spec["versions"])
    if document.front.status == "Active" or not has_active:
        if actual == expected:
            return []
        missing = [f"{i} {h}" for i, h in expected if (i, h) not in actual]
        extra = [f"{i} {h}" for i, h in actual if (i, h) not in expected]
        detail = "; ".join(filter(None, [
            f"missing: {', '.join(missing)}" if missing else "",
            f"unexpected: {', '.join(extra)}" if extra else "",
            "order differs" if not missing and not extra else "",
        ]))
        return [f"sections do not match kb_spec.yaml ({detail})"]
    order = [section_id for section_id, _ in expected]
    ids = [section_id for section_id, _ in actual]
    unknown = [section_id for section_id in ids if section_id not in order]
    if unknown:
        return [f"section ids {', '.join(unknown)} are not part of the active version's numbering"]
    if ids != sorted(ids, key=order.index):
        return ["section ids are not in the active version's order"]
    return []


def _check_must_state(document: SourceDocument, spec: dict[str, Any], reference: ReferenceData) -> list[str]:
    errors: list[str] = []
    sections = {s.section_id: s for s in document.sections}
    for spec_section in spec["sections"]:
        section_id = str(spec_section["id"])
        section = sections.get(section_id)
        if section is None:
            continue
        special = SPECIAL_SECTION_CHECKS.get((document.front.doc_id, section_id))
        if special is not None:
            errors.extend(special(section, reference))
            continue
        text = normalise(section.plain_text)
        for fact in spec_section.get("must_state", []):
            if normalise(fact).rstrip(".") not in text:
                errors.append(f"section {section_id}: must state '{fact}'")
    return errors


def _check_routing_table(section: Section, reference: ReferenceData) -> list[str]:
    """RTE-RUL-14 section 3 must reproduce routing_rules.yaml exactly, with names and codes."""
    tables = [b for b in section.blocks if isinstance(b, TableBlock)]
    if len(tables) != 1:
        return ["section 3: expected exactly one routing table"]
    table = tables[0]
    expected_header = ("Rule ID", "Category", "Subcategory", "Primary department", "Supporting departments")
    errors: list[str] = []
    if table.header != expected_header:
        errors.append(f"section 3: routing table header should be {' | '.join(expected_header)}")

    def department(code: str) -> str:
        return f"{reference.department_names[code]} ({code})"

    expected_rows = []
    for rule in reference.routing_rules:
        category, subcategory = reference.subcategories[rule["subcategory"]]
        supporting = "; ".join(department(code) for code in rule["supporting_departments"]) or "None"
        expected_rows.append((
            rule["rule_id"], category, f"{rule['subcategory']} {subcategory}",
            department(rule["primary_department"]), supporting,
        ))
    if len(table.rows) != len(expected_rows):
        errors.append(f"section 3: routing table has {len(table.rows)} rows, routing_rules.yaml has {len(expected_rows)}")
    for actual, expected in zip(table.rows, expected_rows, strict=False):  # length mismatch reported above
        if tuple(strip_inline(cell) for cell in actual) != expected:
            errors.append(f"section 3: row {' | '.join(actual)} should be {' | '.join(expected)}")
    return errors


SPECIAL_SECTION_CHECKS: dict[tuple[str, str], Callable[[Section, ReferenceData], list[str]]] = {
    ("RTE-RUL-14", "3"): _check_routing_table,
}


def validate_revisions(documents: list[SourceDocument], reference: ReferenceData) -> dict[str, list[str]]:
    """New versions of known documents (hidden pack) must keep the spec's section structure."""
    problems: dict[str, list[str]] = {}
    for document in documents:
        spec = reference.spec_documents.get(document.front.doc_id)
        if spec is None:
            continue
        expected = [(str(s["id"]), str(s["heading"])) for s in spec["sections"]]
        actual = [(s.section_id, s.heading) for s in document.sections]
        if actual != expected:
            problems[document.path.name] = ["sections differ from the structure defined in kb_spec.yaml"]
    return problems


# ---------------------------------------------------------------------------
# Orchestration and reporting
# ---------------------------------------------------------------------------

def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def build_target(target: BuildTarget, documents: list[SourceDocument]) -> None:
    target.output_dir.mkdir(parents=True, exist_ok=True)
    for document in documents:
        RENDERERS[document.front.format](document, document.output_path(target.output_dir))
    if target.manifest_path is not None:
        write_manifest(target, documents)
    print(f"[build] {target.label}: rendered {len(documents)} file(s) into {rel(target.output_dir)}/")


def check_target(target: BuildTarget, documents: list[SourceDocument],
                 reference: ReferenceData) -> tuple[list[CheckResult], list[str]]:
    """Verify one target. Returns per-file results and target-level errors."""
    target_errors: list[str] = []
    warnings: list[str] = []
    for document in documents:
        errors, lint_warnings = lint_source(document, reference)
        target_errors.extend(f"{document.path.name}: {message}" for message in errors)
        warnings.extend(f"{document.path.name}: {message}" for message in lint_warnings)
    spec_problems = (validate_against_spec(documents, reference) if target.validate_against_spec
                     else validate_revisions(documents, reference))
    for name, messages in spec_problems.items():
        target_errors.extend(f"{name}: {message}" for message in messages)
    target_errors.extend(verify_manifest(target, documents))
    results = [verify_output(d, d.output_path(target.output_dir)) for d in documents]
    for message in warnings:
        print(f"[warn]  {message}")
    return results, target_errors


def print_summary(label: str, results: list[CheckResult], target_errors: list[str]) -> None:
    print()
    print(f"== {label}: verification ==")
    width = max([len(r.file) for r in results] + [4])
    print(f"{'FILE':<{width}}  {'FMT':<4}  {'STATUS':<10}  {'SIZE':<10}  {'SECTIONS':>8}  RESULT")
    for r in results:
        sections = f"{r.sections_found}/{r.sections_total}"
        print(f"{r.file:<{width}}  {r.fmt:<4}  {r.status:<10}  {r.units:<10}  {sections:>8}  "
              f"{'PASS' if r.ok else 'FAIL'}")
        for error in r.errors:
            print(f"    - {error}")
    if target_errors:
        print("Source / spec / manifest problems:")
        for error in target_errors:
            print(f"    - {error}")
    passed = sum(r.ok for r in results)
    print(f"{passed}/{len(results)} files passed; {len(target_errors)} source/spec/manifest problem(s).")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the Lumora knowledge base (PDF/DOCX/MD), write manifests and verify the output.")
    parser.add_argument("--target", choices=["all", *TARGETS], default="all",
                        help="which document set to process (default: all)")
    parser.add_argument("--check", action="store_true",
                        help="verify existing outputs without rebuilding them")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    selected = list(TARGETS.values()) if args.target == "all" else [TARGETS[args.target]]
    reference = ReferenceData.load()
    failed = False
    for target in selected:
        try:
            documents = load_sources(target)
        except SourceError as exc:
            print(f"[error] {target.label}: {exc}")
            failed = True
            continue
        if not args.check:
            build_target(target, documents)
        results, target_errors = check_target(target, documents, reference)
        print_summary(target.label, results, target_errors)
        failed = failed or bool(target_errors) or not all(r.ok for r in results)
    print()
    print("RESULT: FAIL" if failed else "RESULT: PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
