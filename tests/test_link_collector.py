from __future__ import annotations

import json
import shutil
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools import link_collector


class LinkCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = REPO_ROOT / ".test-link-collector"
        shutil.rmtree(self.root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_canonicalizes_and_removes_tracking_parameters(self) -> None:
        canonical = link_collector.canonicalize_url(
            "HTTPS://Example.COM:443/article?utm_source=tg&b=2&a=1#fragment"
        )
        self.assertEqual(canonical, "https://example.com/article?a=1&b=2")

    def test_rejects_private_network_targets(self) -> None:
        private_resolution = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ]
        with mock.patch("socket.getaddrinfo", return_value=private_resolution):
            result = link_collector.archive_link("https://internal.example", root=self.root)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(result["archived"])
        self.assertFalse(result["indexed"])

    def test_archives_with_provenance_without_false_index_claim(self) -> None:
        fetched = {
            "requested_url": "https://example.com/article",
            "final_url": "https://example.com/article",
            "http_status": 200,
            "content_type": "text/html",
            "charset": "utf-8",
            "etag": '"abc"',
            "last_modified": None,
            "html_bytes": (
                b"<html lang='en'><head><title>Example Article</title>"
                b"<meta name='author' content='Hans'></head>"
                b"<body><article><h1>Example Article</h1><p>Durable knowledge.</p>"
                b"<script>ignore me</script></article></body></html>"
            ),
        }
        public_resolution = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        with mock.patch("socket.getaddrinfo", return_value=public_resolution):
            result = link_collector.archive_link(
                "https://example.com/article?utm_source=telegram",
                "Hans sent this from Telegram.",
                root=self.root,
                fetcher=lambda _url: fetched,
                indexer=lambda _root, _chunks, _manifest: {
                    "indexed": False,
                    "status": "unavailable",
                    "error": "test index unavailable",
                },
            )

        self.assertEqual(result["status"], "archived_not_indexed")
        self.assertTrue(result["archived"])
        self.assertFalse(result["indexed"])
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["canonical_url"], "https://example.com/article")
        self.assertEqual(manifest["capture_source"], "telegram_collector")
        self.assertEqual(manifest["index_status"], "unavailable")
        self.assertTrue(Path(result["raw_html_path"]).is_file())
        self.assertTrue(Path(result["raw_metadata_path"]).is_file())
        text = Path(result["extracted_text_path"]).read_text(encoding="utf-8")
        self.assertIn("Hans sent this from Telegram.", text)
        self.assertIn("Durable knowledge.", text)
        self.assertNotIn("ignore me", text)

    def test_duplicate_adds_capture_context_without_refetching(self) -> None:
        fetched = {
            "requested_url": "https://example.com/",
            "final_url": "https://example.com/",
            "http_status": 200,
            "content_type": "text/html",
            "charset": "utf-8",
            "etag": None,
            "last_modified": None,
            "html_bytes": b"<html><title>Example</title><body>Reusable text.</body></html>",
        }
        public_resolution = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        indexer = lambda _root, _chunks, _manifest: {
            "indexed": True,
            "status": "verified",
            "table": "library_chunks",
            "indexed_at": "2026-08-13T00:00:00+00:00",
        }
        with mock.patch("socket.getaddrinfo", return_value=public_resolution):
            first = link_collector.archive_link(
                "https://example.com",
                "first",
                root=self.root,
                fetcher=lambda _url: fetched,
                indexer=indexer,
            )
            second = link_collector.archive_link(
                "https://example.com/?utm_campaign=again",
                "second",
                root=self.root,
                fetcher=mock.Mock(side_effect=AssertionError("duplicate refetched")),
                indexer=indexer,
            )

        self.assertTrue(first["indexed"])
        self.assertEqual(second["status"], "duplicate_indexed")
        self.assertTrue(second["duplicate"])
        manifest = json.loads(Path(second["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual([item["capture_context"] for item in manifest["captures"]], ["first", "second"])

    def test_empty_html_is_archived_but_not_indexed(self) -> None:
        fetched = {
            "requested_url": "https://example.com/empty",
            "final_url": "https://example.com/empty",
            "http_status": 200,
            "content_type": "text/html",
            "charset": "utf-8",
            "etag": None,
            "last_modified": None,
            "html_bytes": b"<html><head><title>Empty</title></head><body><script>only script</script></body></html>",
        }
        public_resolution = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        indexer = mock.Mock(side_effect=AssertionError("empty HTML was indexed"))
        with mock.patch("socket.getaddrinfo", return_value=public_resolution):
            result = link_collector.archive_link(
                "https://example.com/empty",
                root=self.root,
                fetcher=lambda _url: fetched,
                indexer=indexer,
            )

        self.assertEqual(result["status"], "archived_not_indexed")
        self.assertFalse(result["extracted"])
        self.assertFalse(result["indexed"])
        indexer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
