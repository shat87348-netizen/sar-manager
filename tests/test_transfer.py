from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.main import _transfer_job_response
from app.repository import list_transfer_jobs
from app.transfer import (
    TransferJobRequest,
    prepare_transfer_files,
    run_transfer_job,
    transfer_destination_subdirectory,
)

LANHE_XML = """<?xml version="1.0"?>
<ProductMeta>
  <SatelliteID>RSS1B</SatelliteID>
  <ProductInfo><DataProcessing><ProductID>LANHE_DEDUP_001</ProductID></DataProcessing></ProductInfo>
  <ImageInfo>
    <ImagingStartTime>2026-08-21T12:00:00</ImagingStartTime>
    <ImageExtent>
      <UpperLeft><Longitude>120</Longitude><Latitude>31</Latitude></UpperLeft>
      <UpperRight><Longitude>121</Longitude><Latitude>31</Latitude></UpperRight>
      <LowerRight><Longitude>121</Longitude><Latitude>30</Latitude></LowerRight>
      <LowerLeft><Longitude>120</Longitude><Latitude>30</Latitude></LowerLeft>
    </ImageExtent>
  </ImageInfo>
</ProductMeta>
"""


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

    def test_existing_database_product_is_skipped_before_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory) / "remote-linux"
            product = source_root / "product-001"
            product.mkdir(parents=True)
            (product / "metadata.XML").write_text(LANHE_XML, encoding="utf-8")
            settings = SimpleNamespace(
                transfer_sources={"storage-01": source_root.resolve()},
                transfer_destination_root="/upload",
            )
            request = TransferJobRequest(
                source="LANHE",
                server="storage-01",
                files=["product-001"],
            )

            with (
                patch("app.transfer.get_settings", return_value=settings),
                patch(
                    "app.transfer.get_existing_external_ids",
                    return_value={"LANHE:LANHE_DEDUP_001"},
                ),
            ):
                prepared = prepare_transfer_files(request)

            self.assertEqual(
                prepared[0]["skip_reason"],
                "Already ingested: LANHE:LANHE_DEDUP_001",
            )
            self.assertEqual(
                prepared[0]["external_ids"],
                ["LANHE:LANHE_DEDUP_001"],
            )

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
                        "status": "QUEUED",
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
                        "status": "QUEUED",
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

    def test_job_response_contains_live_and_skipped_file_progress(self) -> None:
        now = datetime(2026, 8, 21, 12, 0, 0)
        job = {
            "id": uuid4(),
            "source": "LANHE",
            "server": "storage-01",
            "destination_subdirectory": "lanhe",
            "mode": "COPY",
            "status": "RUNNING",
            "total_files": 2,
            "completed_files": 0,
            "failed_files": 0,
            "skipped_files": 1,
            "total_bytes": 100,
            "transferred_bytes": 0,
            "error_message": None,
            "created_at": now,
            "started_at": now,
            "completed_at": None,
            "files": [
                {
                    "source_path": "new-product",
                    "destination_path": "lanhe/new-product",
                    "status": "TRANSFERRING",
                    "size_bytes": 100,
                    "transferred_bytes": 25,
                    "error_message": None,
                },
                {
                    "source_path": "existing-product",
                    "destination_path": "lanhe/existing-product",
                    "status": "SKIPPED",
                    "size_bytes": 200,
                    "transferred_bytes": 0,
                    "error_message": "Already ingested: LANHE:EXISTING",
                },
            ],
        }

        response = _transfer_job_response(job)

        self.assertEqual(response["progress"]["transferred_bytes"], 25)
        self.assertEqual(response["progress"]["percent"], 25.0)
        self.assertEqual(response["progress"]["skipped_files"], 1)
        self.assertEqual(response["files"][0]["phase"], "TRANSFERRING")
        self.assertEqual(response["files"][1]["phase"], "SKIPPED")

    def test_job_list_attaches_live_file_records(self) -> None:
        job_id = uuid4()
        job = {"id": job_id, "status": "RUNNING"}
        file_record = {
            "id": uuid4(),
            "job_id": job_id,
            "status": "TRANSFERRING",
            "transferred_bytes": 25,
        }
        pool = MagicMock()
        connection = pool.connection.return_value.__enter__.return_value
        jobs_result = MagicMock()
        jobs_result.fetchall.return_value = [job]
        files_result = MagicMock()
        files_result.fetchall.return_value = [file_record]
        connection.execute.side_effect = [jobs_result, files_result]

        with patch("app.repository.get_pool", return_value=pool):
            jobs = list_transfer_jobs(status="RUNNING", limit=100, offset=0)

        self.assertEqual(jobs[0]["files"], [file_record])
        self.assertEqual(jobs[0]["files"][0]["transferred_bytes"], 25)


if __name__ == "__main__":
    unittest.main()
