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
                expected = (
                    "insufficient_evidence"
                    if document_id == unrelated
                    else "clarification_required"
                )
                assert data["status"] == expected
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


def test_reasoning_cites_dependency_chain_and_checked_conversion(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    document = model(
        app,
        database,
        "technical.md",
        "# Circuit\n\n"
        "The pump requires a filter. The filter depends on a valve.\n\n"
        "The rated voltage is 220 V.\n\n"
        "The circuit was approved in 2024.",
    )
    assert app.state.graph_store.build_next()
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        checks = {
            "How does pump depend on valve?": "The document supports this dependency chain.",
            "What is the rated voltage in kV?": "0.22 kV",
            "When was the circuit approved?": "The circuit was approved in 2024.",
        }
        for question, expected in checks.items():
            response = client.post(
                f"{BASE}/ask",
                json={
                    "document_id": document,
                    "question": question,
                },
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["answer"] == expected, data
            for hit in data["citations"]:
                assert client.get(hit["source_url"]).json()["primary"] == hit["evidence"]
            if question.startswith("How"):
                assert data["reasoning"] == ["pump requires filter.", "filter depends on valve."]
        mismatch = client.post(
            f"{BASE}/ask",
            json={
                "document_id": document,
                "question": "What is the rated voltage in A?",
            },
        ).json()
        assert mismatch["status"] == "insufficient_evidence"


def test_evaluation_report_contains_measured_baseline(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        report = client.get(f"{BASE}/evaluation").json()
        assert report["queries"] > 0
        assert 0 <= report["variants"]["bm25"]["recall_at_5"] <= 1


def test_comparison_reports_source_backed_opposing_statements(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    first = model(app, database, "first.md", "The pump requires a filter.")
    second = model(app, database, "second.md", "The pump does not require a filter.")
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        response = client.get(f"{BASE}/ncm/compare", params={"left": first, "right": second})
        assert response.status_code == 200, response.text
        opposing = response.json()["opposing_statements"]
        assert len(opposing) == 1
        assert "requires a filter" in opposing[0]["left"]["text"]
        assert "does not require a filter" in opposing[0]["right"]["text"]


def test_question_can_be_scoped_to_a_named_section(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    document = model(
        app,
        database,
        "modes.md",
        "# Standard mode\n\nThe pump requires a filter.\n\n"
        "# Service mode\n\nThe pump requires a regulator.",
    )
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"{BASE}/ask",
            json={
                "document_id": document,
                "question": "What does the pump require in section Service mode?",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "The pump requires a regulator."


def test_decomposed_comparison_temporal_order_and_relationship(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    document = model(
        app,
        database,
        "comparison.md",
        "A pump is a device that moves water.\n\n"
        "A filter is a device that removes particles.\n\n"
        "The pump requires a filter.\n\n"
        "The pump was approved in 2024.\n\n"
        "The filter was approved on 2023-06-09.\n\n"
        "The valve was approved on 2024-04-22.",
    )
    assert app.state.graph_store.build_next()
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:

        def ask(prompt):
            response = client.post(
                f"{BASE}/ask", json={"question": prompt, "document_id": document}
            )
            assert response.status_code == 200, response.text
            return response.json()

        compared = ask("What is the difference between pump and filter?")
        assert compared["status"] == "answered"
        assert compared["reasoning"] == [
            "A pump is a device that moves water.",
            "A filter is a device that removes particles.",
        ]
        related = ask("How are filter and pump connected?")
        assert related["reasoning"] == ["pump requires filter."]
        ordered = ask("Which was approved first: pump or filter?")
        assert ordered["reasoning"][0] == "The filter was approved on 2023-06-09."
        overlap = ask("Which was approved first: pump or valve?")
        assert overlap["status"] == "clarification_required"
        for result in (compared, related, ordered):
            for hit in result["citations"]:
                assert client.get(hit["source_url"]).json()["primary"] == hit["evidence"]


def test_claim_validation_requires_opt_in_and_abstains_on_conflict(
    database, migration, monkeypatch
):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    document = model(
        app,
        database,
        "claim.md",
        "The pump requires a filter.\n\nThe pump does not require a filter.",
    )
    body = {"document_id": document, "claim": "The pump requires a filter."}
    url = f"{BASE}/validate-claim"
    headers = {"X-SmartDoc-Local": "1"}

    def inference(pairs):
        return [
            {"entailment": 0.98, "contradiction": 0.01}
            if "does not" not in premise
            else {"entailment": 0.01, "contradiction": 0.98}
            for premise, _ in pairs
        ], [False] * len(pairs)

    monkeypatch.setattr(app.state.local_inference, "infer", inference)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.post(url, json=body).status_code == 403
        refused = client.post(url, json=body, headers=headers)
        assert refused.json()["status"] == "insufficient_evidence"
        assert refused.json()["claims"] == []
        question = {"document_id": document, "question": "Summary of this document"}
        answer = client.post(f"{BASE}/ask", json=question).json()
        sources = {item["chunk_id"]: item["evidence"]["text"] for item in answer["citations"]}
        assert answer["claims"]
        for claim in answer["claims"]:
            assert claim["text"] in sources[claim["source_chunk_ids"][0]]


def test_comparison_keeps_claims_in_their_selected_documents(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    first = model(app, database, "pump.md", "A pump is a device that moves water.")
    second = model(app, database, "filter.md", "A filter is a device that removes particles.")
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"{BASE}/ask",
            json={
                "question": "Compare pump and filter",
                "document_id": first,
                "comparison_document_id": second,
            },
        )
        assert response.status_code == 200, response.text
        compared = response.json()
        assert compared["status"] == "answered"
        assert [hit["document_id"] for hit in compared["citations"]] == [first, second]
        assert len(compared["claims"]) == 2
        for claim, hit in zip(compared["claims"], compared["citations"], strict=True):
            assert claim["source_chunk_ids"] == [hit["chunk_id"]]
