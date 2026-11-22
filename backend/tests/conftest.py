from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient

from smartdoc.app import create_app
from smartdoc.config import MIGRATIONS_DIR, Settings


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "data with spaces" / "test.sqlite3"
    monkeypatch.setenv("SMARTDOC_DATABASE_PATH", str(path))
    return path


@pytest.fixture
def migration(database: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


@pytest.fixture
def client(database: Path):
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    with TestClient(app) as test_client:
        yield test_client
