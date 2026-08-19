from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knowledge" / "layer"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import finalize
import run_intake_pipeline
from common import load_manifest, save_manifest


class FinalizeTests(unittest.TestCase):
    def test_finalize_moves_pdf_and_updates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inbox = root / "intake" / "inbox"
            raw = root / "raw" / "pdfs"
            manifests = root / "state" / "manifests"
            chunks = root / "processed" / "chunks"
            inbox.mkdir(parents=True)
            raw.mkdir(parents=True)
            manifests.mkdir(parents=True)
            chunks.mkdir(parents=True)

            pdf_path = inbox / "book.pdf"
            pdf_path.write_bytes(b"pdf")
            chunk_path = chunks / "doc.jsonl"
            chunk_path.write_text('{"chunk":1}\n{"chunk":2}\n', encoding="utf-8")
            manifest_path = manifests / "doc.json"
            failed_state = root / "state" / "failed"
            failed_state.mkdir(parents=True)
            (failed_state / "doc-indexing.json").write_text('{"stage":"indexing"}\n', encoding="utf-8")
            save_manifest(
                manifest_path,
                {
                    "title": "Book",
                    "source_path": str(pdf_path),
                    "chunk_count": 2,
                    "chunk_path": str(chunk_path),
                    "ingest_status": "extracted",
                    "failed_stage": "indexing",
                    "failure_error": "old error",
                },
            )

            ok, message = finalize.finalize_pdf(root, pdf_path, manifest_path)

            self.assertTrue(ok)
            self.assertIn("FINALIZED title=Book chunks=2 path=raw/pdfs/book.pdf", message)
            self.assertFalse(pdf_path.exists())
            self.assertTrue((raw / "book.pdf").exists())
            manifest = load_manifest(manifest_path)
            self.assertEqual(manifest["status"], "indexed")
            self.assertEqual(manifest["ingest_status"], "ingested")
            self.assertEqual(manifest["source_path"], str(raw / "book.pdf"))
            self.assertIsNone(manifest["failed_stage"])
            self.assertIsNone(manifest["failure_error"])
            self.assertFalse((failed_state / "doc-indexing.json").exists())

    def test_finalize_warns_when_pdf_not_in_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            other = root / "raw" / "book.pdf"
            other.parent.mkdir(parents=True)
            other.write_bytes(b"pdf")

            ok, message = finalize.finalize_pdf(root, other, None)

            self.assertTrue(ok)
            self.assertEqual(message, f"WARN finalize skipped path={other} not in inbox")


class RunPipelineTests(unittest.TestCase):
    def _fake_extract_success(self, root: Path, manifest_path: Path, pdf_path: Path) -> tuple[bool, str | None]:
        manifest = load_manifest(manifest_path)
        text_path = root / "processed" / "text" / f"{manifest['document_id']}.txt"
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text("page one\fpage two", encoding="utf-8")
        manifest["extraction_status"] = "completed"
        manifest["ingest_status"] = "extracted"
        manifest["extracted_text_path"] = str(text_path)
        save_manifest(manifest_path, manifest)
        return True, None

    def _fake_chunk_success(self, root: Path, manifest_path: Path, chunk_size: int, overlap: int) -> tuple[int, str | None]:
        manifest = load_manifest(manifest_path)
        chunk_path = root / "processed" / "chunks" / f"{manifest['document_id']}.jsonl"
        chunk_path.parent.mkdir(parents=True, exist_ok=True)
        chunk_path.write_text('{"chunk":1}\n{"chunk":2}\n', encoding="utf-8")
        manifest["chunk_status"] = "completed"
        manifest["chunk_count"] = 2
        manifest["chunk_path"] = str(chunk_path)
        save_manifest(manifest_path, manifest)
        return 2, None

    def test_run_pipeline_indexes_batch_once_and_finalizes_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inbox = root / "intake" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "alpha.pdf").write_bytes(b"alpha")
            (inbox / "beta.pdf").write_bytes(b"beta")
            logs: list[str] = []
            calls: list[list[str]] = []

            def fake_runner(cmd, capture_output, text, check):  # noqa: ANN001
                calls.append(cmd)
                return mock.Mock(returncode=0, stdout="PASS index build", stderr="")

            exit_code = run_intake_pipeline.run_pipeline(
                root,
                runner=fake_runner,
                extractor=self._fake_extract_success,
                chunker=self._fake_chunk_success,
                emit=logs.append,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("--device", calls[0])
            self.assertIn("cpu", calls[0])
            chunk_args = [value for index, value in enumerate(calls[0]) if calls[0][index - 1] == "--chunk-file"]
            self.assertEqual(len(chunk_args), 2)
            self.assertTrue(all(path.endswith(".jsonl") for path in chunk_args))
            self.assertTrue((root / "raw" / "pdfs" / "alpha.pdf").exists())
            self.assertTrue((root / "raw" / "pdfs" / "beta.pdf").exists())
            log_text = "\n".join(logs)
            self.assertIn("KNOWLEDGE_INDEXED document_id=", log_text)
            self.assertIn("source=", log_text)
            self.assertIn("RESULT indexed=2 failures=0 skipped=0", "\n".join(logs))

    def test_run_pipeline_moves_failed_pdf_and_continues_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inbox = root / "intake" / "inbox"
            inbox.mkdir(parents=True)
            bad_pdf = inbox / "bad.pdf"
            good_pdf = inbox / "good.pdf"
            bad_pdf.write_bytes(b"bad")
            good_pdf.write_bytes(b"good")
            logs: list[str] = []

            def flaky_extract(root: Path, manifest_path: Path, pdf_path: Path) -> tuple[bool, str | None]:
                if pdf_path.name == "bad.pdf":
                    return False, "pdftotext failed"
                return self._fake_extract_success(root, manifest_path, pdf_path)

            runner_calls: list[list[str]] = []

            def fake_runner(cmd, capture_output, text, check):  # noqa: ANN001
                runner_calls.append(cmd)
                return mock.Mock(returncode=0, stdout="PASS index build", stderr="")

            exit_code = run_intake_pipeline.run_pipeline(
                root,
                runner=fake_runner,
                extractor=flaky_extract,
                chunker=self._fake_chunk_success,
                emit=logs.append,
            )

            self.assertEqual(exit_code, 1)
            self.assertEqual(len(runner_calls), 1)
            self.assertTrue((root / "intake" / "failed" / "bad.pdf").exists())
            self.assertTrue((root / "raw" / "pdfs" / "good.pdf").exists())
            self.assertIn("FAILED title=bad step=extraction error=pdftotext failed", "\n".join(logs))

    def test_run_pipeline_fails_batch_when_chunk_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inbox = root / "intake" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "alpha.pdf").write_bytes(b"alpha")
            logs: list[str] = []

            def chunk_without_file(root: Path, manifest_path: Path, chunk_size: int, overlap: int) -> tuple[int, str | None]:
                manifest = load_manifest(manifest_path)
                manifest["chunk_status"] = "completed"
                manifest["chunk_count"] = 2
                manifest["chunk_path"] = str(root / "processed" / "chunks" / f"{manifest['document_id']}.jsonl")
                save_manifest(manifest_path, manifest)
                return 2, None

            runner = mock.Mock()

            exit_code = run_intake_pipeline.run_pipeline(
                root,
                runner=runner,
                extractor=self._fake_extract_success,
                chunker=chunk_without_file,
                emit=logs.append,
            )

            self.assertEqual(exit_code, 1)
            runner.assert_not_called()
            self.assertTrue((root / "intake" / "failed" / "alpha.pdf").exists())
            self.assertIn("FAILED title=alpha step=indexing error=chunk file missing", "\n".join(logs))

    def test_run_pipeline_skips_duplicate_indexed_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inbox = root / "intake" / "inbox"
            raw = root / "raw" / "pdfs"
            manifests = root / "state" / "manifests"
            inbox.mkdir(parents=True)
            raw.mkdir(parents=True)
            manifests.mkdir(parents=True)

            archive_pdf = raw / "dup.pdf"
            archive_pdf.write_bytes(b"same-content")
            duplicate_pdf = inbox / "dup.pdf"
            duplicate_pdf.write_bytes(b"same-content")
            record = run_intake_pipeline.manifest_for(archive_pdf)
            manifest_path = manifests / f"{record['document_id']}.json"
            save_manifest(
                manifest_path,
                {
                    **record,
                    "source_path": str(archive_pdf),
                    "status": "indexed",
                    "ingest_status": "ingested",
                },
            )
            logs: list[str] = []

            exit_code = run_intake_pipeline.run_pipeline(root, emit=logs.append)

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "intake" / "failed" / "dup.pdf").exists())
            self.assertIn("SKIPPED title=dup reason=already indexed", "\n".join(logs))


if __name__ == "__main__":
    unittest.main()
