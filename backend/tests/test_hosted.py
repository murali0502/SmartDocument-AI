from alembic import command
from fastapi.testclient import TestClient

from smartdoc.config import Settings
from smartdoc.hosted import create_hosted_app


def test_hosted_access_and_upload(migration, database, tmp_path):
    command.upgrade(migration, "head")
    (tmp_path / "index.html").write_text("SmartDoc AI", encoding="utf-8")
    password = "dev-fixture-only-password"
    settings = Settings(database_path=database, ingestion_worker=False)
    app = create_hosted_app(settings, tmp_path, password, "smartdoc.example")
    auth = ("smartdoc", password)
    workspace = "/api/v1/workspaces/local"

    with TestClient(app, base_url="https://smartdoc.example") as client:
        for path in ("/", "/api/v1/docs", "/api/v1/openapi.json", f"{workspace}/documents"):
            response = client.get(path)
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"].startswith("Basic ")

        assert client.get("/api/v1/health/ready").status_code == 200
        assert client.get("/", auth=("smartdoc", "wrong")).status_code == 401
        home = client.get("/", auth=auth)
        assert home.text == "SmartDoc AI"
        assert home.headers["X-Content-Type-Options"] == "nosniff"
        assert home.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in home.headers["Content-Security-Policy"]
        assert home.headers["Referrer-Policy"] == "no-referrer"
        assert "/swagger/swagger-ui-bundle.js" in client.get("/api/v1/docs", auth=auth).text

        headers = {"Content-Type": "application/octet-stream", "X-SmartDoc-Upload": "1"}
        upload = f"{workspace}/uploads?filename=manual.txt"
        assert (
            client.post(upload, auth=auth, headers={**headers, "Origin": "null"}).status_code == 403
        )
        assert (
            client.post(
                upload, auth=auth, headers={**headers, "Sec-Fetch-Site": "cross-site"}
            ).status_code
            == 403
        )
        accepted = client.post(
            upload,
            auth=auth,
            headers={
                **headers,
                "Origin": "https://smartdoc.example",
                "Sec-Fetch-Site": "same-origin",
            },
            content=b"The filter removes particles.",
        )
        assert accepted.status_code == 202
        documents = client.get(f"{workspace}/documents", auth=auth)
        assert documents.headers["Cache-Control"] == "private, no-store"
        assert documents.json()["items"][0]["document"]["filename"] == "manual.txt"
