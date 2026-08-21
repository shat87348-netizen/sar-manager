from __future__ import annotations

import json
from xml.etree import ElementTree as ET

from app.adapters.base import JsonSarAdapter, MetadataError, SarAdapter
from app.adapters.capella import CapellaAdapter
from app.adapters.gf3 import Gf3Adapter
from app.adapters.iceye import IceyeAdapter
from app.adapters.lanhe import LanheAdapter
from app.adapters.strix import StrixAdapter
from app.adapters.umbra import UmbraAdapter
from app.domain import MetadataCandidate, ParsedMetadata


class AdapterRegistry:
    def __init__(
        self,
        xml_adapters: tuple[SarAdapter, ...] | None = None,
        json_adapters: tuple[JsonSarAdapter, ...] | None = None,
    ) -> None:
        self.xml_adapters = xml_adapters or (
            Gf3Adapter(),
            StrixAdapter(),
            LanheAdapter(),
        )
        self.json_adapters = json_adapters or (
            UmbraAdapter(),
            CapellaAdapter(),
            IceyeAdapter(),
        )

    @property
    def source_codes(self) -> tuple[str, ...]:
        """Return the source codes that this installation can recognize.

        Keeping this list on the adapter registry means a new source becomes
        available to frontend filters as soon as its adapter is registered.
        """
        return tuple(
            sorted(
                {
                    adapter.source
                    for adapter in (*self.xml_adapters, *self.json_adapters)
                }
            )
        )

    def parse(self, candidate: MetadataCandidate) -> ParsedMetadata | None:
        if candidate.format == "XML":
            try:
                root = ET.fromstring(candidate.metadata_bytes)
            except ET.ParseError as exc:
                raise MetadataError(f"Invalid XML: {exc}") from exc
            for adapter in self.xml_adapters:
                if adapter.supports(root):
                    return adapter.parse(root, candidate)
            return None

        if candidate.format == "JSON":
            try:
                document = json.loads(candidate.metadata_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MetadataError(f"Invalid JSON: {exc}") from exc
            if not isinstance(document, dict):
                raise MetadataError("JSON metadata root must be an object")
            for adapter in self.json_adapters:
                if adapter.supports(document):
                    return adapter.parse(document, candidate)
            return None

        raise MetadataError(f"Unsupported metadata format: {candidate.format}")
