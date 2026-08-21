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


class StrixAdapter(SarAdapter):
    source = "STRIX"

    def supports(self, root: ET.Element) -> bool:
        if local_name(root.tag) != "EarthObservation":
            return False
        return any(
            local_name(item.tag) == "shortName"
            and item.text
            and item.text.strip().lower() == "strix"
            for item in root.iter()
        )

    @staticmethod
    def _vendor_value(root: ET.Element, attribute_name: str) -> str | None:
        for specific in root.iter():
            if local_name(specific.tag) != "SpecificInformation":
                continue
            if child_text(specific, "localAttribute") == attribute_name:
                return child_text(specific, "localValue")
        return None

    def parse(self, root: ET.Element, candidate: MetadataCandidate) -> ParsedMetadata:
        time_text = self._vendor_value(root, "sceneCenterDateTime")
        acquisition_time = parse_time_without_timezone(time_text)
        if acquisition_time is None:
            raise MetadataError("StriX sceneCenterDateTime is missing")

        pos_list = first_text(root, "posList")
        coordinates: list[tuple[float, float]] = []
        if pos_list:
            values = [float(value) for value in pos_list.split()]
            if len(values) % 2:
                raise MetadataError("StriX GML posList contains an odd number of values")
            # The supplied StriX XML uses GML axis order latitude, longitude.
            for latitude, longitude in zip(values[0::2], values[1::2]):
                coordinates.append((longitude, latitude))

        stem = candidate.metadata_file.name.rsplit(".", 1)[0]
        if stem.upper().startswith("PAR-"):
            stem = stem[4:]
        external_id = f"STRIX:{stem.upper()}"
        metadata = {
            "satellite": "StriX",
            "polarization": first_text(root, "polarisationChannels"),
            "imaging_mode": first_text(root, "operationalMode"),
            "orbit_direction": first_text(root, "orbitDirection"),
            "reference_system": first_text(root, "referenceSystemIdentifier"),
        }
        return ParsedMetadata(
            source=self.source,
            external_id=external_id,
            name=candidate.dataset_name,
            acquisition_time=acquisition_time,
            coordinates=tuple(coordinates),
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
