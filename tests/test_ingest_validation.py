from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.adapters import AdapterRegistry
from app.ingest import IngestError, _validate_source


WANG_PRODUCT_XML = """<?xml version=\"1.0\"?>
<SARProductMetadata xmlns=\"pj3-ips-sar:product-metadata\">
  <ProductName>RSS1B_TEST_PRODUCT</ProductName>
  <CenterTimeUTC>2026-08-21T12:00:00Z</CenterTimeUTC>
  <GeographicFootprint>
    <UpperLeft longitudeDegrees=\"120\" latitudeDegrees=\"31\" />
    <UpperRight longitudeDegrees=\"121\" latitudeDegrees=\"31\" />
    <LowerRight longitudeDegrees=\"121\" latitudeDegrees=\"30\" />
    <LowerLeft longitudeDegrees=\"120\" latitudeDegrees=\"30\" />
  </GeographicFootprint>
</SARProductMetadata>
"""


class IngestValidationTests(unittest.TestCase):
    def test_wang_quality_xml_does_not_reject_product_with_primary_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            product = Path(directory)
            (product / "RSS1B_TEST.xml").write_text(WANG_PRODUCT_XML, encoding="utf-8")
            (product / "RSS1B_TEST_QUALITY.XML").write_text(
                "<QualityReport />", encoding="utf-8"
            )

            self.assertEqual(_validate_source(product, "WANG", AdapterRegistry()), 1)

    def test_auxiliary_xml_without_primary_metadata_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            product = Path(directory)
            (product / "RSS1B_TEST_QUALITY.XML").write_text(
                "<QualityReport />", encoding="utf-8"
            )

            with self.assertRaisesRegex(IngestError, "No primary SAR"):
                _validate_source(product, "WANG", AdapterRegistry())
