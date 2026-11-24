from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
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
    vision_url: str | None = None
    vision_model: str | None = None
    vision_max_pages: int = Field(default=8, ge=1, le=16)
    vision_timeout: int = Field(default=90, ge=5, le=180)

    @model_validator(mode="after")
    def validate_vision_endpoint(self) -> "Settings":
        if bool(self.vision_url) != bool(self.vision_model):
            raise ValueError("Configure both SMARTDOC_VISION_URL and SMARTDOC_VISION_MODEL.")
        if self.vision_url:
            url = urlsplit(self.vision_url)
            host = url.hostname or ""
            private = host == "localhost" or host.endswith(".railway.internal")
            try:
                address = ip_address(host)
                private = address.is_loopback or (
                    address.is_private
                    and not address.is_unspecified
                    and not address.is_link_local
                    and not address.is_multicast
                )
            except ValueError:
                pass
            if (
                not private
                or url.scheme not in {"http", "https"}
                or url.username is not None
                or url.query
                or url.fragment
            ):
                raise ValueError("The vision endpoint must be on the private network.")
        return self

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
