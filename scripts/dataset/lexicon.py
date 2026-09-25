"""Lexical signal detector for the dataset coherence self-check.

This is a deliberately *simple* reading of ``rules/complaint_rules/signals.yaml``
(word-boundary term matching with the configured negation window, plus the
configured regular expressions). It is used only to check that every signal a
scenario DECLARES is really expressed in the rendered complaint text, and to
report lexical hits that were not declared. Expected labels never come from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .common import SIGNALS_PATH
from .textutil import normalize

_WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class _Signal:
    name: str
    terms: tuple[tuple[str, re.Pattern[str]], ...]
    patterns: tuple[re.Pattern[str], ...]


class SignalDetector:
    """Detect signals from ``signals.yaml`` in free text."""

    def __init__(self, path: Path = SIGNALS_PATH) -> None:
        with path.open("r", encoding="utf-8") as handle:
            spec: dict[str, Any] = yaml.safe_load(handle)
        # YAML 1.1 parses an unquoted ``no`` as boolean False; map it back to the intended cue word.
        self.negation_cues = {("no" if c is False else "yes" if c is True else str(c).lower())
                              for c in spec.get("negation_cues", [])}
        self.window = int(spec.get("negation_window", 3))
        self.signals: dict[str, _Signal] = {}
        for name, body in (spec.get("signals") or {}).items():
            terms = tuple(
                (str(t).lower(), re.compile(r"(?<![a-z0-9])" + re.escape(str(t).lower()) + r"(?![a-z0-9])"))
                for t in body.get("terms", []) or []
            )
            patterns = tuple(re.compile(p, re.IGNORECASE | re.DOTALL) for p in body.get("patterns", []) or [])
            self.signals[name] = _Signal(name, terms, patterns)

    @property
    def names(self) -> set[str]:
        return set(self.signals)

    def _negated(self, text: str, start: int) -> bool:
        before = _WORD_RE.findall(text[:start])[-self.window:]
        return any(tok in self.negation_cues for tok in before)

    def occurrences(self, text: str, name: str) -> list[tuple[str, bool]]:
        """Every (matched text, negated?) occurrence of ``name``; patterns are never negated."""
        sig = self.signals.get(name)
        if sig is None:
            return []
        norm = normalize(text)
        found: list[tuple[str, bool]] = []
        for term, regex in sig.terms:
            for match in regex.finditer(norm):
                found.append((term, self._negated(norm, match.start())))
        for pattern in sig.patterns:
            hit = pattern.search(norm)
            if hit:
                found.append((hit.group(0), False))
        return found

    def evidence(self, text: str, name: str) -> str | None:
        """Matched term/pattern for ``name`` (non-negated occurrences only), or ``None``."""
        for term, negated in self.occurrences(text, name):
            if not negated:
                return term
        return None

    def found(self, text: str, name: str) -> bool:
        """Present in a non-negated position (the runtime lexicon's reading)."""
        return self.evidence(text, name) is not None

    def found_any(self, text: str, name: str) -> bool:
        """Present at all, even if only inside a negation window."""
        return bool(self.occurrences(text, name))

    def detect(self, text: str) -> set[str]:
        """All signals lexically present in ``text``."""
        return {name for name in self.signals if self.found(text, name)}
