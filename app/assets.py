from __future__ import annotations

from app.domain import AssetKind, AssetRecord, LocatedFile, MetadataCandidate

_PREVIEW_MARKERS = ("thumb", "thumbnail", "quicklook", "preview", "qlk", "thm")
_LISTABLE_SUFFIXES = {
    ".xml",
    ".json",
    ".kml",
    ".tif",
    ".tiff",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}


def _is_preview(item: LocatedFile) -> bool:
    return any(marker in item.name.lower() for marker in _PREVIEW_MARKERS)


def _select_tiff(files: list[LocatedFile]) -> LocatedFile | None:
    candidates = [item for item in files if item.suffix in {".tif", ".tiff"}]
    return (
        sorted(
            candidates,
            key=lambda item: (
                _is_preview(item),
                "cog" in item.name.lower(),
                item.suffix != ".tiff",
                item.name.lower(),
            ),
        )[0]
        if candidates
        else None
    )


def _select_thumbnail(
    files: list[LocatedFile], original_tiff: LocatedFile | None
) -> LocatedFile | None:
    candidates = [item for item in files if item.suffix in {".jpg", ".jpeg", ".png", ".webp"}]
    if candidates:
        return sorted(
            candidates,
            key=lambda item: (
                not _is_preview(item),
                item.suffix not in {".jpg", ".jpeg"},
                item.name.lower(),
            ),
        )[0]

    tiff_previews = [
        item
        for item in files
        if item.suffix in {".tif", ".tiff"} and _is_preview(item)
    ]
    if tiff_previews:
        return sorted(tiff_previews, key=lambda item: item.name.lower())[0]

    # Some vendors do not provide a separate preview. In that case the API
    # intentionally exposes the original TIFF as both TIFF and THUMBNAIL.
    return original_tiff


def select_assets(candidate: MetadataCandidate) -> tuple[AssetRecord, ...]:
    files = list(candidate.related_files)
    assets: list[AssetRecord] = []
    if candidate.format == "XML":
        assets.append(AssetRecord(AssetKind.XML, candidate.metadata_file))
    elif candidate.format == "JSON":
        assets.append(AssetRecord(AssetKind.JSON, candidate.metadata_file))
    tiff = _select_tiff(files)
    thumbnail = _select_thumbnail(files, tiff)
    if tiff:
        assets.append(AssetRecord(AssetKind.TIFF, tiff))
    if thumbnail:
        assets.append(AssetRecord(AssetKind.THUMBNAIL, thumbnail))
    return tuple(assets)


def select_files(candidate: MetadataCandidate) -> tuple[LocatedFile, ...]:
    """Return every shareable metadata or image file belonging to a product."""

    return tuple(
        sorted(
            (item for item in candidate.related_files if item.suffix in _LISTABLE_SUFFIXES),
            key=lambda item: (
                item.archive_path or "",
                item.relative_path or "",
                item.member_path or "",
                item.name.lower(),
            ),
        )
    )
