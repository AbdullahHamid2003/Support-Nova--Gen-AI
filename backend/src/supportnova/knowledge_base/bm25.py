"""Okapi BM25 lexical index with an inverted index (scales to tens of thousands of chunks)."""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from supportnova.complaint_processing.text import content_tokens


class BM25:
    def __init__(self, documents: list[str], *, k1: float = 1.4, b: float = 0.72) -> None:
        self.k1, self.b = k1, b
        self.n = len(documents)
        self.lengths: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for idx, text in enumerate(documents):
            counts = Counter(content_tokens(text))
            self.lengths.append(sum(counts.values()))
            for term, tf in counts.items():
                self.postings[term].append((idx, tf))
        self.avgdl = (sum(self.lengths) / self.n) if self.n else 0.0
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def scores(self, query: str) -> list[float]:
        out = [0.0] * self.n
        for term in set(content_tokens(query)):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for idx, tf in self.postings[term]:
                denom = tf + self.k1 * (1 - self.b + self.b * self.lengths[idx] / (self.avgdl or 1))
                out[idx] += idf * tf * (self.k1 + 1) / denom
        return out
