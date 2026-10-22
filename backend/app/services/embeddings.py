"""Embedding providers behind one interface.

* HashEmbedder (default, offline): signed feature hashing of word / CJK-bigram tokens and
  character trigrams. It is a *lexical* vector model — it captures term and sub-word overlap,
  not deep semantics. It exists so the full pipeline runs without network access or API keys.
* OpenAICompatibleEmbedder: any /v1/embeddings endpoint (OpenAI, Azure-compatible gateways,
  local servers such as vLLM / Ollama's OpenAI shim).
"""
from __future__ import annotations

import hashlib
import logging
import math
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.services.text_utils import normalize, tokenize

log = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = f"hash-lexical-v1-{dim}"

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        n = int.from_bytes(h, "little")
        return n % self.dim, (1.0 if (n >> 63) & 1 else -1.0)

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        counts: dict[str, float] = {}
        for tok in tokenize(text):
            counts[f"t:{tok}"] = counts.get(f"t:{tok}", 0) + 1.0
        flat = "".join(ch for ch in normalize(text).lower() if not ch.isspace())
        for i in range(len(flat) - 2):
            g = f"g:{flat[i:i + 3]}"
            counts[g] = counts.get(g, 0) + 0.3
        for feat, c in counts.items():
            idx, sign = self._bucket(feat)
            vec[idx] += sign * (1.0 + math.log(c)) if c >= 1 else sign * c
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class OpenAICompatibleEmbedder:
    def __init__(self, settings: Settings):
        if not settings.embedding_api_key:
            raise EmbeddingError("EMBEDDING_PROVIDER=openai 但未设置 EMBEDDING_API_KEY")
        self.settings = settings
        self.dim = settings.embedding_dim
        self.name = f"openai:{settings.embedding_model}:{settings.embedding_dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        url = self.settings.embedding_base_url.rstrip("/") + "/embeddings"
        headers = {"Authorization": f"Bearer {self.settings.embedding_api_key}"}
        for i in range(0, len(texts), 64):
            batch = texts[i : i + 64]
            body = {"model": self.settings.embedding_model, "input": batch, "dimensions": self.dim}
            try:
                resp = httpx.post(url, json=body, headers=headers, timeout=60)
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"Embedding 接口网络错误：{type(exc).__name__}") from exc
            if resp.status_code != 200:
                # Never log headers (contain the key); the body is the provider's error message.
                raise EmbeddingError(f"Embedding 接口返回 HTTP {resp.status_code}: {resp.text[:300]}")
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        return out


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        s = get_settings()
        if s.embedding_provider == "hash":
            _embedder = HashEmbedder(s.embedding_dim)
        elif s.embedding_provider == "openai":
            _embedder = OpenAICompatibleEmbedder(s)
        else:
            raise EmbeddingError(f"未知的 EMBEDDING_PROVIDER: {s.embedding_provider}")
    return _embedder


def set_embedder(embedder: Embedder | None):
    global _embedder
    _embedder = embedder
