from uuid import uuid4

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_graph import model

from smartdoc.app import create_app
from smartdoc.config import Settings
from smartdoc.persistence.structure_models import DocumentChunk

BASE = "/api/v1/workspaces/local"


def test_search_methods_filters_and_source_round_trip(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    pump = model(app, database, "pump.md", "The pump requires a ceramic filter.")
    motor = model(app, database, "motor.md", "The motor requires a regulator.")
    assert app.state.graph_store.build_next()
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        response = client.post(f"{BASE}/search", json={"query": "What does the pump require?"})
        assert response.status_code == 200, response.text
        result = response.json()
        first = result["items"][0]
        assert first["document_id"] == pump
        assert set(first["method_scores"]) == {"bm25", "concept", "graph", "structure"}
        assert result["diagnostics"]["graph_version"]
        assert client.get(first["source_url"]).json()["primary"] == first["evidence"]
        filtered = client.post(
            f"{BASE}/search",
            json={
                "query": "requires",
                "document_ids": [motor],
                "methods": ["bm25"],
                "element_types": [first["element_type"]],
            },
        ).json()
        assert [hit["document_id"] for hit in filtered["items"]] == [motor]
        assert set(filtered["items"][0]["method_scores"]) == {"bm25"}
        assert (
            client.post(
                f"{BASE}/search",
                json={"query": "pump", "document_ids": [str(uuid4())]},
            ).json()["items"]
            == []
        )


def test_search_omits_invalid_evidence_and_reports_unavailable_model(database, migration, tmp_path):
    command.upgrade(migration, "head")
    app = create_app(
        Settings(
            database_path=database,
            ingestion_worker=False,
            nlp_model_dir=tmp_path / "missing",
        )
    )
    model(app, database, "pump.md", "The pump requires a ceramic filter.")
    with Session(app.state.structure_store.engine) as session:
        chunk = session.scalar(select(DocumentChunk))
        chunk.payload = {**chunk.payload, "text": "The pump operates underwater."}
        session.commit()
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        result = client.post(
            f"{BASE}/search",
            json={"query": "underwater", "methods": ["bm25"]},
        ).json()
        assert result["items"] == []
        assert result["diagnostics"]["invalid_sources"] == 1
        dense = client.post(f"{BASE}/search", json={"query": "pump", "methods": ["dense"]})
        assert dense.status_code == 503, dense.text


def test_ask_requires_one_direct_statement_in_selected_document(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    reliable = model(app, database, "pump.md", "The pump requires a filter.")
    unrelated = model(app, database, "motor.md", "The motor requires a pump.")
    conflict = model(
        app,
        database,
        "conflict.md",
        "The pump requires a filter. The pump requires a regulator.",
    )
    negated = model(
        app,
        database,
        "negated.md",
        "The pump requires a filter. The pump does not require a filter.",
    )
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        for document_id in (reliable, unrelated, conflict, negated):
            response = client.post(
                f"{BASE}/ask",
                json={
                    "document_id": document_id,
                    "question": "What does the pump require?",
                },
            )
            assert response.status_code == 200, response.text
            data = response.json()
            if document_id == reliable:
                assert data["answer"] == "The pump requires a filter."
                assert data["citations"][0]["document_id"] == reliable
            else:
                assert data["status"] == "insufficient_evidence"
                assert data["citations"] == []


def test_pdf_summary_quotes_selected_document_across_pages(database, migration):
    from io import BytesIO
    from time import monotonic, sleep

    from reportlab.pdfgen.canvas import Canvas
    from test_ingestion import post

    command.upgrade(migration, "head")
    output = BytesIO()
    passages = [
        "Electric current measures how quickly electric charge moves through a circuit.",
        "Electrical resistance limits the flow of charge through a conductor.",
    ]
    canvas = Canvas(output)
    for passage in passages:
        canvas.drawString(36, 700, passage)
        canvas.showPage()
    canvas.save()
    app = create_app(Settings(database_path=database))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        upload = post(client, "electricity.pdf", output.getvalue())
        assert upload.status_code == 202, upload.text
        document_id = upload.json()["document"]["id"]
        deadline = monotonic() + 15
        while client.get(f"{BASE}/documents/{document_id}/structure").json()["status"] != "ready":
            assert monotonic() < deadline
            sleep(0.1)
        response = client.post(
            f"{BASE}/ask",
            json={"document_id": document_id, "question": "Summary of this document"},
        )
        assert response.status_code == 200, response.text
        answer = response.json()
        assert answer["summary"] == passages
        assert [hit["locator"]["page"] for hit in answer["citations"]] == [1, 2]
        for excerpt, hit in zip(passages, answer["citations"], strict=True):
            assert excerpt in client.get(hit["source_url"]).json()["primary"]["text"]
