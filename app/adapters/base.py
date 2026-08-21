from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

from app.domain import MetadataCandidate, ParsedMetadata


class MetadataError(ValueError):
    pass


class MetadataIgnored(ValueError):
    """A recognized auxiliary metadata file which is not a primary SAR product."""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def first_text(root: ET.Element, name: str) -> str | None:
    for element in root.iter():
        if local_name(element.tag) == name and element.text and element.text.strip():
            return element.text.strip()
    return None


def child_text(parent: ET.Element, name: str) -> str | None:
    for element in parent:
        if local_name(element.tag) == name and element.text and element.text.strip():
            return element.text.strip()
    return None


def parse_time_without_timezone(value: str | None) -> datetime | None:
    """Parse a source timestamp while deliberately avoiding timezone conversion."""

    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1]
    # Python accepts microseconds, while several SAR vendors emit nanoseconds.
    normalized = re.sub(r"(\.\d{6})\d+(?=([+-]\d{2}:?\d{2})?$)", r"\1", normalized)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MetadataError(f"Invalid acquisition time: {value}") from exc
    return parsed.replace(tzinfo=None)


class SarAdapter(ABC):
    source: str

    @abstractmethod
    def supports(self, root: ET.Element) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse(self, root: ET.Element, candidate: MetadataCandidate) -> ParsedMetadata:
        raise NotImplementedError


class JsonSarAdapter(ABC):
    source: str

    @abstractmethod
    def supports(self, document: dict[str, Any]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse(
        self, document: dict[str, Any], candidate: MetadataCandidate
    ) -> ParsedMetadata:
        raise NotImplementedError
