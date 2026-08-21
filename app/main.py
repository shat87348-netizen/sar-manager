from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.asset_service import asset_response
from app.adapters.base import MetadataError, parse_time_without_timezone
from app.adapters.registry import AdapterRegistry
from app.config import get_settings
from app.db import close_pool, open_pool
from app.repository import (
    get_asset,
    get_dataset,
    get_dataset_files,
    get_source_counts,
    get_stats,
    query_datasets,
)
from app.scanner import scan_storage


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
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


@app.post("/api/v1/admin/scan")
def run_scan() -> dict:
    return scan_storage(settings.scan_root).to_dict()


web_directory = Path(__file__).resolve().parents[1] / "web"
app.mount("/web", StaticFiles(directory=web_directory, html=True), name="web")
