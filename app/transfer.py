from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from app.adapters import AdapterRegistry
from app.adapters.base import MetadataError, MetadataIgnored
from app.config import get_settings
from app.containers import iter_candidates
from app.domain import DiscoveryError
from app.ingest import ingest_upload
from app.repository import (
    cancel_transfer_file,
    fail_transfer_job,
    finalize_transfer_job,
    finish_transfer_file,
    get_existing_external_ids,
    get_transfer_job,
    start_transfer_job,
    transfer_job_is_cancelled,
    update_transfer_file_progress,
)


class TransferCancelled(Exception):
    pass


class TransferJobRequest(BaseModel):
    """Files are paths relative to the configured source server root."""

    source: str = Field(min_length=1, max_length=64)
    server: str = Field(min_length=1, max_length=128)
    files: list[str] = Field(min_length=1, max_length=100)
    destination_subdirectory: str = Field(default="", max_length=512)
    mode: str = Field(default="COPY", pattern="^(COPY|MOVE)$")

    @field_validator("files")
    @classmethod
    def files_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("files must not contain duplicates")
        return value

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        return value.strip().upper()


def _relative_path(value: str, field: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=422, detail=f"{field} must be a safe relative path")
    return path


def _resolve_under_root(root: Path, relative_path: str, field: str) -> Path:
    candidate = (root / _relative_path(relative_path, field)).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=422, detail=f"{field} escapes its configured root")
    return candidate


def transfer_destination_subdirectory(request: TransferJobRequest) -> Path:
    """Return an upload subdirectory which is always scoped to the SAR source."""

    source_directory = request.source.lower()
    requested = request.destination_subdirectory.strip()
    if not requested:
        return Path(source_directory)
    relative = _relative_path(requested, "destination_subdirectory")
    if relative.parts[0].lower() == source_directory:
        return relative
    return Path(source_directory) / relative


def _path_size(path: Path) -> int:
    if path.is_symlink():
        raise HTTPException(status_code=422, detail="symbolic links are not supported for transfer")
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        raise HTTPException(
            status_code=422,
            detail=f"source path is not a regular file or directory: {path.name}",
        )
    total = 0
    for item in path.rglob("*"):
        if item.is_symlink():
            raise HTTPException(
                status_code=422, detail="symbolic links are not supported for transfer"
            )
        if item.is_file():
            total += item.stat().st_size
    return total


def _recognized_external_ids(
    path: Path,
    expected_source: str,
    registry: AdapterRegistry,
) -> list[str]:
    external_ids: set[str] = set()
    for result in iter_candidates(path):
        if isinstance(result, DiscoveryError):
            continue
        try:
            parsed = registry.parse(result)
        except (MetadataError, MetadataIgnored):
            continue
        if parsed is None:
            continue
        if parsed.source != expected_source:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"source path {path.name} is declared as {expected_source}, "
                    f"but contains {parsed.source} metadata"
                ),
            )
        external_ids.add(parsed.external_id)
    return sorted(external_ids)


def prepare_transfer_files(request: TransferJobRequest) -> list[dict[str, object]]:
    settings = get_settings()
    registry = AdapterRegistry()
    supported_sources = registry.source_codes
    if request.source not in supported_sources:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unsupported SAR source: {request.source} "
                f"(supported: {', '.join(supported_sources)})"
            ),
        )
    source_root = settings.transfer_sources.get(request.server)
    if source_root is None:
        raise HTTPException(
            status_code=422, detail=f"unknown transfer server: {request.server}"
        )
    if not source_root.is_dir():
        raise HTTPException(
            status_code=503, detail=f"transfer server is not mounted: {request.server}"
        )
    destination_subdirectory = transfer_destination_subdirectory(request)
    destination_names: set[str] = set()
    prepared: list[dict[str, object]] = []
    for source_path in request.files:
        source = _resolve_under_root(source_root, source_path, "files")
        if not source.exists():
            raise HTTPException(
                status_code=422, detail=f"source path does not exist: {source_path}"
            )
        destination_path = destination_subdirectory / source.name
        if str(destination_path) in destination_names:
            raise HTTPException(
                status_code=422, detail="files resolve to the same destination name"
            )
        destination_names.add(str(destination_path))
        prepared.append(
            {
                "source_path": str(_relative_path(source_path, "files")),
                "destination_path": str(destination_path),
                "size_bytes": _path_size(source),
                "external_ids": _recognized_external_ids(
                    source,
                    request.source,
                    registry,
                ),
            }
        )
    requested_external_ids = sorted(
        {
            external_id
            for item in prepared
            for external_id in item["external_ids"]
        }
    )
    existing_external_ids = get_existing_external_ids(requested_external_ids)
    for item in prepared:
        item_external_ids = set(item["external_ids"])
        if item_external_ids and item_external_ids <= existing_external_ids:
            item["skip_reason"] = "Already ingested: " + ", ".join(
                sorted(item_external_ids)
            )
    return prepared


def _copy_file(
    source: Path, destination: Path, completed: int, report: Callable[[int], None]
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, destination.open("wb") as destination_handle:
        while chunk := source_handle.read(8 * 1024 * 1024):
            destination_handle.write(chunk)
            completed += len(chunk)
            report(completed)
    shutil.copystat(source, destination)
    return completed


def _copy_path(source: Path, destination: Path, report: Callable[[int], None]) -> None:
    completed = 0
    if source.is_file():
        _copy_file(source, destination, completed, report)
        return
    destination.mkdir(parents=True)
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise RuntimeError("symbolic links are not supported for transfer")
        target = destination / item.relative_to(source)
        if item.is_dir():
            target.mkdir(exist_ok=True)
        elif item.is_file():
            completed = _copy_file(item, target, completed, report)
    shutil.copystat(source, destination)


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def run_transfer_job(job_id: UUID) -> None:
    """Copy each requested product, then ingest it into the SAR catalogue."""

    if not start_transfer_job(job_id):
        return
    job = get_transfer_job(job_id)
    if job is None:
        return
    settings = get_settings()
    source_root = settings.transfer_sources.get(job["server"])
    if source_root is None:
        fail_transfer_job(job_id, "Configured transfer server was removed")
        return
    destination_root = Path(settings.transfer_destination_root).resolve()
    try:
        destination_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fail_transfer_job(job_id, f"Cannot create transfer destination: {exc}")
        return

    for file_record in job["files"]:
        if transfer_job_is_cancelled(job_id):
            return
        if file_record["status"] == "SKIPPED":
            continue
        file_id = file_record["id"]
        source = _resolve_under_root(source_root, file_record["source_path"], "source_path")
        destination = _resolve_under_root(
            destination_root, file_record["destination_path"], "destination_path"
        )
        temporary_destination = destination.with_name(f".{destination.name}.transfer-{file_id}")
        phase = "transfer"
        try:
            if destination.exists():
                raise RuntimeError("destination already exists")
            if temporary_destination.exists():
                raise RuntimeError("temporary destination already exists")
            update_transfer_file_progress(file_id, 0, "TRANSFERRING")

            def report(transferred: int) -> None:
                update_transfer_file_progress(file_id, transferred)
                if transfer_job_is_cancelled(job_id):
                    raise TransferCancelled()

            _copy_path(source, temporary_destination, report)
            if transfer_job_is_cancelled(job_id):
                _remove_path(temporary_destination)
                cancel_transfer_file(file_id)
                return
            os.replace(temporary_destination, destination)
            if job["mode"] == "MOVE":
                _remove_path(source)
            if transfer_job_is_cancelled(job_id):
                cancel_transfer_file(file_id)
                return

            phase = "ingest"
            ingest_upload(
                upload_root=destination_root,
                data_root=settings.scan_root,
                relative_path=file_record["destination_path"],
                write_delay_ms=settings.scan_write_delay_ms,
            )
            finish_transfer_file(file_id, True)
        except TransferCancelled:
            if temporary_destination.exists():
                _remove_path(temporary_destination)
            cancel_transfer_file(file_id)
            return
        except Exception as exc:  # Keep processing the remaining requested files.
            if temporary_destination.exists():
                _remove_path(temporary_destination)
            finish_transfer_file(file_id, False, f"{phase} failed: {exc}")
    finalize_transfer_job(job_id)
