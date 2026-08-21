from __future__ import annotations

from datetime import datetime
from typing import Any

from app.adapters.base import JsonSarAdapter, MetadataError, parse_time_without_timezone
from app.adapters.geometry import polygon_coordinates
from app.domain import MetadataCandidate, ParsedMetadata


def _center_time(start: datetime, end: datetime) -> datetime:
    return start + (end - start) / 2


class UmbraAdapter(JsonSarAdapter):
    source = "UMBRA"

    def supports(self, document: dict[str, Any]) -> bool:
        return str(document.get("vendor", "")).lower().startswith("umbra") and isinstance(
            document.get("collects"), list
        )

    def parse(
        self, document: dict[str, Any], candidate: MetadataCandidate
    ) -> ParsedMetadata:
        collects = document.get("collects")
        if not collects or not isinstance(collects[0], dict):
            raise MetadataError("Umbra collects[0] is missing")
        collect = collects[0]

        start = parse_time_without_timezone(collect.get("startAtUTC"))
        end = parse_time_without_timezone(collect.get("endAtUTC"))
        if start is None or end is None:
            raise MetadataError("Umbra collection time is missing")
        if end < start:
            raise MetadataError("Umbra endAtUTC precedes startAtUTC")

        collect_id = collect.get("id")
        if not collect_id:
            raise MetadataError("Umbra collect id is missing")

        metadata = {
            "satellite": document.get("umbraSatelliteName"),
            "imaging_mode": document.get("imagingMode"),
            "product_sku": document.get("productSku"),
            "polarization": collect.get("polarizations"),
            "start_time": collect.get("startAtUTC"),
            "end_time": collect.get("endAtUTC"),
        }
        return ParsedMetadata(
            source=self.source,
            external_id=f"UMBRA:{collect_id}",
            name=candidate.dataset_name,
            acquisition_time=_center_time(start, end),
            coordinates=polygon_coordinates(collect.get("footprintPolygonLla")),
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
