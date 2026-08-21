from __future__ import annotations

import errno
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from app.adapters import AdapterRegistry
from app.adapters.base import MetadataError, MetadataIgnored
from app.containers import iter_candidates
from app.domain import DiscoveryError


class IngestError(ValueError):
    """Raised when a staged upload cannot be promoted into a source directory."""


@dataclass(frozen=True)
class IngestResult:
    expected_source: str
    upload_path: str
    data_path: str
    move_method: str
    scan: dict[str, int]

    def to_dict(self) -> dict:
        return asdict(self)


def _source_for_relative_path(relative_path: str, registry: AdapterRegistry) -> tuple[str, Path]:
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        raise IngestError("Path must be a relative path below /upload")
    if len(relative.parts) < 2 or relative.parts[0] in {"", "."}:
        raise IngestError("Use a product path such as gf3/batch-001/product.zip")

    source_by_directory = {
        source_code.lower(): source_code for source_code in registry.source_codes
    }
    expected_source = source_by_directory.get(relative.parts[0].lower())
    if expected_source is None:
        supported = ", ".join(sorted(source_by_directory))
        raise IngestError(f"Unknown upload source directory: {relative.parts[0]} (supported: {supported})")
    return expected_source, Path(*relative.parts)


def _resolve_child(root: Path, relative: Path, label: str) -> Path:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise IngestError(f"{label} root does not exist: {root}")
    raw_target = root.joinpath(relative)
    try:
        target = raw_target.resolve(strict=True)
    except OSError as exc:
        raise IngestError(f"Upload path does not exist: {raw_target}") from exc
    if target != root and root not in target.parents:
        raise IngestError(f"Unsafe path outside {label} root")

    # Do not accept symlink components. This makes the staging boundary explicit.
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise IngestError("Symbolic links are not allowed in an upload path")
    return target


def _validate_source(target: Path, expected_source: str, registry: AdapterRegistry) -> int:
    recognized = 0
    discovery_errors: list[str] = []
    for result in iter_candidates(target):
        if isinstance(result, DiscoveryError):
            discovery_errors.append(f"{result.path}: {result.message}")
            continue
        try:
            parsed = registry.parse(result)
        except MetadataIgnored:
            continue
        except MetadataError as exc:
            discovery_errors.append(f"{result.metadata_file.name}: {exc}")
            continue
        if parsed is None:
            discovery_errors.append(
                f"{result.metadata_file.name}: no adapter recognized this metadata"
            )
            continue
        if parsed.source != expected_source:
            raise IngestError(
                f"Source directory is {expected_source}, but {result.metadata_file.name} "
                f"is recognized as {parsed.source}"
            )
        recognized += 1

    if discovery_errors:
        raise IngestError("Upload validation failed: " + "; ".join(discovery_errors[:3]))
    if recognized == 0:
        raise IngestError("No primary SAR XML or JSON metadata was found in this upload")
    return recognized


def _move_to_data(staged: Path, destination: Path) -> str:
    if destination.exists():
        raise IngestError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        staged.rename(destination)
        return "rename"
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise IngestError(f"Cannot move upload into data source: {exc}") from exc
    try:
        shutil.move(str(staged), str(destination))
        return "copy_then_delete"
    except OSError as exc:
        raise IngestError(f"Cannot copy upload into data source: {exc}") from exc


def ingest_upload(
    upload_root: str | Path,
    data_root: str | Path,
    relative_path: str,
    force: bool = False,
    write_delay_ms: int = 0,
) -> IngestResult:
    """Validate a staged product, promote it into /data, then scan only it."""
    registry = AdapterRegistry()
    expected_source, relative = _source_for_relative_path(relative_path, registry)
    staged = _resolve_child(Path(upload_root), relative, "upload")
    _validate_source(staged, expected_source, registry)

    data_root_path = Path(data_root).expanduser().resolve()
    if not data_root_path.is_dir():
        raise IngestError(f"Data root does not exist: {data_root_path}")
    destination = data_root_path / expected_source.lower() / Path(*relative.parts[1:])
    move_method = _move_to_data(staged, destination)

    # Import after the move so stored asset paths always refer to /data, never /upload.
    from app.scanner import scan_storage

    report = scan_storage(destination, force=force, write_delay_ms=write_delay_ms)
    return IngestResult(
        expected_source=expected_source,
        upload_path=str(staged),
        data_path=str(destination),
        move_method=move_method,
        scan=report.to_dict(),
    )
