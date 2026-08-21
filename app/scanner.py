from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.adapters import AdapterRegistry
from app.adapters.base import MetadataError, MetadataIgnored
from app.assets import select_assets, select_files
from app.containers import iter_candidates
from app.domain import (
    AssetKind,
    DatasetStatus,
    DiscoveryError,
    IngestRecord,
    MetadataCandidate,
    ParsedMetadata,
)
from app.repository import get_existing_metadata_hashes, save_ingest_record


@dataclass
class ScanReport:
    discovered_metadata: int = 0
    discovered_xml: int = 0
    discovered_json: int = 0
    imported: int = 0
    ready: int = 0
    partial: int = 0
    invalid_metadata: int = 0
    unknown_source: int = 0
    duplicate: int = 0
    duplicate_skipped: int = 0
    unchanged_skipped: int = 0
    ignored_metadata: int = 0
    discovery_errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _unknown_record(
    candidate: MetadataCandidate,
    sha256: str,
    status: DatasetStatus,
    error: str,
) -> IngestRecord:
    parsed = ParsedMetadata(
        source="UNKNOWN",
        external_id=f"UNKNOWN:{sha256[:24]}",
        name=candidate.dataset_name,
        acquisition_time=None,
        coordinates=(),
        metadata={
            "metadata_file": candidate.metadata_file.name,
            "metadata_format": candidate.format,
        },
    )
    return IngestRecord(
        parsed=parsed,
        status=status,
        xml_sha256=sha256,
        assets=select_assets(candidate),
        files=select_files(candidate),
        error_message=error,
    )


def _status_for(parsed: ParsedMetadata, assets: tuple) -> tuple[DatasetStatus, str | None]:
    missing: list[str] = []
    kinds = {asset.kind for asset in assets}
    if parsed.acquisition_time is None:
        missing.append("acquisition_time")
    if parsed.footprint_wkt is None:
        missing.append("footprint")
    if AssetKind.TIFF not in kinds:
        missing.append("TIFF")
    if AssetKind.THUMBNAIL not in kinds:
        missing.append("THUMBNAIL")
    if not missing:
        return DatasetStatus.READY, None
    return DatasetStatus.PARTIAL, "Missing: " + ", ".join(missing)


def scan_storage(
    storage_root: str | Path,
    force: bool = False,
    write_delay_ms: int = 0,
) -> ScanReport:
    registry = AdapterRegistry()
    report = ScanReport()
    seen: dict[str, str] = {}
    known_hashes = {} if force else get_existing_metadata_hashes()

    for result in iter_candidates(storage_root):
        if isinstance(result, DiscoveryError):
            report.discovery_errors += 1
            continue
        candidate = result
        report.discovered_metadata += 1
        if candidate.format == "XML":
            report.discovered_xml += 1
        elif candidate.format == "JSON":
            report.discovered_json += 1
        sha256 = hashlib.sha256(candidate.metadata_bytes).hexdigest()
        try:
            parsed = registry.parse(candidate)
            if parsed is None:
                unknown_id = f"UNKNOWN:{sha256[:24]}"
                if known_hashes.get(unknown_id) == sha256:
                    report.unchanged_skipped += 1
                    continue
                record = _unknown_record(
                    candidate,
                    sha256,
                    DatasetStatus.UNKNOWN_SOURCE,
                    f"No adapter recognized this {candidate.format}",
                )
            else:
                previous_sha = seen.get(parsed.external_id)
                if previous_sha == sha256:
                    report.duplicate_skipped += 1
                    continue
                seen[parsed.external_id] = sha256
                if previous_sha is None and known_hashes.get(parsed.external_id) == sha256:
                    report.unchanged_skipped += 1
                    continue
                assets = select_assets(candidate)
                status, error = _status_for(parsed, assets)
                if previous_sha is not None and previous_sha != sha256:
                    status = DatasetStatus.DUPLICATE
                    error = "Conflicting metadata content for the same external_id"
                record = IngestRecord(
                    parsed=parsed,
                    status=status,
                    xml_sha256=sha256,
                    assets=assets,
                    files=select_files(candidate),
                    error_message=error,
                )
        except MetadataIgnored:
            report.ignored_metadata += 1
            continue
        except MetadataError as exc:
            unknown_id = f"UNKNOWN:{sha256[:24]}"
            if known_hashes.get(unknown_id) == sha256:
                report.unchanged_skipped += 1
                continue
            record = _unknown_record(
                candidate, sha256, DatasetStatus.INVALID_METADATA, str(exc)
            )

        save_ingest_record(record)
        if write_delay_ms > 0:
            time.sleep(write_delay_ms / 1000)
        report.imported += 1
        if record.status == DatasetStatus.READY:
            report.ready += 1
        elif record.status == DatasetStatus.PARTIAL:
            report.partial += 1
        elif record.status == DatasetStatus.INVALID_METADATA:
            report.invalid_metadata += 1
        elif record.status == DatasetStatus.UNKNOWN_SOURCE:
            report.unknown_source += 1
        elif record.status == DatasetStatus.DUPLICATE:
            report.duplicate += 1
    return report
