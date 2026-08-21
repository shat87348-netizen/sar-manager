CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS sar_dataset (
    id UUID PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    acquisition_time TIMESTAMP WITHOUT TIME ZONE,
    footprint geometry(Polygon, 4326),
    status TEXT NOT NULL CHECK (
        status IN ('READY', 'PARTIAL', 'INVALID_METADATA', 'UNKNOWN_SOURCE', 'DUPLICATE')
    ),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    xml_sha256 CHAR(64) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sar_dataset_time ON sar_dataset (acquisition_time);
CREATE INDEX IF NOT EXISTS idx_sar_dataset_source ON sar_dataset (source);
CREATE INDEX IF NOT EXISTS idx_sar_dataset_status ON sar_dataset (status);
CREATE INDEX IF NOT EXISTS idx_sar_dataset_footprint ON sar_dataset USING GIST (footprint);

CREATE TABLE IF NOT EXISTS sar_asset (
    id UUID PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES sar_dataset(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('XML', 'JSON', 'TIFF', 'THUMBNAIL')),
    container_type TEXT NOT NULL CHECK (container_type IN ('FILE', 'ZIP', 'TAR')),
    storage_root TEXT NOT NULL,
    relative_path TEXT,
    archive_path TEXT,
    member_path TEXT,
    file_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE (dataset_id, kind),
    CHECK (
        (container_type = 'FILE' AND relative_path IS NOT NULL
            AND archive_path IS NULL AND member_path IS NULL)
        OR
        (container_type IN ('ZIP', 'TAR') AND relative_path IS NULL
            AND archive_path IS NOT NULL AND member_path IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_sar_asset_dataset ON sar_asset (dataset_id);

CREATE TABLE IF NOT EXISTS sar_file (
    id UUID PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES sar_dataset(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (
        kind IN ('XML', 'JSON', 'KML', 'TIFF', 'PNG', 'JPEG', 'WEBP')
    ),
    container_type TEXT NOT NULL CHECK (container_type IN ('FILE', 'ZIP', 'TAR')),
    storage_root TEXT NOT NULL,
    relative_path TEXT,
    archive_path TEXT,
    member_path TEXT,
    file_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CHECK (
        (container_type = 'FILE' AND relative_path IS NOT NULL
            AND archive_path IS NULL AND member_path IS NULL)
        OR
        (container_type IN ('ZIP', 'TAR') AND relative_path IS NULL
            AND archive_path IS NOT NULL AND member_path IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_sar_file_dataset ON sar_file (dataset_id);

-- Version 0.2 adds JSON description files. Existing installations execute this
-- schema on every API start, so update the original 0.1 constraint in place.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'sar_asset'::regclass
          AND conname = 'sar_asset_kind_check'
          AND pg_get_constraintdef(oid) NOT LIKE '%JSON%'
    ) THEN
        ALTER TABLE sar_asset DROP CONSTRAINT sar_asset_kind_check;
        ALTER TABLE sar_asset
            ADD CONSTRAINT sar_asset_kind_check
            CHECK (kind IN ('XML', 'JSON', 'TIFF', 'THUMBNAIL'));
    END IF;
END
$$;
