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


class Gf3Adapter(SarAdapter):
    source = "GF3"

    def supports(self, root: ET.Element) -> bool:
        return (
            local_name(root.tag).lower() == "product"
            and (first_text(root, "satellite") or "").upper() == "GF3"
        )

    def parse(self, root: ET.Element, candidate: MetadataCandidate) -> ParsedMetadata:
        product_id = first_text(root, "productID")
        external_id = f"GF3:{product_id or candidate.metadata_file.name}"
        acquisition_time = parse_time_without_timezone(first_text(root, "CenterTime"))

        corner = next((item for item in root.iter() if local_name(item.tag) == "corner"), None)
        coordinates: list[tuple[float, float]] = []
        if corner is not None:
            by_name = {local_name(item.tag): item for item in corner}
            for name in ("topLeft", "topRight", "bottomRight", "bottomLeft"):
                point = by_name.get(name)
                if point is None:
                    continue
                latitude = child_text(point, "latitude")
                longitude = child_text(point, "longitude")
                if latitude is None or longitude is None:
                    continue
                coordinates.append((float(longitude), float(latitude)))

        if acquisition_time is None:
            raise MetadataError("GF3 CenterTime is missing")

        metadata = {
            "product_id": product_id,
            "satellite": first_text(root, "satellite"),
            "orbit_id": first_text(root, "orbitID"),
            "imaging_mode": first_text(root, "imagingMode"),
            "polarization": first_text(root, "productPolar") or first_text(root, "polarMode"),
            "product_level": first_text(root, "productLevel"),
        }
        return ParsedMetadata(
            source=self.source,
            external_id=external_id,
            name=candidate.dataset_name,
            acquisition_time=acquisition_time,
            coordinates=tuple(coordinates),
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
