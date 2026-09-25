"""Shared lexical utilities: tokenisation, light stemming, phrase matching with negation."""

from __future__ import annotations

import re
from functools import lru_cache

_TOKEN = re.compile(r"[a-z0-9]+(?:['+][a-z0-9]+)*")
STOPWORDS = frozenset(
    "a an the and or but if then so of to in on at for from by with about into over after before under again "
    "is are was were be been being am do does did doing have has had having i me my mine we our ours you your "
    "yours he him his she her they them their it its this that these those there here what which who whom "
    "when where why how all any both each few more most other some such no nor not only own same than too very "
    "can will just should would could may might must shall also as up down out off".split()
)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


@lru_cache(maxsize=65536)
def stem(word: str) -> str:
    """Tiny suffix-stripping stemmer (deterministic, dependency-free)."""
    w = word
    if len(w) <= 4:
        return w
    for suffix, repl in (("ational", "ate"), ("ization", "ize"), ("iveness", "ive"), ("fulness", "ful"),
                         ("ousness", "ous"), ("ements", "e"), ("ement", "e"), ("ments", ""), ("ment", ""),
                         ("ingly", ""), ("edly", ""), ("ing", ""), ("ies", "y"), ("ied", "y"), ("ers", "er"),
                         ("ed", ""), ("es", ""), ("ly", ""), ("s", "")):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: len(w) - len(suffix)] + repl
            break
    return w


def content_tokens(text: str) -> list[str]:
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]


@lru_cache(maxsize=8192)
def phrase_regex(phrase: str) -> re.Pattern[str]:
    """Word-boundary regex for a lexicon phrase; tolerant to punctuation/hyphen spacing."""
    parts = [re.escape(p) for p in re.split(r"[\s-]+", phrase.strip().lower()) if p]
    body = r"[\s-]+".join(parts)
    prefix = r"(?<![a-z0-9])" if phrase[:1].isalnum() else ""
    suffix = r"(?![a-z0-9])" if phrase[-1:].isalnum() else ""
    return re.compile(prefix + body + suffix)


def find_phrase(text_lower: str, phrase: str, negation_cues: frozenset[str] = frozenset(),
                negation_window: int = 3) -> list[tuple[int, int]]:
    """Return non-negated occurrences (start, end) of ``phrase`` in lower-cased text."""
    hits: list[tuple[int, int]] = []
    for m in phrase_regex(phrase).finditer(text_lower):
        if negation_cues:
            preceding = _TOKEN.findall(text_lower[max(0, m.start() - 60):m.start()])[-negation_window:]
            if any(tok in negation_cues for tok in preceding):
                continue
        hits.append((m.start(), m.end()))
    return hits
