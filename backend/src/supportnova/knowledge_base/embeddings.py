"""Embedding providers for semantic retrieval and near-duplicate detection.

* ``local`` (default): deterministic feature-hashing embedder (stemmed unigrams, bigrams and
  character trigrams, signed hashing, log-TF, L2-normalised). No model download, no API key,
  identical results on every machine. It is NOT a neural model; it is a classic IR technique.
* ``openai`` / ``gemini``: provider embeddings when EMBEDDING_PROVIDER and a key are configured.
Vectors are stored as float32 bytes; the model name is stored with each vector so a model change
triggers re-embedding.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from typing import Protocol

import httpx
import numpy as np

from supportnova.complaint_processing.text import STOPWORDS, stem, tokenize
from supportnova.core.config import get_settings
from supportnova.core.errors import RetrievalError


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _h(feature: str) -> int:
    return int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "little")


class LocalHashingEmbedder:
    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.name = f"local-hash-v1-{dim}"

    def _features(self, text: str) -> dict[str, float]:
        tokens = [t for t in tokenize(text) if t not in STOPWORDS]
        stems = [stem(t) for t in tokens]
        feats: dict[str, float] = {}
        for s in stems:
            feats["u:" + s] = feats.get("u:" + s, 0.0) + 1.0
        for a, b in itertools.pairwise(stems):
            key = f"b:{a}_{b}"
            feats[key] = feats.get(key, 0.0) + 0.8
        for t in tokens:
            padded = f"#{t}#"
            for i in range(len(padded) - 2):
                key = "c:" + padded[i:i + 3]
                feats[key] = feats.get(key, 0.0) + 0.25
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for feat, tf in self._features(text).items():
                h = _h(feat)
                idx = h % self.dim
                sign = 1.0 if (h >> 63) & 1 else -1.0
                out[row, idx] += sign * (1.0 + math.log(tf)) if tf >= 1 else sign * tf
            norm = float(np.linalg.norm(out[row]))
            if norm > 0:
                out[row] /= norm
        return out


class OpenAIEmbedder:  # pragma: no cover - requires a key; request/response shape covered by fake-transport tests
    def __init__(self, api_key: str, model: str | None = None, base_url: str | None = None) -> None:
        self.model = model or "text-embedding-3-small"
        self.name = f"openai:{self.model}"
        self.dim = 1536
        self._key = api_key
        self._url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/embeddings"

    def embed(self, texts: list[str]) -> np.ndarray:
        try:
            resp = httpx.post(self._url, headers={"Authorization": f"Bearer {self._key}"},
                              json={"model": self.model, "input": texts}, timeout=30)
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise RetrievalError(f"Embedding provider error: {exc}") from exc
        arr = np.array([d["embedding"] for d in data], dtype=np.float32)
        self.dim = arr.shape[1]
        return arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9)


class GeminiEmbedder:  # pragma: no cover - requires a key
    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.model = model or "text-embedding-004"
        self.name = f"gemini:{self.model}"
        self.dim = 768
        self._key = api_key

    def embed(self, texts: list[str]) -> np.ndarray:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"
        body = {"requests": [{"model": f"models/{self.model}", "content": {"parts": [{"text": t}]}} for t in texts]}
        try:
            resp = httpx.post(url, params={"key": self._key}, json=body, timeout=30)
            resp.raise_for_status()
            arr = np.array([e["values"] for e in resp.json()["embeddings"]], dtype=np.float32)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise RetrievalError(f"Embedding provider error: {exc}") from exc
        self.dim = arr.shape[1]
        return arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9)


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Configured embedder. Falls back to the local embedder when no key is configured."""
    global _embedder
    if _embedder is None:
        s = get_settings()
        key = (s.embedding_api_key or s.ai_api_key)
        if s.embedding_provider == "openai" and key:
            _embedder = OpenAIEmbedder(key.get_secret_value(), s.embedding_model, s.ai_base_url)
        elif s.embedding_provider == "gemini" and key:
            _embedder = GeminiEmbedder(key.get_secret_value(), s.embedding_model)
        else:
            _embedder = LocalHashingEmbedder()
    return _embedder


_similarity_embedder = LocalHashingEmbedder(dim=512)


def similarity_vectors(texts: list[str]) -> np.ndarray:
    """Local vectors used for duplicate / repeat detection (always local and deterministic)."""
    return _similarity_embedder.embed(texts)


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(blob: bytes | None) -> np.ndarray | None:
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32)
