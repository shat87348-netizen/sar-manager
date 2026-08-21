from __future__ import annotations

from typing import Any

from app.adapters.base import (
    JsonSarAdapter,
    MetadataError,
    MetadataIgnored,
    parse_time_without_timezone,
)
from app.adapters.geometry import polygon_coordinates
from app.domain import MetadataCandidate, ParsedMetadata


class IceyeAdapter(JsonSarAdapter):
    source = "ICEYE"

    def supports(self, document: dict[str, Any]) -> bool:
        properties = document.get("properties")
        return (
            document.get("type") == "Feature"
            and isinstance(properties, dict)
            and str(properties.get("constellation", "")).upper() == "ICEYE"
        )

    def parse(
        self, document: dict[str, Any], candidate: MetadataCandidate
    ) -> ParsedMetadata:
        properties = document["properties"]
        product_type = str(properties.get("sar:product_type", "")).upper()
        if not product_type.startswith("GRD"):
            raise MetadataIgnored(f"ICEYE auxiliary product ignored: {product_type or 'UNKNOWN'}")

        item_id = document.get("id")
        if not item_id:
            raise MetadataError("ICEYE STAC id is missing")
        acquisition_time = parse_time_without_timezone(
            properties.get("datetime") or properties.get("start_datetime")
        )
        if acquisition_time is None:
            raise MetadataError("ICEYE acquisition time is missing")

        metadata = {
            "satellite": properties.get("platform"),
            "product_type": product_type,
            "polarization": properties.get("sar:polarizations"),
            "start_time": properties.get("start_datetime"),
            "end_time": properties.get("end_datetime"),
        }
        return ParsedMetadata(
            source=self.source,
            external_id=f"ICEYE:{item_id}",
            name=candidate.dataset_name,
            acquisition_time=acquisition_time,
            coordinates=polygon_coordinates(document.get("geometry")),
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
