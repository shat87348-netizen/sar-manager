from functools import lru_cache

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
