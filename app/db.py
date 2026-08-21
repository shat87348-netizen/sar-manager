from __future__ import annotations

import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row},
        )
    return _pool


def open_pool() -> None:
    pool = get_pool()
    pool.open(wait=True)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def init_database(wait_seconds: int = 0) -> None:
    settings = get_settings()
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            with psycopg.connect(settings.database_url, autocommit=True) as connection:
                schema = Path(__file__).with_name("sql").joinpath("schema.sql").read_text("utf-8")
                connection.execute(schema)
            return
        except psycopg.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)
