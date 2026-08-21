from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from app.transfer import (
    TransferJobRequest,
    prepare_transfer_files,
    run_transfer_job,
    transfer_destination_subdirectory,
)


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

    def test_custom_destination_is_scoped_to_source(self) -> None:
        request = TransferJobRequest(
            source="LANHE",
            server="storage-01",
            files=["product.xml"],
            destination_subdirectory="2026/batch-001",
        )
        self.assertEqual(
            transfer_destination_subdirectory(request),
            Path("lanhe/2026/batch-001"),
        )

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

    def test_successful_transfer_invokes_targeted_ingest_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "remote-linux"
            upload_root = root / "upload"
            data_root = root / "data"
            product = source_root / "product-001"
            product.mkdir(parents=True)
            upload_root.mkdir()
            data_root.mkdir()
            (product / "metadata.XML").write_bytes(b"metadata")
            job_id = uuid4()
            file_id = uuid4()
            job = {
                "server": "storage-01",
                "mode": "COPY",
                "files": [
                    {
                        "id": file_id,
                        "source_path": "product-001",
                        "destination_path": "lanhe/product-001",
                    }
                ],
            }
            settings = SimpleNamespace(
                transfer_sources={"storage-01": source_root.resolve()},
                transfer_destination_root=str(upload_root),
                scan_root=str(data_root),
                scan_write_delay_ms=20,
            )

            with (
                patch("app.transfer.start_transfer_job", return_value=True),
                patch("app.transfer.get_transfer_job", return_value=job),
                patch("app.transfer.get_settings", return_value=settings),
                patch("app.transfer.transfer_job_is_cancelled", return_value=False),
                patch("app.transfer.update_transfer_file_progress"),
                patch("app.transfer.ingest_upload") as ingest,
                patch("app.transfer.finish_transfer_file") as finish,
                patch("app.transfer.finalize_transfer_job") as finalize,
            ):
                run_transfer_job(job_id)

            ingest.assert_called_once_with(
                upload_root=upload_root.resolve(),
                data_root=str(data_root),
                relative_path="lanhe/product-001",
                write_delay_ms=20,
            )
            finish.assert_called_once_with(file_id, True)
            finalize.assert_called_once_with(job_id)

    def test_ingest_failure_marks_file_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "remote-linux"
            upload_root = root / "upload"
            data_root = root / "data"
            source_root.mkdir()
            upload_root.mkdir()
            data_root.mkdir()
            (source_root / "product.xml").write_bytes(b"metadata")
            job_id = uuid4()
            file_id = uuid4()
            job = {
                "server": "storage-01",
                "mode": "COPY",
                "files": [
                    {
                        "id": file_id,
                        "source_path": "product.xml",
                        "destination_path": "lanhe/product.xml",
                    }
                ],
            }
            settings = SimpleNamespace(
                transfer_sources={"storage-01": source_root.resolve()},
                transfer_destination_root=str(upload_root),
                scan_root=str(data_root),
                scan_write_delay_ms=20,
            )

            with (
                patch("app.transfer.start_transfer_job", return_value=True),
                patch("app.transfer.get_transfer_job", return_value=job),
                patch("app.transfer.get_settings", return_value=settings),
                patch("app.transfer.transfer_job_is_cancelled", return_value=False),
                patch("app.transfer.update_transfer_file_progress"),
                patch("app.transfer.ingest_upload", side_effect=RuntimeError("database unavailable")),
                patch("app.transfer.finish_transfer_file") as finish,
                patch("app.transfer.finalize_transfer_job") as finalize,
            ):
                run_transfer_job(job_id)

            finish.assert_called_once_with(
                file_id,
                False,
                "ingest failed: database unavailable",
            )
            finalize.assert_called_once_with(job_id)


if __name__ == "__main__":
    unittest.main()
