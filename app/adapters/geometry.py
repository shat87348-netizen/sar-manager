from __future__ import annotations

import math
import re
from typing import Any

from app.adapters.base import MetadataError


def polygon_coordinates(geometry: Any) -> tuple[tuple[float, float], ...]:
    """Return the exterior ring of a GeoJSON Polygon, dropping optional altitude."""

    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise MetadataError("Metadata geometry must be a GeoJSON Polygon")
    rings = geometry.get("coordinates")
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list):
        raise MetadataError("Metadata Polygon has no exterior ring")

    coordinates: list[tuple[float, float]] = []
    for point in rings[0]:
        if not isinstance(point, list) or len(point) < 2:
            raise MetadataError("Metadata Polygon contains an invalid coordinate")
        coordinates.append((float(point[0]), float(point[1])))
    return tuple(coordinates)


def utm_zone_from_wkt(wkt: str) -> tuple[int, bool]:
    match = re.search(r"UTM zone\s+(\d{1,2})([NS])", wkt, re.IGNORECASE)
    if match:
        return int(match.group(1)), match.group(2).upper() == "N"

    epsg = re.search(r'AUTHORITY\["EPSG","(326|327)(\d{2})"\]', wkt)
    if epsg:
        return int(epsg.group(2)), epsg.group(1) == "326"
    raise MetadataError("Capella coordinate system is not a supported WGS84 UTM zone")


def utm_to_lon_lat(
    easting: float, northing: float, zone: int, northern_hemisphere: bool
) -> tuple[float, float]:
    """Convert WGS84 UTM coordinates to longitude/latitude without external GIS packages."""

    if not 1 <= zone <= 60:
        raise MetadataError(f"Invalid UTM zone: {zone}")

    semi_major = 6378137.0
    eccentricity_squared = 0.0066943799901413165
    scale = 0.9996

    x = easting - 500000.0
    y = northing if northern_hemisphere else northing - 10000000.0
    meridional_arc = y / scale

    e1 = (1.0 - math.sqrt(1.0 - eccentricity_squared)) / (
        1.0 + math.sqrt(1.0 - eccentricity_squared)
    )
    mu = meridional_arc / (
        semi_major
        * (
            1.0
            - eccentricity_squared / 4.0
            - 3.0 * eccentricity_squared**2 / 64.0
            - 5.0 * eccentricity_squared**3 / 256.0
        )
    )

    phi1 = (
        mu
        + (3.0 * e1 / 2.0 - 27.0 * e1**3 / 32.0) * math.sin(2.0 * mu)
        + (21.0 * e1**2 / 16.0 - 55.0 * e1**4 / 32.0) * math.sin(4.0 * mu)
        + (151.0 * e1**3 / 96.0) * math.sin(6.0 * mu)
        + (1097.0 * e1**4 / 512.0) * math.sin(8.0 * mu)
    )

    second_eccentricity = eccentricity_squared / (1.0 - eccentricity_squared)
    n1 = semi_major / math.sqrt(
        1.0 - eccentricity_squared * math.sin(phi1) ** 2
    )
    t1 = math.tan(phi1) ** 2
    c1 = second_eccentricity * math.cos(phi1) ** 2
    r1 = (
        semi_major
        * (1.0 - eccentricity_squared)
        / (1.0 - eccentricity_squared * math.sin(phi1) ** 2) ** 1.5
    )
    d = x / (n1 * scale)

    latitude = phi1 - (n1 * math.tan(phi1) / r1) * (
        d**2 / 2.0
        - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1**2 - 9.0 * second_eccentricity)
        * d**4
        / 24.0
        + (
            61.0
            + 90.0 * t1
            + 298.0 * c1
            + 45.0 * t1**2
            - 252.0 * second_eccentricity
            - 3.0 * c1**2
        )
        * d**6
        / 720.0
    )
    longitude = (
        d
        - (1.0 + 2.0 * t1 + c1) * d**3 / 6.0
        + (
            5.0
            - 2.0 * c1
            + 28.0 * t1
            - 3.0 * c1**2
            + 8.0 * second_eccentricity
            + 24.0 * t1**2
        )
        * d**5
        / 120.0
    ) / math.cos(phi1)

    central_meridian = math.radians((zone - 1) * 6 - 180 + 3)
    return math.degrees(central_meridian + longitude), math.degrees(latitude)


def raster_utm_corners(
    geotransform: Any,
    rows: Any,
    columns: Any,
    coordinate_system_wkt: str,
) -> tuple[tuple[float, float], ...]:
    if (
        not isinstance(geotransform, list)
        or len(geotransform) != 6
        or not isinstance(rows, (int, float))
        or not isinstance(columns, (int, float))
    ):
        raise MetadataError("Capella image geometry is incomplete")

    gt = [float(value) for value in geotransform]
    zone, northern = utm_zone_from_wkt(coordinate_system_wkt)
    pixel_corners = (
        (0.0, 0.0),
        (float(columns), 0.0),
        (float(columns), float(rows)),
        (0.0, float(rows)),
    )
    result: list[tuple[float, float]] = []
    for column, row in pixel_corners:
        easting = gt[0] + column * gt[1] + row * gt[2]
        northing = gt[3] + column * gt[4] + row * gt[5]
        result.append(utm_to_lon_lat(easting, northing, zone, northern))
    return tuple(result)
