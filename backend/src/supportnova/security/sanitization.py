"""Input normalisation and sanitisation (SRS Step 11: whitespace/character normalisation, sanitisation).

The ORIGINAL submitted text is always stored unchanged; these functions produce the
normalised copy that is analysed. Output rendering is escaped by the React frontend.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata

# Zero-width and bidi-control characters are a common way to hide instructions from humans.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿­]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAGS = re.compile(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>|<[^>]{1,200}>", re.IGNORECASE | re.DOTALL)
_SPACES = re.compile(r"[ \t  - 　]+")
_NEWLINES = re.compile(r"\n{3,}")
_PUNCT_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-", "…": "...", "´": "'", "ʼ": "'",
})


def count_invisible(text: str) -> int:
    return len(_INVISIBLE.findall(text or ""))


def normalize_text(text: str | None) -> str:
    """NFKC normalisation, invisible/control character removal, HTML stripping, whitespace collapse."""
    if not text:
        return ""
    value = unicodedata.normalize("NFKC", text)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _INVISIBLE.sub("", value)
    value = _CONTROL.sub("", value)
    value = html.unescape(value)
    value = _TAGS.sub(" ", value)
    value = value.translate(_PUNCT_MAP)
    value = _SPACES.sub(" ", value)
    value = "\n".join(line.strip() for line in value.split("\n"))
    value = _NEWLINES.sub("\n\n", value)
    return value.strip()


def canonical_for_hash(text: str) -> str:
    """Aggressively normalised form for exact-duplicate detection."""
    value = normalize_text(text).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(canonical_for_hash(text).encode("utf-8")).hexdigest()


_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, *, max_length: int = 120) -> str:
    """Strip directories and unsafe characters (prevents path traversal)."""
    base = (name or "file").replace("\\", "/").split("/")[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = _FILENAME_SAFE.sub("_", base).strip("._") or "file"
    if len(base) > max_length:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: max_length - len(ext) - 1] + "." + ext) if dot else base[:max_length]
    return base
