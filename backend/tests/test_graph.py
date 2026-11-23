import os
import subprocess
import sys
import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_ingestion import post
from test_ncm import sources

from smartdoc.app import create_app
from smartdoc.config import Settings
from smartdoc.graph.contracts import SourceRevision
from smartdoc.graph.projection import GraphSource, Projector
from smartdoc.ingestion.contracts import Extraction, ExtractionError, SourceUnit
from smartdoc.ncm.contracts import Weights
from smartdoc.ncm.model import build_snapshot
from smartdoc.persistence.graph_queries import Filters, GraphQueries
from smartdoc.persistence.ingestion_models import LOCAL_WORKSPACE_ID
from smartdoc.persistence.ingestion_store import Upload
from smartdoc.persistence.ncm_models import NcmSnapshot
from smartdoc.structure.contracts import resolve_span

BASE = "/api/v1/workspaces/local"
GRAPH = BASE + "/graph"
REVIEW = {"X-SmartDoc-Local": "1"}


def build_input(text, name):
    prepared = sources(text)
    doc_id, job_id, extraction, rows, _ = prepared
    concepts = build_snapshot(*prepared, Weights())
    available = {row.chunk.id: row.chunk for row in rows}
    return GraphSource(
        revision=SourceRevision(
            document_id=doc_id, extraction_job_id=job_id, snapshot_id=uuid4(), ncm_revision=1
        ),
        filename=name,
        extraction=extraction,
        snapshot=concepts,
        chunks=lambda identifiers: {key: available[key] for key in identifiers if key in available},
    )


def model(app, db, filename, text):
    content = text.encode()
    path = db.parent / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    ext = filename.rsplit(".", 1)[-1]
    doc, _, _ = app.state.ingestion_store.accept(
        Upload(path, filename, ext, sha256(content).hexdigest(), len(content))
    )
    claim = app.state.ingestion_store.claim(30)
    assert claim is not None
    assert app.state.ingestion_store.finish(
        claim,
        Extraction(
            format=ext,
            parser="fixture",
            parser_version="1",
            units=[SourceUnit(kind="document", text=text)],
        ),
    )
    assert app.state.structure_store.build_next()
    while app.state.nlp_store.build_next():
        pass
    assert app.state.ncm_store.build_next()
    return doc.id


def test_exact_definitions_connect_documents_but_case_distinct_units_do_not():
    left = build_input("A pressure signal means a reading in MPa.", "left.md")
    other = build_input("A pressure signal means a reading in MPa.", "right.md")
    distinct = build_input("A pressure signal means a reading in mPa.", "millipascal.md")
    projector = Projector(UUID(LOCAL_WORKSPACE_ID))
    for item in (left, other, distinct):
        projector.sources(item)
    definitions = [
        node for node in projector.projection.nodes.values() if node.kind == "definition"
    ]
    assert len(definitions) == 2
    shared = next(node for node in definitions if len(node.document_ids) == 2)
    assert set(shared.document_ids) == {left.revision.document_id, other.revision.document_id}
    signals = [
        node for node in projector.projection.nodes.values() if node.label == "pressure signal"
    ]
    assert len(signals) == 3
    links = [edge for edge, _ in projector.projection.edges.values() if edge.target_id == shared.id]
    assert len(links) == 2
    assert all(edge.method == "exact_definition" for edge in links)
    for edge, anchors in projector.projection.edges.values():
        assert edge.evidence_count == len(anchors) > 0
        for anchor in anchors:
            item = next(
                item
                for item in (left, other, distinct)
                if item.revision.document_id == anchor.document_id
            )
            assert resolve_span(item.extraction, anchor.source) == anchor.text


def test_graph_rejects_fabricated_and_foreign_evidence():
    target = build_input("The pump requires a filter.", "evidence.md")
    assertion = target.snapshot.assertions[0]
    changed = [
        assertion.evidence.model_copy(update={"text": "Requires a battery."}),
        assertion.evidence.model_copy(update={"document_id": uuid4()}),
        assertion.evidence.model_copy(update={"locator": {"page": 9}}),
    ]
    for altered in changed:
        bad = assertion.model_copy(update={"evidence": altered})
        target.snapshot.assertions = [bad]
        with pytest.raises(ExtractionError, match="does not match"):
            Projector(UUID(LOCAL_WORKSPACE_ID)).sources(target)


def test_projection_rejects_assertion_using_another_documents_concept_id():
    left = build_input("The pump requires a filter.", "left.md")
    right = build_input("The motor requires a regulator.", "right.md")
    projection = Projector(UUID(LOCAL_WORKSPACE_ID))
    projection.sources(right)
    left.snapshot.assertions = [
        left.snapshot.assertions[0].model_copy(
            update={"object_id": right.snapshot.assertions[0].object_id}
        )
    ]
    with pytest.raises(ExtractionError, match="outside its NCM document"):
        projection.sources(left)


def test_standalone_alembic_cli_uses_all_orm_metadata(database):
    config = Path(__file__).resolve().parents[1] / "alembic.ini"
    command = [sys.executable, "-m", "alembic", "-c", str(config)]
    environment = {**os.environ, "SMARTDOC_DATABASE_PATH": str(database)}
    for arguments in (["upgrade", "head"], ["check"]):
        process = subprocess.run(
            [*command, *arguments],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert process.returncode == 0, process.stdout + process.stderr


def test_migration_cross_document_paths_filters_and_analytics(database, migration):
    command.upgrade(migration, "0005_ncm_snapshots")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    left = model(
        app,
        database,
        "left.md",
        "# Pump Assembly\n\nA filter means a mesh screen. The pump requires a filter.",
    )
    right = model(
        app,
        database,
        "right.md",
        "# Water Loop\n\nA filter means a mesh screen. The filter depends on a valve.",
    )
    command.upgrade(migration, "head")
    command.check(migration)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get(GRAPH).json()["latest"] is None
        assert client.get(GRAPH + "/nodes").json()["code"] == "graph_pending"
        assert app.state.graph_store.build_next()
        assert not app.state.graph_store.build_next()
        status = client.get(GRAPH).json()
        version = status["available_version"]
        assert status["latest"]["document_count"] == 2
        assert {item["document_id"] for item in status["latest"]["sources"]} == {left, right}

        left_nodes = client.get(
            GRAPH + "/nodes", params={"document_id": left, "limit": 100}
        ).json()["items"]
        right_nodes = client.get(
            GRAPH + "/nodes", params={"document_id": right, "limit": 100}
        ).json()["items"]
        assert not any(node["label"] == "valve" for node in left_nodes)
        assert all(left in node["document_ids"] for node in left_nodes)
        assert sum(node["kind"] == "document" for node in left_nodes) == 1
        assert any(node["kind"] == "section" for node in left_nodes)
        assert any(node["kind"] == "chunk" for node in left_nodes)
        hub = next(node for node in left_nodes if node["kind"] == "definition")
        assert set(hub["document_ids"]) == {left, right}
        pump = next(node["id"] for node in left_nodes if node["label"] == "pump")
        valve = next(node["id"] for node in right_nodes if node["label"] == "valve")
        page = client.get(GRAPH + "/nodes", params={"query": "PUMP", "limit": 1}).json()
        second = client.get(
            GRAPH + "/nodes",
            params={
                "version_id": version,
                "query": "PUMP",
                "after": page["next_cursor"],
                "limit": 1,
            },
        ).json()
        assert page["version_id"] == version
        assert page["items"][0]["id"] != second["items"][0]["id"]
        assert client.get(GRAPH + "/nodes", params={"query": "%"}).json()["items"] == []

        path = client.get(
            GRAPH + "/paths",
            params={
                "source": pump,
                "target": valve,
                "direction": "both",
                "depth": 6,
            },
        ).json()
        assert path["status"] == "found" and not path["truncated"]
        assert path["node_ids"][0] == pump and path["node_ids"][-1] == valve
        assert len(path["steps"]) == 4
        assert {step["evidence"]["document_id"] for step in path["steps"]} == {left, right}
        for step in path["steps"]:
            edge_id = step["edge"]["id"]
            evidence = client.get(GRAPH + f"/edges/{edge_id}/evidence").json()["items"]
            assert step["evidence"] in evidence

        bounded = client.get(
            GRAPH + "/paths",
            params={
                "source": pump,
                "target": valve,
                "direction": "both",
                "depth": 1,
            },
        ).json()
        assert bounded["status"] == "limit_reached" and bounded["truncated"]
        filtered = client.get(
            GRAPH + "/paths", params={"source": pump, "target": valve, "document_id": left}
        )
        assert filtered.status_code == 404
        outgoing = client.get(
            GRAPH + "/neighbors",
            params={
                "node_id": pump,
                "document_id": left,
                "direction": "out",
                "depth": 2,
            },
        ).json()
        assert all(step["evidence"]["document_id"] == left for step in outgoing["edges"])

        stats = client.get(GRAPH + "/analytics", params={"communities": "true"}).json()
        assert stats["node_count"] >= 5 and stats["edge_count"] >= 4
        assert stats["degree"][0]["degree"] > 0
        assert stats["communities"]


def test_review_republishes_graph_and_preserves_historical_paths(database, migration):
    command.upgrade(migration, "head")
    settings = Settings(database_path=database, ingestion_worker=False)
    app = create_app(settings)
    doc = model(
        app, database, "parts.txt", "The pump requires a filter. The filter depends on a motor."
    )
    assert app.state.graph_store.build_next()
    original = app.state.graph_store.status().available_version
    url = f"{BASE}/documents/{doc}/ncm"
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        edges = client.get(
            GRAPH + "/edges", params={"predicate": "REQUIRES", "kind": "assertion"}
        ).json()["items"]
        first = edges[0]
        target = client.get(GRAPH + "/nodes", params={"query": "motor"}).json()["items"][0]
        args = {"source": first["source_id"], "target": target["id"], "view": "dependencies"}
        assert client.get(GRAPH + "/paths", params=args).json()["status"] == "found"
        reviewed = client.post(
            url + "/revisions",
            headers=REVIEW,
            json={
                "action": "reject_assertion",
                "assertion_id": first["assertion_id"],
                "expected_revision": 1,
                "reason": "Confirmed obsolete dependency.",
            },
        )
        assert reviewed.status_code == 201, reviewed.text
        assert app.state.graph_store.build_next()
        latest = client.get(GRAPH).json()
        assert latest["available_version"] != str(original)
        assert latest["latest"]["sources"][0]["ncm_revision"] == 2
        assert client.get(GRAPH + "/paths", params=args).json()["status"] == "not_found"
        assert (
            client.get(GRAPH + "/paths", params={**args, "version_id": original}).json()["status"]
            == "found"
        )
        preserved = client.get(
            GRAPH + f"/edges/{first['id']}/evidence", params={"version_id": original}
        )
        assert preserved.json()["items"][0]["text"] == "The pump requires a filter."
        rejected = client.get(GRAPH + "/edges", params={"validation": "rejected"}).json()["items"]
        assert rejected[0]["id"] == first["id"] and not rejected[0]["traversable"]
        first_page = client.get(GRAPH + "/versions", params={"limit": 1}).json()
        assert first_page["items"][0]["id"] == str(original)
        assert first_page["next_cursor"] == first_page["items"][0]["sequence"]

    restarted = create_app(settings)
    assert not restarted.state.graph_store.build_next()
    assert restarted.state.graph_store.status().available_version == UUID(
        latest["available_version"]
    )


def test_corrupt_revision_records_failure_and_keeps_last_ready_graph(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    doc = model(app, database, "pump.txt", "The pump requires a filter.")
    assert app.state.graph_store.build_next()
    prior = app.state.graph_store.status().available_version
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"{BASE}/documents/{doc}/ncm/revisions",
            headers=REVIEW,
            json={
                "action": "rebuild",
                "expected_revision": 1,
                "reason": "Exercise a later snapshot.",
            },
        )
        assert response.status_code == 201
        with Session(app.state.ncm_store.engine) as session, session.begin():
            newest = session.get(NcmSnapshot, response.json()["id"])
            body = deepcopy(newest.payload)
            body["assertions"][0]["evidence"]["text"] = "Source changed."
            newest.payload = body
        assert app.state.graph_store.build_next()
        state = client.get(GRAPH).json()
        assert state["latest"]["status"] == "failed"
        assert state["latest"]["error"] == "invalid_provenance"
        assert state["available_version"] == str(prior)
        assert client.get(GRAPH + "/nodes").json()["version_id"] == str(prior)
        assert (
            client.get(GRAPH + "/nodes", params={"version_id": state["latest"]["id"]}).json()[
                "code"
            ]
            == "graph_failed"
        )
        assert not app.state.graph_store.build_next()


def test_only_traversable_assertions_participate_in_scc_and_budget(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    doc = model(
        app,
        database,
        "drive.md",
        "# Drive\n\nThe pump requires a filter. The filter depends on a pump. "
        "The pump may use a capacitor. The pump requires a coil. The pump does not require a coil.",
    )
    assert app.state.graph_store.build_next()
    version = app.state.graph_store.status().available_version
    graph = GraphQueries(app.state.graph_store.engine, version)
    dependency = Filters(document_id=UUID(doc), view="dependencies")
    edges = graph.edges(dependency, 0, 100)
    assert sum(edge.validation == "conflicted" for _, edge in edges) == 2
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        orphans = client.get(GRAPH + "/orphans", params={"view": "dependencies"}).json()
        assert "capacitor" in {item["label"] for item in orphans["items"]}
        assert "pump" not in {item["label"] for item in orphans["items"]}
        stats = client.get(GRAPH + "/analytics", params={"view": "dependencies"}).json()
        assert len(stats["cycles"]) == 1
        assert len(stats["cycles"][0]["node_ids"]) == 2
        assert stats["edge_count"] == 2
        pump = client.get(GRAPH + "/nodes", params={"query": "pump", "kind": "concept"}).json()[
            "items"
        ][0]
        limited = client.get(
            GRAPH + "/neighbors", params={"node_id": pump["id"], "limit": 1}
        ).json()
        assert limited["truncated"] and len(limited["nodes"]) == 1


def test_worker_creates_collection_graph_for_uploaded_documents(database, migration):
    command.upgrade(migration, "head")
    with TestClient(
        create_app(Settings(database_path=database)),
        base_url="http://localhost",
        client=("127.0.0.1", 50000),
    ) as client:
        upload = post(client, "camera.txt", b"The camera requires a lens.")
        assert upload.status_code == 202
        document = upload.json()["document"]["id"]
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            state = client.get(GRAPH).json()
            if state["latest"] and state["latest"]["document_count"] == 1:
                assert state["latest"]["status"] == "ready", state
                assert state["latest"]["sources"][0]["document_id"] == document
                break
            time.sleep(0.1)
        else:
            pytest.fail("The graph worker did not publish the document.")
        browse = client.get(GRAPH + "/edges", params={"predicate": "REQUIRES"}).json()
        assert browse["items"][0]["traversable"]
        assert client.get(GRAPH, headers={"Origin": "https://outside.example"}).status_code == 403
