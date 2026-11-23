from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from smartdoc.ncm.contracts import Weights
from smartdoc.nlp.assets import DEFAULT_MODELS
from smartdoc.nlp.pipeline import Profile

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
    nlp_profile: Profile = "rules"
    nlp_model_dir: Path = DEFAULT_MODELS
    nlp_terms: dict[str, list[str]] = Field(default_factory=dict)
    ncm_weights: Weights = Field(default_factory=Weights)
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("nlp_terms")
    @classmethod
    def validate_terms(cls, glossary: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(glossary) > 32 or sum(map(len, glossary.values())) > 500:
            raise ValueError("The NLP glossary supports up to 32 labels and 500 terms.")
        if any(not label.strip() or len(label) > 48 for label in glossary):
            raise ValueError("NLP glossary labels must contain 1–48 characters.")
        if any(
            not term.strip() or len(term) > 100 for terms in glossary.values() for term in terms
        ):
            raise ValueError("NLP glossary terms must contain 1–100 characters.")
        return glossary
