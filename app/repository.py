from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from app.db import get_pool
from app.domain import AssetRecord, IngestRecord, LocatedFile


def _location_identity(location: LocatedFile) -> str:
    return "|".join(
        (
            location.container_type.value,
            location.relative_path or "",
            location.archive_path or "",
            location.member_path or "",
        )
    )


def _stable_asset_id(dataset_id: UUID, asset: AssetRecord) -> UUID:
    return uuid5(
        dataset_id,
        f"primary|{asset.kind.value}|{_location_identity(asset.location)}",
    )


def _stable_file_id(dataset_id: UUID, location: LocatedFile) -> UUID:
    return uuid5(dataset_id, f"file|{_location_identity(location)}")


def save_ingest_record(record: IngestRecord) -> UUID:
    pool = get_pool()
    with pool.connection() as connection, connection.transaction():
        existing = connection.execute(
            "SELECT id, xml_sha256 FROM sar_dataset WHERE external_id = %s FOR UPDATE",
            (record.parsed.external_id,),
        ).fetchone()
        dataset_id = existing["id"] if existing else uuid4()
        status_value = record.status.value
        error_message = record.error_message
        if existing and existing["xml_sha256"] != record.xml_sha256 and status_value == "READY":
            status_value = "DUPLICATE"
            error_message = "Conflicting metadata content for the same external_id"
        footprint_expression = (
            "ST_GeomFromText(%(footprint)s, 4326)" if record.parsed.footprint_wkt else "NULL"
        )
        values = {
            "id": dataset_id,
            "external_id": record.parsed.external_id,
            "source": record.parsed.source,
            "name": record.parsed.name,
            "acquisition_time": record.parsed.acquisition_time,
            "footprint": record.parsed.footprint_wkt,
            "status": status_value,
            "metadata": json.dumps(record.parsed.metadata, ensure_ascii=False),
            "xml_sha256": record.xml_sha256,
            "error_message": error_message,
        }
        if existing:
            connection.execute(
                f"""
                UPDATE sar_dataset
                SET source = %(source)s,
                    name = %(name)s,
                    acquisition_time = %(acquisition_time)s,
                    footprint = {footprint_expression},
                    status = %(status)s,
                    metadata = %(metadata)s::jsonb,
                    xml_sha256 = %(xml_sha256)s,
                    error_message = %(error_message)s,
                    updated_at = NOW()
                WHERE id = %(id)s
                """,
                values,
            )
            connection.execute("DELETE FROM sar_asset WHERE dataset_id = %s", (dataset_id,))
            connection.execute("DELETE FROM sar_file WHERE dataset_id = %s", (dataset_id,))
        else:
            connection.execute(
                f"""
                INSERT INTO sar_dataset (
                    id, external_id, source, name, acquisition_time, footprint,
                    status, metadata, xml_sha256, error_message
                ) VALUES (
                    %(id)s, %(external_id)s, %(source)s, %(name)s,
                    %(acquisition_time)s, {footprint_expression}, %(status)s,
                    %(metadata)s::jsonb, %(xml_sha256)s, %(error_message)s
                )
                """,
                values,
            )

        for asset in record.assets:
            location = asset.location
            connection.execute(
                """
                INSERT INTO sar_asset (
                    id, dataset_id, kind, container_type, storage_root,
                    relative_path, archive_path, member_path, file_name,
                    mime_type, size_bytes
                ) VALUES (
                    %(id)s, %(dataset_id)s, %(kind)s, %(container_type)s,
                    %(storage_root)s, %(relative_path)s, %(archive_path)s,
                    %(member_path)s, %(file_name)s, %(mime_type)s, %(size_bytes)s
                )
                """,
                {
                    "id": _stable_asset_id(dataset_id, asset),
                    "dataset_id": dataset_id,
                    "kind": asset.kind.value,
                    "container_type": location.container_type.value,
                    "storage_root": location.storage_root,
                    "relative_path": location.relative_path,
                    "archive_path": location.archive_path,
                    "member_path": location.member_path,
                    "file_name": location.name,
                    "mime_type": location.mime_type,
                    "size_bytes": location.size_bytes,
                },
            )

        for located_file in record.files:
            connection.execute(
                """
                INSERT INTO sar_file (
                    id, dataset_id, kind, container_type, storage_root,
                    relative_path, archive_path, member_path, file_name,
                    mime_type, size_bytes
                ) VALUES (
                    %(id)s, %(dataset_id)s, %(kind)s, %(container_type)s,
                    %(storage_root)s, %(relative_path)s, %(archive_path)s,
                    %(member_path)s, %(file_name)s, %(mime_type)s, %(size_bytes)s
                )
                """,
                {
                    "id": _stable_file_id(dataset_id, located_file),
                    "dataset_id": dataset_id,
                    "kind": located_file.file_kind,
                    "container_type": located_file.container_type.value,
                    "storage_root": located_file.storage_root,
                    "relative_path": located_file.relative_path,
                    "archive_path": located_file.archive_path,
                    "member_path": located_file.member_path,
                    "file_name": located_file.name,
                    "mime_type": located_file.mime_type,
                    "size_bytes": located_file.size_bytes,
                },
            )
    return dataset_id


def query_datasets(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    source: str | None = None,
    statuses: tuple[str, ...] = ("READY",),
    limit: int = 100,
    offset: int = 0,
    name: str | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if start_time is not None:
        clauses.append("d.acquisition_time >= %s")
        params.append(start_time)
    if end_time is not None:
        clauses.append("d.acquisition_time <= %s")
        params.append(end_time)
    if source:
        clauses.append("UPPER(d.source) = UPPER(%s)")
        params.append(source)
    if name:
        # Search both the display name and provider product identifier.
        clauses.append("(d.name ILIKE %s OR d.external_id ILIKE %s)")
        name_pattern = f"%{name}%"
        params.extend((name_pattern, name_pattern))
    if statuses:
        clauses.append("d.status = ANY(%s)")
        params.append(list(statuses))
    if bbox:
        clauses.append("ST_Intersects(d.footprint, ST_MakeEnvelope(%s, %s, %s, %s, 4326))")
        params.extend(bbox)

    where = " AND ".join(clauses) if clauses else "TRUE"
    query = f"""
        SELECT d.id, d.external_id, d.source, d.name, d.acquisition_time,
               d.status, d.metadata, d.error_message,
               ST_AsGeoJSON(d.footprint)::jsonb AS geometry,
               (
                   ARRAY_AGG(
                       CASE
                           WHEN a.container_type = 'FILE' THEN
                               CASE
                                   WHEN a.relative_path LIKE '%%/%%' THEN
                                       a.storage_root || '/' ||
                                       regexp_replace(a.relative_path, '/[^/]+$', '')
                                   ELSE a.storage_root
                               END
                           ELSE
                               CASE
                                   WHEN a.archive_path LIKE '%%/%%' THEN
                                       a.storage_root || '/' ||
                                       regexp_replace(a.archive_path, '/[^/]+$', '')
                                   ELSE a.storage_root
                               END
                       END
                       ORDER BY CASE a.kind
                           WHEN 'TIFF' THEN 1
                           WHEN 'THUMBNAIL' THEN 2
                           WHEN 'XML' THEN 3
                           WHEN 'JSON' THEN 4
                           ELSE 5
                       END
                   ) FILTER (WHERE a.id IS NOT NULL)
               )[1] AS data_directory,
               COALESCE(
                   jsonb_object_agg(
                       a.kind,
                       jsonb_build_object(
                           'id', a.id,
                           'file_name', a.file_name,
                           'url', '/api/v1/assets/' || a.id::text,
                           'mime_type', a.mime_type,
                           'size_bytes', a.size_bytes
                       )
                   ) FILTER (WHERE a.id IS NOT NULL),
                   '{{}}'::jsonb
               ) AS assets
        FROM sar_dataset d
        LEFT JOIN sar_asset a ON a.dataset_id = d.id
        WHERE {where}
        GROUP BY d.id
        ORDER BY d.acquisition_time NULLS LAST, d.id
        LIMIT %s OFFSET %s
    """
    params.extend((limit, offset))
    with get_pool().connection() as connection:
        return list(connection.execute(query, params).fetchall())


def get_dataset(dataset_id: UUID) -> dict[str, Any] | None:
    rows = query_dataset_by_id(dataset_id)
    return rows[0] if rows else None


def query_dataset_by_id(dataset_id: UUID) -> list[dict[str, Any]]:
    query = """
        SELECT d.id, d.external_id, d.source, d.name, d.acquisition_time,
               d.status, d.metadata, d.error_message,
               ST_AsGeoJSON(d.footprint)::jsonb AS geometry,
               (
                   ARRAY_AGG(
                       CASE
                           WHEN a.container_type = 'FILE' THEN
                               CASE
                                   WHEN a.relative_path LIKE '%%/%%' THEN
                                       a.storage_root || '/' ||
                                       regexp_replace(a.relative_path, '/[^/]+$', '')
                                   ELSE a.storage_root
                               END
                           ELSE
                               CASE
                                   WHEN a.archive_path LIKE '%%/%%' THEN
                                       a.storage_root || '/' ||
                                       regexp_replace(a.archive_path, '/[^/]+$', '')
                                   ELSE a.storage_root
                               END
                       END
                       ORDER BY CASE a.kind
                           WHEN 'TIFF' THEN 1
                           WHEN 'THUMBNAIL' THEN 2
                           WHEN 'XML' THEN 3
                           WHEN 'JSON' THEN 4
                           ELSE 5
                       END
                   ) FILTER (WHERE a.id IS NOT NULL)
               )[1] AS data_directory,
               COALESCE(
                   jsonb_object_agg(
                       a.kind,
                       jsonb_build_object(
                           'id', a.id,
                           'file_name', a.file_name,
                           'url', '/api/v1/assets/' || a.id::text,
                           'mime_type', a.mime_type,
                           'size_bytes', a.size_bytes
                       )
                   ) FILTER (WHERE a.id IS NOT NULL),
                   '{}'::jsonb
               ) AS assets
        FROM sar_dataset d
        LEFT JOIN sar_asset a ON a.dataset_id = d.id
        WHERE d.id = %s
        GROUP BY d.id
    """
    with get_pool().connection() as connection:
        return list(connection.execute(query, (dataset_id,)).fetchall())


def get_asset(asset_id: UUID) -> dict[str, Any] | None:
    with get_pool().connection() as connection:
        return connection.execute(
            """
            SELECT id, dataset_id, kind, container_type, storage_root,
                   relative_path, archive_path, member_path, file_name,
                   mime_type, size_bytes
            FROM sar_asset WHERE id = %s
            UNION ALL
            SELECT id, dataset_id, kind, container_type, storage_root,
                   relative_path, archive_path, member_path, file_name,
                   mime_type, size_bytes
            FROM sar_file WHERE id = %s
            LIMIT 1
            """,
            (asset_id, asset_id),
        ).fetchone()


def get_dataset_files(dataset_id: UUID) -> list[dict[str, Any]]:
    with get_pool().connection() as connection:
        return list(
            connection.execute(
                """
                SELECT id, dataset_id, kind, container_type, relative_path,
                       archive_path, member_path, file_name, mime_type, size_bytes
                FROM sar_file
                WHERE dataset_id = %s
                ORDER BY kind, file_name, id
                """,
                (dataset_id,),
            ).fetchall()
        )


def get_stats() -> dict[str, Any]:
    with get_pool().connection() as connection:
        total = connection.execute("SELECT COUNT(*) AS count FROM sar_dataset").fetchone()["count"]
        by_source = connection.execute(
            "SELECT source, COUNT(*) AS count FROM sar_dataset GROUP BY source ORDER BY source"
        ).fetchall()
        by_status = connection.execute(
            "SELECT status, COUNT(*) AS count FROM sar_dataset GROUP BY status ORDER BY status"
        ).fetchall()
    return {
        "total": total,
        "by_source": {row["source"]: row["count"] for row in by_source},
        "by_status": {row["status"]: row["count"] for row in by_status},
    }


def get_source_counts() -> dict[str, int]:
    """Return dataset counts grouped by source code.

    UNKNOWN is an ingest failure status rather than a selectable data source,
    so it is deliberately excluded from the source-filter endpoint.
    """
    with get_pool().connection() as connection:
        rows = connection.execute(
            """
            SELECT source, COUNT(*) AS count
            FROM sar_dataset
            WHERE source <> 'UNKNOWN'
            GROUP BY source
            """
        ).fetchall()
    return {row["source"]: row["count"] for row in rows}


def get_existing_metadata_hashes() -> dict[str, str]:
    """Return the metadata hash already stored for every known dataset.

    A scan uses this once at startup to avoid rewriting records whose metadata
    has not changed. This keeps repeat scans from competing with API reads for
    database write capacity.
    """
    with get_pool().connection() as connection:
        rows = connection.execute(
            "SELECT external_id, xml_sha256 FROM sar_dataset"
        ).fetchall()
    return {row["external_id"]: row["xml_sha256"] for row in rows}
