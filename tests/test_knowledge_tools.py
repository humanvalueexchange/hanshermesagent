from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import knowledge


class KnowledgeToolTests(unittest.TestCase):
    def _patch_exists(self, existing: set[Path]) -> mock._patch:
        return mock.patch(
            "pathlib.Path.exists",
            autospec=True,
            side_effect=lambda path: path in existing,
        )

    def test_formats_semantic_results_from_json(self) -> None:
        with self._patch_exists({knowledge.KNOWLEDGE_VENV_PYTHON, knowledge.KNOWLEDGE_SEARCH_SCRIPT}):
            result = knowledge.search_knowledge_vault(
                "laser fund",
                5,
                lambda cmd, timeout: (
                    0,
                    '[{"book":"The LASER Fund","author":"Douglas Andrew","chapter":"Chapter 3","pages":"45-47","score":0.9234,"excerpt":"relevant text"}]',
                ),
            )

        self.assertIn("Found 1 semantic result(s) for 'laser fund' in HVE library:", result)
        self.assertIn("### The LASER Fund", result)
        self.assertIn("Author: Douglas Andrew", result)
        self.assertIn("Pages: 45-47", result)
        self.assertIn("Score: 0.9234", result)

    def test_invalid_json_falls_back_to_grep(self) -> None:
        def fake_run(cmd: list[str], timeout: int) -> tuple[int, str]:
            if cmd[0] == "grep" and "-l" in cmd:
                return 0, "/hve-library/processed/text/laser-fund.txt"
            if cmd[0] == "grep":
                return 0, "42:bitcoin risk management excerpt"
            return 0, "not-json"

        with self._patch_exists(
            {
                knowledge.KNOWLEDGE_VENV_PYTHON,
                knowledge.KNOWLEDGE_SEARCH_SCRIPT,
                knowledge.PROCESSED_TEXT_DIR,
            }
        ):
            result = knowledge.search_knowledge_vault("bitcoin risk management", 5, fake_run)

        self.assertIn("Semantic search unavailable.", result)
        self.assertIn("laser-fund.txt", result)
        self.assertIn("bitcoin risk management excerpt", result)

    def test_timeout_path_uses_fallback_grep(self) -> None:
        calls: list[tuple[list[str], int]] = []

        def fake_run(cmd: list[str], timeout: int) -> tuple[int, str]:
            calls.append((cmd, timeout))
            if cmd[0] == "grep" and "-l" in cmd:
                return 0, "/hve-library/processed/text/fallback.txt"
            if cmd[0] == "grep":
                return 0, "8:fallback line"
            return 1, "timed out"

        with self._patch_exists(
            {
                knowledge.KNOWLEDGE_VENV_PYTHON,
                knowledge.KNOWLEDGE_SEARCH_SCRIPT,
                knowledge.PROCESSED_TEXT_DIR,
            }
        ):
            result = knowledge.search_knowledge_vault("query", 99, fake_run)

        self.assertEqual(calls[0][1], knowledge.SEMANTIC_SEARCH_TIMEOUT)
        self.assertIn("fallback.txt", result)
        self.assertIn("fallback line", result)

    def test_empty_semantic_results_return_no_results_message(self) -> None:
        with self._patch_exists({knowledge.KNOWLEDGE_VENV_PYTHON, knowledge.KNOWLEDGE_SEARCH_SCRIPT}):
            result = knowledge.search_knowledge_vault("nothing", 5, lambda cmd, timeout: (0, "[]"))

        self.assertEqual(result, "No results found for 'nothing' in HVE library.")

    def test_missing_pages_and_score_do_not_break_formatting(self) -> None:
        with self._patch_exists({knowledge.KNOWLEDGE_VENV_PYTHON, knowledge.KNOWLEDGE_SEARCH_SCRIPT}):
            result = knowledge.search_knowledge_vault(
                "query",
                5,
                lambda cmd, timeout: (
                    0,
                    '[{"book":"Unknown","author":null,"chapter":null,"pages":null,"score":null,"excerpt":"text"}]',
                ),
            )

        self.assertIn("Pages: unknown", result)
        self.assertNotIn("Score:", result)
        self.assertIn("Excerpt: text", result)

    def test_machine_result_identifies_semantic_backend(self) -> None:
        with self._patch_exists({knowledge.KNOWLEDGE_VENV_PYTHON, knowledge.KNOWLEDGE_SEARCH_SCRIPT}):
            result = knowledge.search_knowledge_vault_machine(
                "query",
                5,
                lambda cmd, timeout: (0, '[{"document_id":"0123456789abcdef"}]'),
            )
        self.assertEqual(result["retrieval_mode"], "semantic")
        self.assertTrue(result["semantic_available"])
        self.assertFalse(result["fallback_used"])
        self.assertIsNone(result["backend_error"])

    def test_machine_result_preserves_semantic_error_on_fallback(self) -> None:
        def fake_run(cmd: list[str], timeout: int) -> tuple[int, str]:
            if cmd[0] == "grep" and "-l" in cmd:
                return 0, "/hve-library/processed/text/fallback.txt"
            if cmd[0] == "grep":
                return 0, "8:fallback line"
            return 1, "Ollama embedding request failed: refused"

        with self._patch_exists(
            {
                knowledge.KNOWLEDGE_VENV_PYTHON,
                knowledge.KNOWLEDGE_SEARCH_SCRIPT,
                knowledge.PROCESSED_TEXT_DIR,
            }
        ):
            result = knowledge.search_knowledge_vault_machine("query", 5, fake_run)
        self.assertEqual(result["retrieval_mode"], "keyword_fallback")
        self.assertTrue(result["fallback_used"])
        self.assertIn("refused", result["backend_error"])
        self.assertEqual(
            result["results"],
            [{"path": "fallback.txt", "excerpt": "8:fallback line"}],
        )


if __name__ == "__main__":
    unittest.main()
