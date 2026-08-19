#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/embed"
DEFAULT_TIMEOUT_SECONDS = 60.0


class OllamaEmbeddingError(RuntimeError):
    pass


class OllamaEmbedder:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        endpoint: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.model = model
        self.endpoint = endpoint or os.environ.get("OLLAMA_EMBED_ENDPOINT", DEFAULT_ENDPOINT)
        self.timeout_seconds = timeout_seconds or float(
            os.environ.get("OLLAMA_EMBED_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        )

    def encode(
        self,
        texts: list[str],
        prefix: str,
        batch_size: int | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise OllamaEmbeddingError("Embedding input must contain non-empty strings")

        effective_batch_size = batch_size or int(os.environ.get("OLLAMA_EMBED_BATCH_SIZE", "32"))
        if effective_batch_size < 1:
            raise OllamaEmbeddingError("OLLAMA_EMBED_BATCH_SIZE must be positive")
        normalized: list[list[float]] = []
        for start in range(0, len(texts), effective_batch_size):
            normalized.extend(self._encode_batch(texts[start : start + effective_batch_size], prefix))
        return normalized

    def _encode_batch(self, texts: list[str], prefix: str) -> list[list[float]]:
        payload = {"model": self.model, "input": [f"{prefix}: {text}" for text in texts]}
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise OllamaEmbeddingError(
                f"Ollama embedding request failed with HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise OllamaEmbeddingError(f"Ollama embedding request failed: {exc}") from exc

        try:
            result: Any = json.loads(body)
            vectors = result["embeddings"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OllamaEmbeddingError("Ollama returned an invalid embedding response") from exc

        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise OllamaEmbeddingError("Ollama returned an unexpected embedding count")

        normalized: list[list[float]] = []
        dimension: int | None = None
        for vector in vectors:
            if not isinstance(vector, list) or not vector:
                raise OllamaEmbeddingError("Ollama returned an empty embedding vector")
            values = [float(value) for value in vector]
            if not all(math.isfinite(value) for value in values):
                raise OllamaEmbeddingError("Ollama returned a non-finite embedding value")
            if dimension is None:
                dimension = len(values)
            elif len(values) != dimension:
                raise OllamaEmbeddingError("Ollama returned inconsistent embedding dimensions")
            norm = math.sqrt(sum(value * value for value in values))
            if norm == 0:
                raise OllamaEmbeddingError("Ollama returned a zero-length embedding vector")
            normalized.append([value / norm for value in values])
        return normalized
