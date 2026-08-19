from __future__ import annotations

import json
import sys
import urllib.error
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knowledge" / "layer"))

from ollama_embeddings import OllamaEmbedder, OllamaEmbeddingError


class OllamaEmbeddingTests(unittest.TestCase):
    def _response(self, payload: dict) -> mock.Mock:
        response = mock.Mock()
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        response.read.return_value = json.dumps(payload).encode("utf-8")
        return response

    def test_batches_and_normalizes_vectors(self) -> None:
        response = self._response({"embeddings": [[3.0, 4.0], [0.0, 2.0]]})
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            vectors = OllamaEmbedder(endpoint="http://ollama.test/api/embed").encode(
                ["one", "two"],
                "search_document",
                batch_size=2,
            )

        self.assertEqual(vectors, [[0.6, 0.8], [0.0, 1.0]])
        self.assertEqual(urlopen.call_count, 1)

    def test_surfaces_ollama_http_failure(self) -> None:
        error = urllib.error.HTTPError(
            "http://ollama.test/api/embed",
            404,
            "not found",
            {},
            BytesIO(b'{"error":"model not found"}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(OllamaEmbeddingError, "HTTP 404"):
                OllamaEmbedder(endpoint="http://ollama.test/api/embed").encode(["text"], "search_query")

    def test_rejects_inconsistent_dimensions(self) -> None:
        response = self._response({"embeddings": [[1.0, 0.0], [1.0, 0.0, 0.0]]})
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(OllamaEmbeddingError, "inconsistent embedding dimensions"):
                OllamaEmbedder(endpoint="http://ollama.test/api/embed").encode(["one", "two"], "search_query")


if __name__ == "__main__":
    unittest.main()
