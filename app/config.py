from functools import lru_cache
import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SAR Manager"
    app_version: str = "0.2.4"
    database_url: str = "postgresql://sar:sar@localhost:5432/sar"
    scan_root: str = "/data"
    upload_root: str = "/upload"
    scan_write_delay_ms: int = 20
    cors_origins: str = "*"
    public_base_url: str = ""
    transfer_destination_root: str = "/upload"
    # JSON object mapping a public server identifier to its read-only mounted
    # directory. Example: {"sar-storage-01":"/transfer-sources/storage-01"}
    transfer_source_roots: str = "{}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def transfer_sources(self) -> dict[str, Path]:
        try:
            raw = json.loads(self.transfer_source_roots)
        except json.JSONDecodeError as exc:
            raise ValueError("TRANSFER_SOURCE_ROOTS must be a JSON object") from exc
        if not isinstance(raw, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in raw.items()):
            raise ValueError("TRANSFER_SOURCE_ROOTS must map server names to directory paths")
        return {key: Path(value).resolve() for key, value in raw.items()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
