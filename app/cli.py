from __future__ import annotations

import argparse
import json

from app.config import get_settings
from app.db import close_pool, init_database, open_pool
from app.ingest import IngestError, ingest_upload
from app.scanner import scan_storage


def main() -> None:
    parser = argparse.ArgumentParser(description="SAR Manager administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Create PostGIS tables")
    init_parser.add_argument("--wait", type=int, default=0, help="Seconds to wait for PostgreSQL")

    scan_parser = subparsers.add_parser("scan", help="Scan SAR data")
    scan_parser.add_argument("root", nargs="?", default=None, help="Storage root; defaults to SCAN_ROOT")
    scan_parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess unchanged metadata and rebuild related asset records",
    )

    ingest_parser = subparsers.add_parser(
        "ingest", help="Move one staged upload into /data and scan only that product"
    )
    ingest_parser.add_argument(
        "path", help="Path below UPLOAD_ROOT, for example gf3/batch-001/product.zip"
    )
    ingest_parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess unchanged metadata after promotion",
    )

    args = parser.parse_args()
    if args.command == "init-db":
        init_database(args.wait)
        print("Database initialized")
        return
    if args.command == "scan":
        open_pool()
        try:
            settings = get_settings()
            report = scan_storage(
                args.root or settings.scan_root,
                force=args.force,
                write_delay_ms=settings.scan_write_delay_ms,
            )
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        finally:
            close_pool()

    if args.command == "ingest":
        open_pool()
        try:
            settings = get_settings()
            result = ingest_upload(
                settings.upload_root,
                settings.scan_root,
                args.path,
                force=args.force,
                write_delay_ms=settings.scan_write_delay_ms,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        except IngestError as exc:
            parser.error(str(exc))
        finally:
            close_pool()


if __name__ == "__main__":
    main()
