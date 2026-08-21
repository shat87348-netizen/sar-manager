from __future__ import annotations

from typing import Any

from app.adapters.base import JsonSarAdapter, MetadataError, parse_time_without_timezone
from app.adapters.geometry import raster_utm_corners
from app.domain import MetadataCandidate, ParsedMetadata


class CapellaAdapter(JsonSarAdapter):
    source = "CAPELLA"

    def supports(self, document: dict[str, Any]) -> bool:
        collect = document.get("collect")
        return isinstance(collect, dict) and str(collect.get("platform", "")).lower().startswith(
            "capella"
        )

    def parse(
        self, document: dict[str, Any], candidate: MetadataCandidate
    ) -> ParsedMetadata:
        collect = document["collect"]
        collect_id = collect.get("collect_id")
        if not collect_id:
            raise MetadataError("Capella collect_id is missing")

        image = collect.get("image")
        if not isinstance(image, dict):
            raise MetadataError("Capella image metadata is missing")
        center_pixel = image.get("center_pixel")
        center_time_text = (
            center_pixel.get("center_time") if isinstance(center_pixel, dict) else None
        )
        acquisition_time = parse_time_without_timezone(
            center_time_text or collect.get("start_timestamp")
        )
        if acquisition_time is None:
            raise MetadataError("Capella acquisition time is missing")

        image_geometry = image.get("image_geometry")
        if not isinstance(image_geometry, dict):
            raise MetadataError("Capella image geometry is missing")
        coordinate_system = image_geometry.get("coordinate_system")
        wkt = coordinate_system.get("wkt") if isinstance(coordinate_system, dict) else None
        if not isinstance(wkt, str):
            raise MetadataError("Capella coordinate system WKT is missing")

        metadata = {
            "satellite": collect.get("platform"),
            "imaging_mode": collect.get("mode"),
            "product_type": document.get("product_type"),
            "product_version": document.get("product_version"),
            "start_time": collect.get("start_timestamp"),
            "end_time": collect.get("stop_timestamp"),
        }
        return ParsedMetadata(
            source=self.source,
            external_id=f"CAPELLA:{collect_id}",
            name=candidate.dataset_name,
            acquisition_time=acquisition_time,
            coordinates=raster_utm_corners(
                image_geometry.get("geotransform"),
                image.get("rows"),
                image.get("columns"),
                wkt,
            ),
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
