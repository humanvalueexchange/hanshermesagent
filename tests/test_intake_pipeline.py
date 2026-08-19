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

            with mock.patch("finalize.update_source_path", return_value=2):
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
                return mock.Mock(returncode=0, stdout='{"records": 2}', stderr="")

            def fake_finalize(root, pdf_path, manifest_path):  # noqa: ANN001
                destination = root / "raw" / "pdfs" / pdf_path.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.replace(destination)
                return True, f"FINALIZED path={destination.relative_to(root)}"

            exit_code = run_intake_pipeline.run_pipeline(
                root,
                runner=fake_runner,
                extractor=self._fake_extract_success,
                chunker=self._fake_chunk_success,
                finalizer=fake_finalize,
                emit=logs.append,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all("--device" not in call for call in calls))
            chunk_args = [
                value for call in calls for index, value in enumerate(call)
                if index and call[index - 1] == "--chunk-file"
            ]
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
                return mock.Mock(returncode=0, stdout='{"records": 2}', stderr="")

            def fake_finalize(root, pdf_path, manifest_path):  # noqa: ANN001
                destination = root / "raw" / "pdfs" / pdf_path.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.replace(destination)
                return True, f"FINALIZED path={destination.relative_to(root)}"

            exit_code = run_intake_pipeline.run_pipeline(
                root,
                runner=fake_runner,
                extractor=flaky_extract,
                chunker=self._fake_chunk_success,
                finalizer=fake_finalize,
                emit=logs.append,
            )

            self.assertEqual(exit_code, 1)
            self.assertEqual(len(runner_calls), 1)
            self.assertTrue((root / "intake" / "failed" / "bad.pdf").exists())
            self.assertTrue((root / "raw" / "pdfs" / "good.pdf").exists())
            self.assertIn("FAILED title=bad step=extraction error=pdftotext failed", "\n".join(logs))

    def test_run_pipeline_rolls_back_prior_indexed_documents_on_batch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inbox = root / "intake" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "alpha.pdf").write_bytes(b"alpha")
            (inbox / "beta.pdf").write_bytes(b"beta")
            logs: list[str] = []
            calls = 0

            def flaky_runner(cmd, capture_output, text, check):  # noqa: ANN001
                nonlocal calls
                calls += 1
                if calls == 2:
                    return mock.Mock(returncode=1, stdout="", stderr="index failed")
                return mock.Mock(returncode=0, stdout='{"records": 2}', stderr="")

            finalizer = mock.Mock(
                return_value=(True, "FINALIZED should not be called after rollback")
            )
            restored: list[str] = []

            def fake_restore(root, document_id, rows):  # noqa: ANN001
                restored.append(document_id)

            with (
                mock.patch.object(run_intake_pipeline, "snapshot_document", return_value=[]),
                mock.patch.object(run_intake_pipeline, "restore_document", side_effect=fake_restore),
            ):
                exit_code = run_intake_pipeline.run_pipeline(
                    root,
                    runner=flaky_runner,
                    extractor=self._fake_extract_success,
                    chunker=self._fake_chunk_success,
                    finalizer=finalizer,
                    emit=logs.append,
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(calls, 2)
            self.assertEqual(len(restored), 2)
            self.assertFalse((root / "raw" / "pdfs" / "alpha.pdf").exists())
            self.assertTrue((root / "intake" / "processing" / "alpha.pdf").exists())
            self.assertTrue((root / "intake" / "failed" / "beta.pdf").exists())
            finalizer.assert_not_called()
            journal_files = list((root / "state" / "intake-batches").glob("*.json"))
            self.assertEqual(len(journal_files), 1)
            journal = json.loads(journal_files[0].read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "rolled_back")
            self.assertIn("ROLLED_BACK batch=", "\n".join(logs))

    def test_run_pipeline_rolls_back_archived_files_on_finalize_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            inbox = root / "intake" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "alpha.pdf").write_bytes(b"alpha")
            (inbox / "beta.pdf").write_bytes(b"beta")
            logs: list[str] = []

            def fake_runner(cmd, capture_output, text, check):  # noqa: ANN001
                return mock.Mock(returncode=0, stdout='{"records": 2}', stderr="")

            def flaky_finalize(root, pdf_path, manifest_path):  # noqa: ANN001
                destination = root / "raw" / "pdfs" / pdf_path.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.replace(destination)
                manifest = load_manifest(manifest_path)
                manifest["source_path"] = str(destination)
                save_manifest(manifest_path, manifest)
                if pdf_path.name == "beta.pdf":
                    return False, "provenance update failed"
                return True, f"FINALIZED path={destination.relative_to(root)}"

            with (
                mock.patch.object(run_intake_pipeline, "snapshot_document", return_value=[]),
                mock.patch.object(run_intake_pipeline, "restore_document"),
            ):
                exit_code = run_intake_pipeline.run_pipeline(
                    root,
                    runner=fake_runner,
                    extractor=self._fake_extract_success,
                    chunker=self._fake_chunk_success,
                    finalizer=flaky_finalize,
                    emit=logs.append,
                )

            self.assertEqual(exit_code, 1)
            self.assertTrue((root / "intake" / "processing" / "alpha.pdf").exists())
            self.assertTrue((root / "intake" / "failed" / "beta.pdf").exists())
            self.assertFalse((root / "raw" / "pdfs" / "alpha.pdf").exists())
            self.assertFalse((root / "raw" / "pdfs" / "beta.pdf").exists())
            journal_files = list((root / "state" / "intake-batches").glob("*.json"))
            journal = json.loads(journal_files[0].read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "rolled_back")

    def test_recover_incomplete_batch_rolls_back_before_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest_path = root / "state" / "manifests" / "doc.json"
            manifest_path.parent.mkdir(parents=True)
            original_manifest = {"document_id": "doc", "source_path": str(root / "intake" / "processing" / "doc.pdf")}
            save_manifest(manifest_path, original_manifest)
            journal_path = root / "state" / "intake-batches" / "batch.json"
            journal_path.parent.mkdir(parents=True)
            journal_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "batch_id": "batch",
                        "status": "active",
                        "documents": [
                            {
                                "document_id": "doc",
                                "pdf_path": original_manifest["source_path"],
                                "manifest_path": str(manifest_path),
                                "manifest_before": original_manifest,
                                "previous_rows": [],
                                "indexed": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            restored: list[str] = []
            with mock.patch.object(
                run_intake_pipeline,
                "restore_document",
                side_effect=lambda root, document_id, rows: restored.append(document_id),
            ):
                logs: list[str] = []
                run_intake_pipeline.recover_incomplete_batches(root, logs.append)

            self.assertEqual(restored, ["doc"])
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "rolled_back")
            self.assertIn("ROLLED_BACK batch=batch", logs[0])

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
