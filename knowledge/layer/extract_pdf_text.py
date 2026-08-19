#!/usr/bin/env python3

import argparse
import datetime as dt
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from common import clear_failure


OCR_LANGUAGE = "eng"
OCR_DPI = "300"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_manifests(root: Path) -> list[Path]:
    manifest_dir = root / "state" / "manifests"
    if not manifest_dir.exists():
        return []
    return sorted(manifest_dir.glob("*.json"))


def update_manifest(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _has_text(text_path: Path) -> bool:
    return any(character not in {"\f", "\n", "\r", "\t", " "} for character in text_path.read_text(
        encoding="utf-8", errors="ignore"
    ))


def _ocr_pdf(pdf_path: Path, text_path: Path) -> tuple[bool, str | None, dict]:
    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not pdftoppm or not tesseract:
        missing = [
            command
            for command, path in (("pdftoppm", pdftoppm), ("tesseract", tesseract))
            if not path
        ]
        return False, f"local OCR unavailable; missing: {', '.join(missing)}", {
            "extraction_method": "ocr",
            "ocr_status": "unavailable",
            "ocr_language": OCR_LANGUAGE,
            "ocr_page_count": 0,
        }

    with tempfile.TemporaryDirectory(prefix="hve-ocr-", dir=text_path.parent) as temporary_dir:
        page_prefix = Path(temporary_dir) / "page"
        render = subprocess.run(
            [pdftoppm, "-r", OCR_DPI, "-png", str(pdf_path), str(page_prefix)],
            capture_output=True,
            text=True,
            check=False,
        )
        if render.returncode != 0:
            return False, render.stderr.strip() or "PDF page rendering failed", {
                "extraction_method": "ocr",
                "ocr_status": "failed",
                "ocr_language": OCR_LANGUAGE,
                "ocr_page_count": 0,
            }

        pages = sorted(Path(temporary_dir).glob("page-*.png"))
        if not pages:
            return False, "PDF rendering produced no pages", {
                "extraction_method": "ocr",
                "ocr_status": "failed",
                "ocr_language": OCR_LANGUAGE,
                "ocr_page_count": 0,
            }

        extracted_pages: list[str] = []
        for page in pages:
            result = subprocess.run(
                [tesseract, str(page), "stdout", "--psm", "3", "-l", OCR_LANGUAGE],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return False, result.stderr.strip() or f"OCR failed for {page.name}", {
                    "extraction_method": "ocr",
                    "ocr_status": "failed",
                    "ocr_language": OCR_LANGUAGE,
                    "ocr_page_count": len(pages),
                }
            extracted_pages.append(result.stdout.strip())

        if not any(extracted_pages):
            return False, "OCR produced no extractable text", {
                "extraction_method": "ocr",
                "ocr_status": "empty",
                "ocr_language": OCR_LANGUAGE,
                "ocr_page_count": len(pages),
            }

        text_path.write_text("\n\f\n".join(extracted_pages) + "\n", encoding="utf-8")
        return True, None, {
            "extraction_method": "ocr",
            "ocr_status": "completed",
            "ocr_language": OCR_LANGUAGE,
            "ocr_page_count": len(pages),
        }


def extract_text_with_metadata(pdf_path: Path, text_path: Path) -> tuple[bool, str | None, dict]:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return False, "pdftotext not installed", {
            "extraction_method": "native_text",
            "ocr_status": "not_attempted",
            "ocr_language": OCR_LANGUAGE,
            "ocr_page_count": 0,
        }
    text_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [pdftotext, "-layout", str(pdf_path), str(text_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr.strip() or "pdftotext failed", {
            "extraction_method": "native_text",
            "ocr_status": "not_attempted",
            "ocr_language": OCR_LANGUAGE,
            "ocr_page_count": 0,
        }
    if _has_text(text_path):
        return True, None, {
            "extraction_method": "native_text",
            "ocr_status": "not_required",
            "ocr_language": OCR_LANGUAGE,
            "ocr_page_count": 0,
        }
    return _ocr_pdf(pdf_path, text_path)


def extract_text(pdf_path: Path, text_path: Path) -> tuple[bool, str | None]:
    ok, error, _ = extract_text_with_metadata(pdf_path, text_path)
    return ok, error


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text from HVE library PDFs.")
    parser.add_argument("--root", required=True, help="Knowledge-layer root path")
    parser.add_argument("--limit", type=int, default=5, help="Max manifests to process")
    args = parser.parse_args()

    root = Path(args.root)
    processed = 0
    for manifest_path in load_manifests(root):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("extraction_status") == "completed":
            continue
        pdf_path = Path(payload["source_path"])
        if not pdf_path.exists():
            payload["extraction_status"] = "failed"
            payload["extraction_error"] = "source PDF missing"
            update_manifest(manifest_path, payload)
            continue

        text_path = root / "processed" / "text" / f"{payload['document_id']}.txt"
        ok, error = extract_text(pdf_path, text_path)
        if ok:
            payload["extraction_status"] = "completed"
            payload["ingest_status"] = "extracted"
            payload["extracted_text_path"] = str(text_path)
            payload["extracted_at"] = now_iso()
            payload["extraction_error"] = None
            clear_failure(root, payload["document_id"], "extraction")
        else:
            payload["extraction_status"] = "failed"
            payload["extraction_error"] = error
        update_manifest(manifest_path, payload)
        processed += 1
        if processed >= args.limit:
            break

    print(f"PASS processed={processed} root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
