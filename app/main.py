from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.asset_service import asset_response
from app.adapters.base import MetadataError, parse_time_without_timezone
from app.adapters.registry import AdapterRegistry
from app.config import get_settings
from app.db import close_pool, open_pool
from app.repository import (
    cancel_transfer_job,
    create_transfer_job,
    fail_interrupted_transfer_jobs,
    get_asset,
    get_dataset,
    get_dataset_files,
    get_transfer_job,
    get_source_counts,
    get_stats,
    list_transfer_jobs,
    query_datasets,
)
from app.scanner import scan_storage
from app.transfer import (
    TransferJobRequest,
    prepare_transfer_files,
    run_transfer_job,
    transfer_destination_subdirectory,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    # A process restart cannot safely resume a partial filesystem copy. Surface
    # the interrupted job to callers instead of reporting stale RUNNING state.
    fail_interrupted_transfer_jobs()
    yield
    close_pool()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    try:
        values = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bbox must contain four numbers") from exc
    if len(values) != 4:
        raise HTTPException(status_code=422, detail="bbox must be minLon,minLat,maxLon,maxLat")
    min_lon, min_lat, max_lon, max_lat = values
    if min_lon > max_lon or min_lat > max_lat:
        raise HTTPException(status_code=422, detail="bbox minimums must not exceed maximums")
    return min_lon, min_lat, max_lon, max_lat


def _parse_query_time(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        return parse_time_without_timezone(value)
    except MetadataError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field}: {value}") from exc


def _public_url(path: str, request: Request) -> str:
    base_url = settings.public_base_url.strip().rstrip("/")
    if not base_url:
        base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/{path.lstrip('/')}"


def _feature(row: dict, request: Request) -> dict:
    assets = {
        kind: {**asset, "url": _public_url(asset["url"], request)}
        for kind, asset in row["assets"].items()
    }
    return {
        "type": "Feature",
        "id": str(row["id"]),
        "geometry": row["geometry"],
        "properties": {
            "external_id": row["external_id"],
            "source": row["source"],
            "name": row["name"],
            "acquisition_time": row["acquisition_time"].isoformat(sep=" ")
            if row["acquisition_time"]
            else None,
            "status": row["status"],
            "metadata": row["metadata"],
            "assets": assets,
            "data_directory": row.get("data_directory"),
            "thumbnail_url": assets.get("THUMBNAIL", {}).get("url"),
            "tiff_url": assets.get("TIFF", {}).get("url"),
            "metadata_url": assets.get("XML", {}).get("url")
            or assets.get("JSON", {}).get("url"),
            "error_message": row["error_message"],
        },
    }


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/web/")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/sar")
def list_sar(
    request: Request,
    start_time_text: str | None = Query(None, alias="startTime"),
    end_time_text: str | None = Query(None, alias="endTime"),
    bbox: str | None = None,
    source: str | None = None,
    name: str | None = None,
    include_non_ready: bool = Query(False, alias="includeNonReady"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    start_time = _parse_query_time(start_time_text, "startTime")
    end_time = _parse_query_time(end_time_text, "endTime")
    if start_time and end_time and start_time > end_time:
        raise HTTPException(status_code=422, detail="startTime must not exceed endTime")
    statuses = (
        ("READY", "PARTIAL", "INVALID_METADATA", "UNKNOWN_SOURCE", "DUPLICATE")
        if include_non_ready
        else ("READY",)
    )
    # Read one extra row so the caller knows whether it can request another page.
    rows = query_datasets(
        start_time,
        end_time,
        _parse_bbox(bbox),
        source,
        statuses,
        limit + 1,
        offset,
        name,
    )
    has_more = len(rows) > limit
    if has_more:
        rows.pop()
    return {
        "type": "FeatureCollection",
        "features": [_feature(row, request) for row in rows],
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
    }


@app.get("/api/v1/sar/{dataset_id}")
def sar_detail(dataset_id: UUID, request: Request) -> dict:
    row = get_dataset(dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="SAR dataset not found")
    return _feature(row, request)


@app.get("/api/v1/sar/{dataset_id}/files")
def sar_files(dataset_id: UUID, request: Request) -> dict:
    dataset = get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="SAR dataset not found")
    files = get_dataset_files(dataset_id)
    return {
        "dataset_id": str(dataset_id),
        "external_id": dataset["external_id"],
        "name": dataset["name"],
        "files": [
            {
                "id": str(item["id"]),
                "kind": item["kind"],
                "file_name": item["file_name"],
                "path": item["member_path"] or item["relative_path"],
                "container_type": item["container_type"],
                "mime_type": item["mime_type"],
                "size_bytes": item["size_bytes"],
                "url": _public_url(f"/api/v1/assets/{item['id']}", request),
            }
            for item in files
        ],
    }


@app.get("/api/v1/assets/{asset_id}")
def download_asset(asset_id: UUID):
    asset = get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset_response(asset)


@app.get("/api/v1/stats")
def stats() -> dict:
    return get_stats()


@app.get("/api/v1/sources")
def list_sources() -> dict:
    """List all source types supported by this installation and their counts."""
    counts = get_source_counts()
    return {
        "sources": [
            {"code": source_code, "count": counts.get(source_code, 0)}
            for source_code in AdapterRegistry().source_codes
        ]
    }


@app.post("/api/v1/transfer-jobs", status_code=status.HTTP_202_ACCEPTED)
def create_transfer(
    payload: TransferJobRequest, background_tasks: BackgroundTasks
) -> dict:
    """Copy or move products from an approved LAN mount, then ingest them."""
    files = prepare_transfer_files(payload)
    job = create_transfer_job(
        source=payload.source.upper(),
        server=payload.server,
        destination_subdirectory=str(transfer_destination_subdirectory(payload)),
        mode=payload.mode,
        files=files,
    )
    background_tasks.add_task(run_transfer_job, job["id"])
    return _transfer_job_response(job)


@app.get("/api/v1/transfer-jobs")
def transfer_jobs(
    status_text: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    return {
        "jobs": [
            _transfer_job_response(job) for job in list_transfer_jobs(status_text, limit)
        ]
    }


@app.get("/api/v1/transfer-jobs/{job_id}")
def transfer_job_detail(job_id: UUID) -> dict:
    job = get_transfer_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="transfer job not found")
    return _transfer_job_response(job)


@app.post("/api/v1/transfer-jobs/{job_id}/cancel")
def cancel_transfer(job_id: UUID) -> dict:
    if not cancel_transfer_job(job_id):
        raise HTTPException(status_code=409, detail="transfer job cannot be cancelled")
    job = get_transfer_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="transfer job not found")
    return _transfer_job_response(job)


def _transfer_job_response(job: dict) -> dict:
    files = job.get("files", [])
    transferred_bytes = (
        sum(item["transferred_bytes"] for item in files)
        if files
        else job["transferred_bytes"]
    )
    total_bytes = job["total_bytes"]
    percent = round((transferred_bytes / total_bytes) * 100, 2) if total_bytes else 100.0
    file_phases = [_transfer_file_phase(item) for item in files]
    if job["status"] == "RUNNING" and "INGESTING" in file_phases:
        phase = "INGESTING"
    elif job["status"] == "RUNNING":
        phase = "TRANSFERRING"
    else:
        phase = job["status"]
    return {
        "job_id": job["id"],
        "source": job["source"],
        "server": job["server"],
        "destination_subdirectory": job["destination_subdirectory"],
        "mode": job["mode"],
        "status": job["status"],
        "phase": phase,
        "progress": {
            "total_files": job["total_files"],
            "completed_files": job["completed_files"],
            "failed_files": job["failed_files"],
            "total_bytes": total_bytes,
            "transferred_bytes": transferred_bytes,
            "percent": percent,
        },
        "error_message": job["error_message"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "files": [
            {
                "source_path": item["source_path"],
                "destination_path": item["destination_path"],
                "status": item["status"],
                "phase": _transfer_file_phase(item),
                "size_bytes": item["size_bytes"],
                "transferred_bytes": item["transferred_bytes"],
                "error_message": item["error_message"],
            }
            for item in files
        ],
    }


def _transfer_file_phase(item: dict) -> str:
    status_text = item["status"]
    if status_text == "COMPLETED":
        return "INGESTED"
    if status_text == "TRANSFERRING" and item["transferred_bytes"] >= item["size_bytes"]:
        return "INGESTING"
    return status_text


@app.post("/api/v1/admin/scan")
def run_scan() -> dict:
    return scan_storage(settings.scan_root).to_dict()


web_directory = Path(__file__).resolve().parents[1] / "web"
app.mount("/web", StaticFiles(directory=web_directory, html=True), name="web")
