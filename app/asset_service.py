from __future__ import annotations

import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse


def _safe_path(root: str, relative: str) -> Path:
    root_path = Path(root).resolve()
    target = root_path.joinpath(relative).resolve()
    if target != root_path and root_path not in target.parents:
        raise HTTPException(status_code=400, detail="Unsafe asset path")
    return target


def _safe_member(member: str) -> bool:
    path = PurePosixPath(member)
    return bool(member) and not path.is_absolute() and ".." not in path.parts


def _zip_chunks(path: Path, member: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with zipfile.ZipFile(path) as archive, archive.open(member) as stream:
        while chunk := stream.read(chunk_size):
            yield chunk


def _tar_chunks(path: Path, member: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with tarfile.open(path, mode="r:*") as archive:
        info = archive.getmember(member)
        stream = archive.extractfile(info)
        if stream is None:
            return
        with stream:
            while chunk := stream.read(chunk_size):
                yield chunk


def asset_response(asset: dict[str, Any]):
    headers = {"Content-Disposition": f'inline; filename="{asset["file_name"]}"'}
    if asset["container_type"] == "FILE":
        path = _safe_path(asset["storage_root"], asset["relative_path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Asset file not found")
        return FileResponse(
            path,
            media_type=asset["mime_type"],
            filename=asset["file_name"],
            content_disposition_type="inline",
        )

    member = asset["member_path"]
    if not _safe_member(member):
        raise HTTPException(status_code=400, detail="Unsafe archive member path")
    archive_path = _safe_path(asset["storage_root"], asset["archive_path"])
    if not archive_path.is_file():
        raise HTTPException(status_code=404, detail="Archive file not found")
    if asset.get("size_bytes") is not None:
        headers["Content-Length"] = str(asset["size_bytes"])
    if asset["container_type"] == "ZIP":
        body = _zip_chunks(archive_path, member)
    elif asset["container_type"] == "TAR":
        body = _tar_chunks(archive_path, member)
    else:
        raise HTTPException(status_code=500, detail="Unsupported container type")
    return StreamingResponse(body, media_type=asset["mime_type"], headers=headers)
