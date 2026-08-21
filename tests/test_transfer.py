from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.transfer import TransferJobRequest, prepare_transfer_files


class TransferRequestTests(unittest.TestCase):
    def test_multiple_paths_default_to_source_upload_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory) / "remote-linux"
            source_root.mkdir()
            first = source_root / "batch" / "LANHE_001.XML"
            second = source_root / "batch" / "LANHE_002.XML"
            first.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second file")
            settings = SimpleNamespace(
                transfer_sources={"storage-01": source_root.resolve()},
                transfer_destination_root="/upload",
            )
            request = TransferJobRequest(
                source="lanhe",
                server="storage-01",
                files=["batch/LANHE_001.XML", "batch/LANHE_002.XML"],
            )

            with patch("app.transfer.get_settings", return_value=settings):
                prepared = prepare_transfer_files(request)

            self.assertEqual(request.source, "LANHE")
            self.assertEqual(len(prepared), 2)
            self.assertEqual(prepared[0]["destination_path"], "lanhe/LANHE_001.XML")
            self.assertEqual(prepared[1]["destination_path"], "lanhe/LANHE_002.XML")
            self.assertEqual(prepared[0]["size_bytes"], 5)
            self.assertEqual(prepared[1]["size_bytes"], 11)

    def test_unknown_source_is_rejected_before_transfer(self) -> None:
        settings = SimpleNamespace(transfer_sources={}, transfer_destination_root="/upload")
        request = TransferJobRequest(
            source="unknown",
            server="storage-01",
            files=["batch/product.xml"],
        )

        with patch("app.transfer.get_settings", return_value=settings):
            with self.assertRaisesRegex(HTTPException, "unsupported SAR source"):
                prepare_transfer_files(request)


if __name__ == "__main__":
    unittest.main()
