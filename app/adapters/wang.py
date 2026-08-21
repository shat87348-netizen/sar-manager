from __future__ import annotations

from xml.etree import ElementTree as ET

from app.adapters.base import (
    MetadataError,
    SarAdapter,
    first_text,
    local_name,
    parse_time_without_timezone,
)
from app.domain import MetadataCandidate, ParsedMetadata


class WangAdapter(SarAdapter):
    """Parse WANG SARProductMetadata XML products."""

    source = "WANG"
    _NAMESPACE_MARKER = "pj3-ips-sar:product-metadata"

    def supports(self, root: ET.Element) -> bool:
        return (
            local_name(root.tag) == "SARProductMetadata"
            and self._NAMESPACE_MARKER in root.tag
        )

    @staticmethod
    def _footprint(root: ET.Element) -> tuple[tuple[float, float], ...]:
        footprint = next(
            (
                element
                for element in root.iter()
                if local_name(element.tag) == "GeographicFootprint"
            ),
            None,
        )
        if footprint is None:
            raise MetadataError("WANG GeographicFootprint is missing")

        points_by_name = {local_name(element.tag): element for element in footprint}
        coordinates: list[tuple[float, float]] = []
        for point_name in ("UpperLeft", "UpperRight", "LowerRight", "LowerLeft"):
            point = points_by_name.get(point_name)
            if point is None:
                raise MetadataError(f"WANG footprint point is missing: {point_name}")
            longitude = point.get("longitudeDegrees")
            latitude = point.get("latitudeDegrees")
            if longitude is None or latitude is None:
                raise MetadataError(f"WANG footprint coordinates are missing: {point_name}")
            try:
                coordinates.append((float(longitude), float(latitude)))
            except ValueError as exc:
                raise MetadataError(
                    f"WANG footprint coordinates are invalid: {point_name}"
                ) from exc
        return tuple(coordinates)

    def parse(self, root: ET.Element, candidate: MetadataCandidate) -> ParsedMetadata:
        product_name = first_text(root, "ProductName")
        if not product_name:
            raise MetadataError("WANG ProductName is missing")

        acquisition_time = parse_time_without_timezone(
            first_text(root, "CenterTimeUTC") or first_text(root, "StartTimeUTC")
        )
        if acquisition_time is None:
            raise MetadataError("WANG acquisition time is missing")

        metadata = {
            "product_name": product_name,
            "satellite": first_text(root, "Satellite"),
            "instrument": first_text(root, "Instrument"),
            "frequency_band": first_text(root, "FrequencyBand"),
            "imaging_mode": first_text(root, "ImagingMode"),
            "product_level": first_text(root, "ProductLevel"),
            "product_type": first_text(root, "ProductType"),
            "observation_direction": first_text(root, "ObservationDirection"),
            "start_time": first_text(root, "StartTimeUTC"),
            "end_time": first_text(root, "StopTimeUTC"),
            "projection": first_text(root, "Name"),
            "epsg": first_text(root, "EPSG"),
            "pixel_spacing": first_text(root, "PixelSpacing"),
            "processing_status": first_text(root, "ProcessingStatus"),
            "correction_method": first_text(root, "GeometricCorrectionMethod"),
        }
        return ParsedMetadata(
            source=self.source,
            external_id=f"WANG:{product_name}",
            name=candidate.dataset_name,
            acquisition_time=acquisition_time,
            coordinates=self._footprint(root),
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
