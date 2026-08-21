from __future__ import annotations

import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingest import IngestError, ingest_upload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GF3_XML = next((PROJECT_ROOT / "tiff" / "gf3").rglob("*.xml"))
STRIX_ARCHIVE = next((PROJECT_ROOT / "tiff" / "striX").glob("*.zip"))


class IngestTests(unittest.TestCase):
    def _fake_scanner(self, expected_target: Path) -> types.ModuleType:
        module = types.ModuleType("app.scanner")

        class Report:
            def to_dict(self) -> dict[str, int]:
                return {"imported": 1, "ready": 1}

        def scan_storage(target: Path, force: bool, write_delay_ms: int) -> Report:
            self.assertEqual(target, expected_target)
            self.assertFalse(force)
            self.assertEqual(write_delay_ms, 20)
            return Report()

        module.scan_storage = scan_storage
        return module

    def test_ingest_moves_valid_gf3_product_before_targeted_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload = root / "upload"
            data = root / "data"
            staged = upload / "gf3" / "batch-001" / "product-001"
            staged.mkdir(parents=True)
            data.mkdir()
            shutil.copy2(GF3_XML, staged / GF3_XML.name)

            destination = (data / "gf3" / "batch-001" / "product-001").resolve()
            with patch.dict(sys.modules, {"app.scanner": self._fake_scanner(destination)}):
                result = ingest_upload(
                    upload,
                    data,
                    "gf3/batch-001/product-001",
                    write_delay_ms=20,
                )

            self.assertFalse(staged.exists())
            self.assertTrue((destination / GF3_XML.name).is_file())
            self.assertEqual(result.expected_source, "GF3")
            self.assertEqual(result.move_method, "rename")
            self.assertEqual(result.scan["imported"], 1)

    def test_ingest_rejects_source_directory_mismatch_without_moving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload = root / "upload"
            data = root / "data"
            staged = upload / "strix" / "product-001"
            staged.mkdir(parents=True)
            data.mkdir()
            shutil.copy2(GF3_XML, staged / GF3_XML.name)

            with self.assertRaises(IngestError):
                ingest_upload(upload, data, "strix/product-001")

            self.assertTrue(staged.exists())
            self.assertFalse((data / "strix" / "product-001").exists())

    def test_ingest_accepts_a_single_archive_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload = root / "upload"
            data = root / "data"
            staged = upload / "strix" / "batch-001" / STRIX_ARCHIVE.name
            staged.parent.mkdir(parents=True)
            data.mkdir()
            shutil.copy2(STRIX_ARCHIVE, staged)

            destination = (data / "strix" / "batch-001" / STRIX_ARCHIVE.name).resolve()
            with patch.dict(sys.modules, {"app.scanner": self._fake_scanner(destination)}):
                result = ingest_upload(
                    upload,
                    data,
                    f"strix/batch-001/{STRIX_ARCHIVE.name}",
                    write_delay_ms=20,
                )

            self.assertFalse(staged.exists())
            self.assertTrue(destination.is_file())
            self.assertEqual(result.expected_source, "STRIX")

    def test_ingest_rejects_paths_outside_upload_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload = root / "upload"
            data = root / "data"
            upload.mkdir()
            data.mkdir()
            with self.assertRaises(IngestError):
                ingest_upload(upload, data, "gf3/../../outside")


if __name__ == "__main__":
    unittest.main()
