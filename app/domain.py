from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Optional


class DatasetStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INVALID_METADATA = "INVALID_METADATA"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    DUPLICATE = "DUPLICATE"


class AssetKind(str, Enum):
    XML = "XML"
    JSON = "JSON"
    TIFF = "TIFF"
    THUMBNAIL = "THUMBNAIL"


class ContainerType(str, Enum):
    FILE = "FILE"
    ZIP = "ZIP"
    TAR = "TAR"


@dataclass(frozen=True)
class LocatedFile:
    """A file on disk or a member inside an archive."""

    name: str
    storage_root: str
    container_type: ContainerType
    relative_path: Optional[str] = None
    archive_path: Optional[str] = None
    member_path: Optional[str] = None
    size_bytes: Optional[int] = None

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.name).suffix.lower()

    @property
    def mime_type(self) -> str:
        if self.suffix == ".kml":
            return "application/vnd.google-earth.kml+xml"
        return mimetypes.guess_type(self.name)[0] or "application/octet-stream"

    @property
    def file_kind(self) -> str:
        return {
            ".xml": "XML",
            ".json": "JSON",
            ".kml": "KML",
            ".tif": "TIFF",
            ".tiff": "TIFF",
            ".png": "PNG",
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".webp": "WEBP",
        }.get(self.suffix, "OTHER")


@dataclass(frozen=True)
class MetadataCandidate:
    """An XML or JSON description file and the files belonging to its product."""

    metadata_file: LocatedFile
    metadata_bytes: bytes
    related_files: tuple[LocatedFile, ...]
    dataset_name: str

    @property
    def format(self) -> str:
        return self.metadata_file.suffix.removeprefix(".").upper()


# Kept as an import alias for integrations built against version 0.1.0.
XmlCandidate = MetadataCandidate


@dataclass(frozen=True)
class DiscoveryError:
    path: str
    message: str
    container_type: Optional[ContainerType] = None


@dataclass(frozen=True)
class ParsedMetadata:
    source: str
    external_id: str
    name: str
    acquisition_time: Optional[datetime]
    coordinates: tuple[tuple[float, float], ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def footprint_wkt(self) -> Optional[str]:
        if len(self.coordinates) < 4:
            return None
        points = list(self.coordinates)
        if points[0] != points[-1]:
            points.append(points[0])
        return "POLYGON(({}))".format(
            ", ".join(f"{lon:.12f} {lat:.12f}" for lon, lat in points)
        )


@dataclass(frozen=True)
class AssetRecord:
    kind: AssetKind
    location: LocatedFile


@dataclass(frozen=True)
class IngestRecord:
    parsed: ParsedMetadata
    status: DatasetStatus
    xml_sha256: str
    assets: tuple[AssetRecord, ...]
    files: tuple[LocatedFile, ...] = ()
    error_message: Optional[str] = None
