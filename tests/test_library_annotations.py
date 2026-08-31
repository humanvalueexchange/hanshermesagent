from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.library_annotations import append_annotation, read_annotations


class LibraryAnnotationTests(unittest.TestCase):
    def test_appends_owner_attestation_without_changing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = root / "state" / "manifests" / "0123456789abcdef.json"
            manifest.parent.mkdir(parents=True)
            original = {"document_id": "0123456789abcdef", "title": "Source"}
            manifest.write_text(json.dumps(original) + "\n", encoding="utf-8")

            result = append_annotation(
                "0123456789abcdef",
                "Hans confirms the source relationship from firsthand knowledge.",
                "provenance",
                "owner_attested",
                "Hans Westphal",
                "Direct personal knowledge.",
                root=root,
            )

            self.assertEqual(result["status"], "annotated")
            self.assertEqual(json.loads(manifest.read_text()) , original)
            annotations = read_annotations("0123456789abcdef", root=root)
            self.assertEqual(len(annotations), 1)
            self.assertEqual(annotations[0]["verification_status"], "owner_attested")

    def test_rejects_unknown_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "does not exist"):
                append_annotation(
                    "0123456789abcdef",
                    "Note",
                    "provenance",
                    "owner_attested",
                    "Hans Westphal",
                    root=Path(tmpdir),
                )

    def test_rejects_unauthorized_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = root / "state" / "manifests" / "0123456789abcdef.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "authorized HVE authority"):
                append_annotation(
                    "0123456789abcdef",
                    "Note",
                    "provenance",
                    "owner_attested",
                    "Unknown",
                    root=root,
                )


if __name__ == "__main__":
    unittest.main()
