from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from app.adapters import AdapterRegistry
from app.adapters.base import MetadataIgnored
from app.assets import select_assets, select_files
from app.containers import iter_candidates
from app.domain import AssetKind, ContainerType, DiscoveryError, MetadataCandidate

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = PROJECT_ROOT / "tiff"


def candidates() -> list[MetadataCandidate]:
    return [
        item
        for item in iter_candidates(SAMPLE_ROOT)
        if not isinstance(item, DiscoveryError)
    ]


def candidate_named(name: str) -> MetadataCandidate:
    return next(item for item in candidates() if item.metadata_file.name == name)


class ParserTests(unittest.TestCase):
    def test_registered_source_codes(self) -> None:
        self.assertEqual(
            AdapterRegistry().source_codes,
            ("CAPELLA", "GF3", "ICEYE", "STRIX", "UMBRA", "WANG"),
        )

    def test_wang_sample_without_classified_assets(self) -> None:
        candidate = candidate_named(
            "RSS1B_SAR_SP2_01-01_E35.0_N32.9_20260728_L2_2026072823352003.xml"
        )
        parsed = AdapterRegistry().parse(candidate)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.source, "WANG")
        self.assertEqual(parsed.name, "testSar")
        self.assertEqual(
            parsed.external_id,
            "WANG:RSS1B_SAR_SP2_01-01_E35.0_N32.9_20260728_L2_2026072823352003",
        )
        self.assertEqual(parsed.acquisition_time.isoformat(), "2026-07-28T23:35:20")
        self.assertEqual(len(parsed.coordinates), 4)
        self.assertAlmostEqual(parsed.coordinates[0][0], 34.910188815151528)
        self.assertAlmostEqual(parsed.coordinates[0][1], 32.982593418104322)

        assets = {asset.kind: asset for asset in select_assets(candidate)}
        self.assertIn(AssetKind.XML, assets)
        self.assertNotIn(AssetKind.TIFF, assets)
        self.assertNotIn(AssetKind.THUMBNAIL, assets)
        self.assertEqual(
            [item.name for item in select_files(candidate)],
            [candidate.metadata_file.name],
        )

    def test_wang_discovers_same_directory_tiff_and_thumbnail(self) -> None:
        source_xml = SAMPLE_ROOT.joinpath(
            "wang",
            "testSar",
            "RSS1B_SAR_SP2_01-01_E35.0_N32.9_20260728_L2_2026072823352003.xml",
        )
        stem = source_xml.stem
        with tempfile.TemporaryDirectory() as directory:
            product = Path(directory) / "testSar"
            product.mkdir()
            shutil.copy2(source_xml, product / source_xml.name)
            (product / f"{stem}.tiff").write_bytes(b"test tiff")
            (product / f"{stem}.png").write_bytes(b"test thumbnail")

            candidate = next(
                item
                for item in iter_candidates(product)
                if not isinstance(item, DiscoveryError)
            )
            parsed = AdapterRegistry().parse(candidate)
            self.assertIsNotNone(parsed)
            assets = {asset.kind: asset for asset in select_assets(candidate)}
            self.assertEqual(assets[AssetKind.TIFF].location.name, f"{stem}.tiff")
            self.assertEqual(assets[AssetKind.THUMBNAIL].location.name, f"{stem}.png")
            listed_files = {item.name: item.file_kind for item in select_files(candidate)}
            self.assertEqual(
                listed_files,
                {
                    source_xml.name: "XML",
                    f"{stem}.tiff": "TIFF",
                    f"{stem}.png": "PNG",
                },
            )

    def test_gf3_sample(self) -> None:
        candidate = candidate_named(
            "GF3_KRN_SL_029134_W157.9_N21.3_20220221_L2_HH_L20007211856.meta.xml"
        )
        parsed = AdapterRegistry().parse(candidate)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.source, "GF3")
        self.assertEqual(
            parsed.acquisition_time.isoformat(), "2022-02-21T04:40:13.411804"
        )
        self.assertEqual(len(parsed.coordinates), 4)
        self.assertAlmostEqual(parsed.coordinates[0][0], -157.992731)
        self.assertAlmostEqual(parsed.coordinates[0][1], 21.367691)

        assets = {asset.kind: asset for asset in select_assets(candidate)}
        self.assertNotIn(AssetKind.TIFF, assets)
        self.assertTrue(assets[AssetKind.THUMBNAIL].location.name.endswith(".thumb.jpg"))

    def test_strix_archive_and_gml_axis_order(self) -> None:
        candidate = candidate_named("PAR-VV-STRIX4-20250920T165227Z-SR-SLGRD.xml")
        parsed = AdapterRegistry().parse(candidate)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.source, "STRIX")
        self.assertEqual(parsed.acquisition_time.isoformat(), "2025-09-20T16:52:27")
        self.assertAlmostEqual(parsed.coordinates[0][0], -74.21223536781925)
        self.assertAlmostEqual(parsed.coordinates[0][1], 4.769782166226894)

        assets = {asset.kind: asset for asset in select_assets(candidate)}
        self.assertEqual(candidate.metadata_file.container_type, ContainerType.ZIP)
        self.assertNotIn("cog", assets[AssetKind.TIFF].location.name.lower())
        self.assertTrue(assets[AssetKind.THUMBNAIL].location.name.endswith(".jpeg"))

    def test_umbra_json_and_tiff_thumbnail_fallback(self) -> None:
        candidate = candidate_named("2023-10-24-04-02-21_UMBRA-05_METADATA.json")
        parsed = AdapterRegistry().parse(candidate)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.source, "UMBRA")
        self.assertEqual(parsed.acquisition_time.isoformat(), "2023-10-24T04:02:23")
        self.assertGreater(len(parsed.coordinates), 4)

        assets = {asset.kind: asset for asset in select_assets(candidate)}
        self.assertIn(AssetKind.JSON, assets)
        self.assertEqual(
            assets[AssetKind.TIFF].location,
            assets[AssetKind.THUMBNAIL].location,
        )

    def test_capella_json_utm_footprint(self) -> None:
        candidate = next(
            item
            for item in candidates()
            if item.metadata_file.name.endswith("_extended.json")
        )
        parsed = AdapterRegistry().parse(candidate)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.source, "CAPELLA")
        self.assertEqual(
            parsed.acquisition_time.isoformat(), "2024-05-04T09:39:40.285000"
        )
        self.assertEqual(len(parsed.coordinates), 4)
        self.assertAlmostEqual(parsed.coordinates[0][0], 136.787334, places=5)
        self.assertAlmostEqual(parsed.coordinates[0][1], -30.390053, places=5)

    def test_iceye_grd_is_primary_and_qlk_is_thumbnail(self) -> None:
        registry = AdapterRegistry()
        grd = next(
            item
            for item in candidates()
            if item.metadata_file.name.endswith("_GRD.json")
        )
        parsed = registry.parse(grd)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.source, "ICEYE")
        self.assertEqual(parsed.acquisition_time.isoformat(), "2025-11-08T01:21:24.063000")

        assets = {asset.kind: asset for asset in select_assets(grd)}
        self.assertIn(AssetKind.JSON, assets)
        self.assertTrue(assets[AssetKind.TIFF].location.name.endswith("_GRD.tif"))
        self.assertTrue(assets[AssetKind.THUMBNAIL].location.name.endswith("_QLK.tif"))
        listed_files = select_files(grd)
        self.assertTrue(any(item.file_kind == "KML" for item in listed_files))
        self.assertGreaterEqual(
            sum(item.file_kind == "JSON" for item in listed_files),
            5,
        )

        auxiliary = next(
            item
            for item in candidates()
            if item.metadata_file.name.endswith("_QLK.json")
        )
        with self.assertRaises(MetadataIgnored):
            registry.parse(auxiliary)

    def test_deep_directory_and_json_archive_discovery(self) -> None:
        metadata = {
            "type": "Feature",
            "id": "ICEYE_TEST_GRD",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]],
            },
            "properties": {
                "constellation": "ICEYE",
                "platform": "ICEYE-X1",
                "datetime": "2025-01-01T00:00:00Z",
                "sar:product_type": "GRD",
            },
        }
        payload = json.dumps(metadata).encode()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deep = root / "source" / "year" / "month" / "dataset"
            image_dir = deep / "images"
            image_dir.mkdir(parents=True)
            (deep / "meta.json").write_bytes(payload)
            (image_dir / "image.tif").write_bytes(b"tiff")

            zip_path = root / "archive.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("deep/product/meta.json", payload)
                archive.writestr("deep/product/images/image.tif", b"tiff")

            tar_path = root / "archive.tar.gz"
            with tarfile.open(tar_path, "w:gz") as archive:
                info = tarfile.TarInfo("deep/product/meta.json")
                info.size = len(payload)
                archive.addfile(info, BytesIO(payload))

            found = [
                item
                for item in iter_candidates(root)
                if not isinstance(item, DiscoveryError)
            ]
            self.assertEqual(len(found), 3)
            regular = next(
                item
                for item in found
                if item.metadata_file.container_type == ContainerType.FILE
            )
            self.assertTrue(
                any(file.name == "image.tif" for file in regular.related_files)
            )
            archived = next(
                item
                for item in found
                if item.metadata_file.container_type == ContainerType.ZIP
            )
            self.assertTrue(
                any(file.name == "image.tif" for file in archived.related_files)
            )


if __name__ == "__main__":
    unittest.main()
