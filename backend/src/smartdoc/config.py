from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[2]
MIGRATIONS_DIR = PACKAGE_DIR / "migrations"
if not MIGRATIONS_DIR.is_dir():
    MIGRATIONS_DIR = PROJECT_ROOT / "backend" / "migrations"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMARTDOC_", extra="ignore")

    database_path: Path = Field(default_factory=lambda: Path(".local") / "smartdoc.sqlite3")
    storage_path: Path | None = None
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1, le=64 * 1024 * 1024)
    processing_timeout: int = Field(default=90, ge=5, le=180)
    ingestion_worker: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
