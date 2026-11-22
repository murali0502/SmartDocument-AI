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
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
