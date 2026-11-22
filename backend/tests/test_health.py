import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from smartdoc.api.health import Readiness
from smartdoc.persistence.database import database_url

LIVE = "/api/v1/health/live"
READY = "/api/v1/health/ready"


def test_liveness_is_independent_of_storage(client: TestClient, database: Path):
    response = client.get(LIVE)
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert response.headers["Cache-Control"] == "no-store"
    assert UUID(response.headers["X-Request-ID"]).version == 4
    assert not database.exists()


def test_readiness_reports_missing_store_without_creating_it(client: TestClient, database: Path):
    response = client.get(READY)
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    status = Readiness.model_validate(response.json())
    assert status.status == "unavailable"
    assert status.database == "missing"
    assert status.checked_at.tzinfo is not None
    assert not database.exists()


def test_readiness_follows_migration_and_detects_missing_tables(
    client: TestClient, database: Path, migration: Config
):
    command.upgrade(migration, "head")
    response = client.get(READY)
    assert response.status_code == 200
    assert response.json()["database"] == "ready"
    assert datetime.fromisoformat(response.json()["checked_at"]).tzinfo is not None

    engine = create_engine(database_url(database))
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE users")
    engine.dispose()

    response = client.get(READY)
    assert response.status_code == 503
    assert response.json()["database"] == "migration_required"


def test_readiness_handles_unmigrated_and_corrupt_files(client: TestClient, database: Path):
    database.parent.mkdir()
    database.touch()
    response = client.get(READY)
    assert response.status_code == 503
    assert response.json()["database"] == "migration_required"

    database.write_bytes(b"this is not a SQLite file")
    response = client.get(READY)
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
    assert "sqlite3" not in response.text


def test_health_contract_is_published(client: TestClient):
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert "503" in response.json()["paths"][READY]["get"]["responses"]


def test_errors_and_access_logs_preserve_correlation(client: TestClient, caplog):
    caplog.set_level(logging.INFO, logger="smartdoc.app")
    response = client.get("/api/v1/unknown", params={"q": "sensitive-query"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    event = next(record for record in caplog.records if record.message == "request_completed")
    assert event.request_id == response.json()["request_id"]
    assert event.status == 404
    assert event.route is None
    assert "sensitive-query" not in response.text + caplog.text


def test_validation_and_internal_errors_are_sanitized(client: TestClient, caplog):
    app: FastAPI = client.app

    @app.get("/test-input")
    def input_check(quantity: int):
        return quantity

    @app.get("/test-failure")
    def failure():
        raise ValueError("private diagnostic data")

    response = client.get("/test-input?quantity=sensitive-query")
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert "sensitive-query" not in response.text

    response = client.get("/test-failure")
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
    assert "private diagnostic data" not in response.text + caplog.text
    record = next(record for record in caplog.records if record.message == "request_completed")
    assert record.error_type == "ValueError"
    assert record.route == "/test-failure"
