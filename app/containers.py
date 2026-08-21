from __future__ import annotations

import logging
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Union

from app.domain import ContainerType, DiscoveryError, LocatedFile, MetadataCandidate

logger = logging.getLogger(__name__)

MAX_METADATA_BYTES = 10 * 1024 * 1024
METADATA_SUFFIXES = {".xml", ".json"}
DiscoveryResult = Union[MetadataCandidate, DiscoveryError]


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _archive_kind(path: Path) -> ContainerType | None:
    lower = path.name.lower()
    if lower.endswith(".zip"):
        return ContainerType.ZIP
    if lower.endswith((".tar", ".tar.gz", ".tgz")):
        return ContainerType.TAR
    return None


def _dataset_name_from_archive(path: Path) -> str:
    lower = path.name.lower()
    if lower.endswith(".tar.gz"):
        return path.name[:-7]
    if lower.endswith(".tgz"):
        return path.name[:-4]
    return path.stem


def _regular_candidates(
    root: Path, metadata_paths: tuple[Path, ...] | None = None
) -> Iterator[DiscoveryResult]:
    paths = metadata_paths or tuple(sorted(root.rglob("*")))
    for metadata_path in paths:
        if (
            not metadata_path.is_file()
            or metadata_path.suffix.lower() not in METADATA_SUFFIXES
        ):
            continue
        try:
            size = metadata_path.stat().st_size
            if size > MAX_METADATA_BYTES:
                yield DiscoveryError(
                    str(metadata_path),
                    f"Metadata exceeds {MAX_METADATA_BYTES} bytes",
                )
                continue
            metadata_bytes = metadata_path.read_bytes()
            # Include descendants as well as direct siblings. This supports products
            # whose image and preview are placed in nested subdirectories.
            related_files = tuple(
                LocatedFile(
                    name=item.name,
                    storage_root=str(root),
                    container_type=ContainerType.FILE,
                    relative_path=item.relative_to(root).as_posix(),
                    size_bytes=item.stat().st_size,
                )
                for item in sorted(metadata_path.parent.rglob("*"))
                if item.is_file()
            )
            metadata_location = next(
                item
                for item in related_files
                if item.relative_path == metadata_path.relative_to(root).as_posix()
            )
            yield MetadataCandidate(
                metadata_location,
                metadata_bytes,
                related_files,
                metadata_path.parent.name,
            )
        except (OSError, StopIteration) as exc:
            yield DiscoveryError(str(metadata_path), str(exc), ContainerType.FILE)


def _zip_candidates(root: Path, archive: Path) -> Iterator[DiscoveryResult]:
    archive_rel = archive.relative_to(root).as_posix()
    try:
        with zipfile.ZipFile(archive) as handle:
            infos = [
                info
                for info in handle.infolist()
                if not info.is_dir() and _safe_member_name(info.filename)
            ]
            for info in infos:
                if PurePosixPath(info.filename).suffix.lower() not in METADATA_SUFFIXES:
                    continue
                if info.file_size > MAX_METADATA_BYTES:
                    yield DiscoveryError(
                        f"{archive_rel}!/{info.filename}",
                        f"Metadata exceeds {MAX_METADATA_BYTES} bytes",
                        ContainerType.ZIP,
                    )
                    continue
                parent_path = PurePosixPath(info.filename).parent
                related_infos = [
                    member
                    for member in infos
                    if member.filename == info.filename
                    or PurePosixPath(member.filename).is_relative_to(parent_path)
                ]
                related_files = tuple(
                    LocatedFile(
                        name=PurePosixPath(member.filename).name,
                        storage_root=str(root),
                        container_type=ContainerType.ZIP,
                        archive_path=archive_rel,
                        member_path=member.filename,
                        size_bytes=member.file_size,
                    )
                    for member in sorted(related_infos, key=lambda value: value.filename)
                )
                metadata_location = next(
                    item for item in related_files if item.member_path == info.filename
                )
                dataset_name = (
                    PurePosixPath(info.filename).parent.name
                    or _dataset_name_from_archive(archive)
                )
                yield MetadataCandidate(
                    metadata_location,
                    handle.read(info),
                    related_files,
                    dataset_name,
                )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        yield DiscoveryError(archive_rel, str(exc), ContainerType.ZIP)


def _tar_candidates(root: Path, archive: Path) -> Iterator[DiscoveryResult]:
    archive_rel = archive.relative_to(root).as_posix()
    try:
        with tarfile.open(archive, mode="r:*") as handle:
            members = [
                member
                for member in handle.getmembers()
                if member.isfile() and _safe_member_name(member.name)
            ]
            for member in members:
                if PurePosixPath(member.name).suffix.lower() not in METADATA_SUFFIXES:
                    continue
                if member.size > MAX_METADATA_BYTES:
                    yield DiscoveryError(
                        f"{archive_rel}!/{member.name}",
                        f"Metadata exceeds {MAX_METADATA_BYTES} bytes",
                        ContainerType.TAR,
                    )
                    continue
                extracted = handle.extractfile(member)
                if extracted is None:
                    yield DiscoveryError(
                        f"{archive_rel}!/{member.name}",
                        "Cannot read metadata member",
                        ContainerType.TAR,
                    )
                    continue
                parent_path = PurePosixPath(member.name).parent
                related_members = [
                    item
                    for item in members
                    if item.name == member.name
                    or PurePosixPath(item.name).is_relative_to(parent_path)
                ]
                related_files = tuple(
                    LocatedFile(
                        name=PurePosixPath(item.name).name,
                        storage_root=str(root),
                        container_type=ContainerType.TAR,
                        archive_path=archive_rel,
                        member_path=item.name,
                        size_bytes=item.size,
                    )
                    for item in sorted(related_members, key=lambda value: value.name)
                )
                metadata_location = next(
                    item for item in related_files if item.member_path == member.name
                )
                dataset_name = (
                    PurePosixPath(member.name).parent.name
                    or _dataset_name_from_archive(archive)
                )
                yield MetadataCandidate(
                    metadata_location,
                    extracted.read(),
                    related_files,
                    dataset_name,
                )
    except (OSError, tarfile.TarError) as exc:
        yield DiscoveryError(archive_rel, str(exc), ContainerType.TAR)


def iter_candidates(storage_root: str | Path) -> Iterator[DiscoveryResult]:
    """Yield XML/JSON candidates recursively from directories and archives."""

    root = Path(storage_root).expanduser().resolve()
    if root.is_file():
        if root.suffix.lower() in METADATA_SUFFIXES:
            yield from _regular_candidates(root.parent, (root,))
            return
        kind = _archive_kind(root)
        if kind == ContainerType.ZIP:
            yield from _zip_candidates(root.parent, root)
            return
        if kind == ContainerType.TAR:
            yield from _tar_candidates(root.parent, root)
            return
        yield DiscoveryError(str(root), "Target is not a metadata file or supported archive")
        return
    if not root.is_dir():
        yield DiscoveryError(str(root), "Storage root is not a directory")
        return

    yield from _regular_candidates(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        kind = _archive_kind(path)
        if kind == ContainerType.ZIP:
            yield from _zip_candidates(root, path)
        elif kind == ContainerType.TAR:
            yield from _tar_candidates(root, path)
