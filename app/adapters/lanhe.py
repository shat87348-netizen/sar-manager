from __future__ import annotations

from xml.etree import ElementTree as ET

from app.adapters.base import (
    MetadataError,
    SarAdapter,
    child_text,
    first_text,
    local_name,
    parse_time_without_timezone,
)
from app.domain import MetadataCandidate, ParsedMetadata


class LanheAdapter(SarAdapter):
    """Parse LANHE RSS1B ``ProductMeta`` XML products."""

    source = "LANHE"

    def supports(self, root: ET.Element) -> bool:
        return (
            local_name(root.tag) == "ProductMeta"
            and (first_text(root, "SatelliteID") or "").upper() == "RSS1B"
        )

    @staticmethod
    def _coordinates(root: ET.Element) -> tuple[tuple[float, float], ...]:
        image_extent = next(
            (element for element in root.iter() if local_name(element.tag) == "ImageExtent"),
            None,
        )
        if image_extent is None:
            raise MetadataError("LANHE ImageExtent is missing")

        corners = {local_name(element.tag): element for element in image_extent}
        coordinates: list[tuple[float, float]] = []
        for corner_name in ("UpperLeft", "UpperRight", "LowerRight", "LowerLeft"):
            corner = corners.get(corner_name)
            if corner is None:
                raise MetadataError(f"LANHE ImageExtent {corner_name} is missing")
            longitude = child_text(corner, "Longitude")
            latitude = child_text(corner, "Latitude")
            if longitude is None or latitude is None:
                raise MetadataError(
                    f"LANHE ImageExtent {corner_name} longitude or latitude is missing"
                )
            try:
                coordinates.append((float(longitude), float(latitude)))
            except ValueError as exc:
                raise MetadataError(
                    f"LANHE ImageExtent {corner_name} coordinates are invalid"
                ) from exc
        return tuple(coordinates)

    def parse(self, root: ET.Element, candidate: MetadataCandidate) -> ParsedMetadata:
        product_id = first_text(root, "ProductID")
        external_id = f"LANHE:{product_id or candidate.metadata_file.name}"
        acquisition_time = parse_time_without_timezone(first_text(root, "ImagingStartTime"))
        if acquisition_time is None:
            raise MetadataError("LANHE ImagingStartTime is missing")

        metadata = {
            "product_id": product_id,
            "satellite": first_text(root, "SatelliteID"),
            "sensor": first_text(root, "SensorID"),
            "receiving_station": first_text(root, "RecStationID"),
            "orbit_id": first_text(root, "OrbitID"),
            "orbit_direction": first_text(root, "OrbitDirection"),
            "imaging_mode": first_text(root, "ImageMode"),
            "look_direction": first_text(root, "LookDirection"),
            "product_level": first_text(root, "ProductLevel"),
            "product_type": first_text(root, "ProductType"),
            "product_format": first_text(root, "ProductFormat"),
            "polarization": first_text(root, "PolarMode"),
            "start_time": first_text(root, "ImagingStartTime"),
            "end_time": first_text(root, "ImagingStopTime"),
            "processing_time": first_text(root, "ProcessingTime"),
            "image_name": first_text(root, "ImageName"),
            "browse_name": first_text(root, "BrowseName"),
            "thumbnail_name": first_text(root, "ThumbName"),
            "pixel_spacing": first_text(root, "PixelSpacing"),
            "map_projection": first_text(root, "MapProjection"),
            "utm_zone": first_text(root, "UtmZone"),
        }
        return ParsedMetadata(
            source=self.source,
            external_id=external_id,
            name=candidate.dataset_name,
            acquisition_time=acquisition_time,
            coordinates=self._coordinates(root),
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
