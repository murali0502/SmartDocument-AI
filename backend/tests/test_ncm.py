import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from test_ingestion import post

from smartdoc.app import create_app
from smartdoc.config import Settings
from smartdoc.ingestion.contracts import Extraction, ExtractionError, SourceUnit
from smartdoc.ncm.candidates import Inputs
from smartdoc.ncm.contracts import Weights
from smartdoc.ncm.dependencies import dependency_view
from smartdoc.ncm.model import build_snapshot
from smartdoc.ncm.revisions import compare, merge, reject_assertion
from smartdoc.nlp.pipeline import LanguagePipeline
from smartdoc.structure.builder import build_structure
from smartdoc.structure.contracts import resolve_span

BASE = "/api/v1/workspaces/local"
HEADER = {"X-SmartDoc-Local": "1"}


def sources(text, *, document_id=None, job_id=None, terms=None):
    document_id, job_id = document_id or uuid4(), job_id or uuid4()
    extraction = Extraction(
        format="md",
        parser="fixture",
        parser_version="1",
        units=[SourceUnit(kind="document", text=text)],
    )
    now = datetime.now(UTC)
    chunks = build_structure(document_id, job_id, extraction, now).chunks
    pipeline = LanguagePipeline("rules", Path("."), terms or {})
    rows = [
        Inputs(chunk, annotation)
        for chunk, annotation in zip(chunks, pipeline.annotate_batch(chunks), strict=True)
    ]
    return document_id, job_id, extraction, rows, now


def snapshot(text, **kwargs):
    return build_snapshot(*sources(text, **kwargs), Weights())


def test_anchored_concepts_acronyms_prioritization_and_stable_ids():
    text = (
        "# Hydraulics\n\n## Pump Assembly\n\n"
        "An Auxiliary Control Unit (ACU) regulates the system. "
        "The ACU requires a pressure sensor. "
        "A pressure sensor means a pressure transducer. "
        "The pressure sensor is part of the Pump Assembly."
    )
    prepared = sources(text)
    data = build_snapshot(*prepared, Weights())
    repeated = build_snapshot(*prepared, Weights())
    assert data == repeated
    concepts = {item.normalized: item for item in data.concepts}
    unit = concepts["auxiliary control unit"]
    sensor = concepts["pressure sensor"]
    assert "acu" not in concepts
    assert unit.aliases[0].surface == "ACU" and unit.aliases[0].method == "acronym"
    requires = next(item for item in data.assertions if item.type == "REQUIRES")
    assert requires.subject_id == unit.id and requires.object_id == sensor.id
    assert requires.subject.text == "ACU"
    assert requires.validation == "source_validated"
    assert requires.evidence.text == "The ACU requires a pressure sensor."
    assert sensor.definitions[0].expression.text == "pressure transducer"
    assert sensor.score.features["definition"] == 3
    assert len(data.hierarchy) >= 3
    assert any(
        edge.child_id == sensor.id
        and edge.parent_id == concepts["pump assembly"].id
        and edge.kind == "part_of"
        for edge in data.hierarchy
    )
    assert any(
        edge.child_id == concepts["pump assembly"].id
        and edge.parent_id == concepts["hydraulics"].id
        and edge.kind == "section"
        for edge in data.hierarchy
    )
    for item in data.assertions:
        for anchor in (item.subject, item.predicate, item.object, item.evidence):
            assert resolve_span(prepared[2], anchor.source) == anchor.text
    different = build_snapshot(*prepared, Weights(definition=10))
    assert different.concepts[0].id == sensor.id
    assert different.concepts[0].score.features["definition"] == 10


def test_ambiguous_acronyms_and_distinct_definition_scopes():
    data = snapshot(
        "# Cooling\n\nA Control Unit (CU) is installed. "
        "A gauge means a mechanical indicator.\n\n"
        "# Chemistry Workspace\n\nA Chemical Unit (CU) is installed. "
        "A gauge means a concentration indicator. The CU requires a filter."
    )
    assert len(data.ambiguous_aliases) == 1
    assert data.ambiguous_aliases[0].surface == "CU"
    assert len(data.ambiguous_aliases[0].alternatives) == 2
    assert len(data.ambiguous_aliases[0].evidence) == 2
    matching = [item for item in data.concepts if item.normalized == "gauge"]
    assert len(matching) == 2 and len({item.sense for item in matching}) == 2
    assert len({item.definitions[0].expression.text for item in matching}) == 2
    relation = next(item for item in data.assertions if item.type == "REQUIRES")
    assert relation.validation == "needs_review"
    result = dependency_view(data.assertions, relation.subject_id, "prerequisites", 3)
    assert not result.paths


def test_conflicts_polarity_dependency_cycles_and_impact():
    data = snapshot(
        "The pump requires a filter. The filter depends on a valve. The valve requires a pump. "
        "The pump may use a thermostat. The pump requires power. The pump does not require power."
    )
    concepts = {item.normalized: item.id for item in data.concepts}
    origin = concepts["pump"]
    view = dependency_view(data.assertions, origin, "prerequisites", 4)
    assert {edge.concept_ids[-1]: edge.depth for edge in view.paths} == {
        concepts["filter"]: 1,
        concepts["valve"]: 2,
    }
    assert view.cycles[0].concepts == sorted([origin, concepts["filter"], concepts["valve"]])
    assert len(view.cycles[0].assertions) == 3
    impact = dependency_view(data.assertions, concepts["filter"], "impact", 2)
    assert impact.paths[0].concept_ids[-1] == origin
    assert dependency_view(data.assertions, origin, "prerequisites", 1).truncated
    assert [row.validation for row in data.assertions if row.object_id == concepts["power"]] == [
        "conflicted",
        "conflicted",
    ]
    negative = next(row for row in data.assertions if row.negated)
    rejected = reject_assertion(data, negative.id, Weights())
    assert (
        next(row for row in rejected.assertions if row.id == negative.id).validation == "rejected"
    )
    assert concepts["power"] in {
        path.concept_ids[-1]
        for path in dependency_view(rejected.assertions, origin, "prerequisites", 3).paths
    }
    assert data.assertions[-1].validation == "conflicted"


def test_unverifiable_nlp_relation_is_discarded_and_invalid_chunk_fails():
    *start, rows, timestamp = sources("The pump requires a filter.")
    reported = rows[0].annotation
    bad = reported.relations[0].model_copy(update={"type": "PRODUCES"})
    rows[0].annotation = reported.model_copy(update={"relations": [bad]})
    results = build_snapshot(*start, rows, timestamp, Weights())
    assert not results.assertions
    assert results.rejected_candidates == 1
    rows[0].chunk = rows[0].chunk.model_copy(update={"text": "The pump produces a filter."})
    with pytest.raises(ExtractionError, match="does not match"):
        build_snapshot(*start, rows, timestamp, Weights())


def test_evolution_tracks_evidenced_rename_definition_and_deprecation():
    left = snapshot("The pump requires an old controller. A pressure sensor means an analog gauge.")
    right = snapshot(
        "The old controller is now called the regulator. "
        "A pressure sensor means a digital probe. "
        "The pressure sensor is deprecated. The pump requires a regulator."
    )
    changes = compare(left, right)
    rename = next(row for row in changes if row.kind == "renamed")
    assert rename.left_label == "old controller" and rename.right_label == "regulator"
    assert rename.left_evidence and rename.right_evidence
    definition = next(row for row in changes if row.kind == "definitions_changed")
    assert "analog gauge" in definition.left_evidence[0].text
    assert "digital probe" in definition.right_evidence[0].text
    status = next(row for row in changes if row.kind == "lifecycle_changed")
    assert "deprecated" in status.right_evidence[0].text
    assert compare(left, left) == []


def test_reviewed_merge_is_reversible_and_records_evidence():
    data = snapshot("The blower requires a filter. The fan depends on a motor.")
    objects = {item.normalized: item for item in data.concepts}
    old, new = objects["blower"], objects["fan"]
    rebuilt = merge(data, old.id, new.id, Weights())
    assert old.id in {concept.id for concept in data.concepts}
    assert old.id not in {concept.id for concept in rebuilt.concepts}
    assert (
        next(concept for concept in rebuilt.concepts if concept.id == new.id).aliases[0].method
        == "review"
    )
    assert all(item.subject_id == new.id for item in rebuilt.assertions)
    difference = next(item for item in compare(data, rebuilt) if item.kind == "merged")
    assert difference.left_id == old.id and difference.right_id == new.id
    assert len(difference.right_evidence) == 2


def test_phase_four_database_backfills_with_auditable_history(database, migration):
    command.upgrade(migration, "0004_linguistic_annotations")
    settings = Settings(database_path=database, ingestion_worker=False)
    app = create_app(settings)
    from hashlib import sha256

    from smartdoc.persistence.ingestion_store import Upload

    source = database.parent / "old.txt"
    content = b"The blower requires a filter. The fan depends on a motor."
    source.write_bytes(content)
    stored, _, _ = app.state.ingestion_store.accept(
        Upload(source, "old.txt", "txt", sha256(content).hexdigest(), len(content))
    )
    claim = app.state.ingestion_store.claim(30)
    data = Extraction(
        format="txt",
        parser="fixture",
        parser_version="1",
        units=[SourceUnit(kind="document", text=content.decode())],
    )
    assert app.state.ingestion_store.finish(claim, data)
    assert app.state.structure_store.build_next()
    assert app.state.nlp_store.build_next()
    command.upgrade(migration, "head")
    command.check(migration)

    url = f"{BASE}/documents/{stored.id}/ncm"
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get(url).json()["status"] == "pending"
        assert client.get(url + "/concepts").json()["code"] == "ncm_pending"
        assert app.state.ncm_store.build_next()
        assert not app.state.ncm_store.build_next()
        base = client.get(url).json()
        assert base["revision"] == 1 and base["status"] == "ready"
        items = client.get(url + "/concepts").json()["items"]
        by_label = {item["normalized"]: item for item in items}
        original = by_label["blower"]["id"]
        kept = by_label["fan"]["id"]
        payload = {
            "action": "merge",
            "reason": "Same part in this manual.",
            "expected_revision": 1,
            "source": original,
            "target": kept,
        }
        assert client.post(url + "/revisions", json=payload).status_code == 403
        response = client.post(url + "/revisions", headers=HEADER, json=payload)
        assert response.status_code == 201, response.text
        written = response.json()
        assert written["revision"] == 2 and written["parent_id"] == base["id"]
        assert written["audit"]["reason"] == payload["reason"]
        stale = client.post(url + "/revisions", headers=HEADER, json=payload)
        assert (stale.status_code, stale.json()["code"]) == (409, "revision_conflict")
        assert client.get(url + f"/concepts/{original}").status_code == 404
        assert client.get(url + f"/concepts/{original}?revision=1").status_code == 200
        compare_response = client.get(
            f"{BASE}/ncm/compare",
            params={
                "left": stored.id,
                "right": stored.id,
                "left_revision": 1,
                "right_revision": 2,
                "chronology": "declared_left_before_right",
            },
        )
        assert compare_response.status_code == 200
        assert any(
            change["kind"] == "merged" for change in compare_response.json()["changes"]["items"]
        )

    restarted = create_app(settings)
    with TestClient(restarted, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get(url).json() == written
        restore = client.post(
            url + "/revisions",
            headers=HEADER,
            json={
                "action": "restore",
                "reason": "Undo tentative match",
                "expected_revision": 2,
                "restore_revision": 1,
            },
        )
        assert restore.json()["revision"] == 3
        assert client.get(url + f"/concepts/{original}").status_code == 200
        history = client.get(url + "/revisions", params={"limit": 2}).json()
        assert history["next_cursor"] == 2
        assert [item["audit"]["action"] for item in history["items"]] == ["build", "merge"]
        rebuilt = client.post(
            url + "/revisions",
            headers=HEADER,
            json={
                "action": "rebuild",
                "reason": "Rerun from source",
                "expected_revision": 3,
            },
        )
        assert rebuilt.status_code == 201 and rebuilt.json()["revision"] == 4


def test_live_worker_builds_concepts_for_new_upload(database, migration):
    command.upgrade(migration, "head")
    with TestClient(
        create_app(Settings(database_path=database)),
        base_url="http://localhost",
        client=("127.0.0.1", 50000),
    ) as client:
        upload = post(client, "gearbox.txt", b"The gearbox requires a lubricant.")
        assert upload.status_code == 202
        doc = upload.json()["document"]["id"]
        url = f"{BASE}/documents/{doc}/ncm"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            info = client.get(url).json()
            if info["status"] != "pending":
                assert info["status"] == "ready", info
                break
            time.sleep(0.05)
        else:
            pytest.fail("The worker did not publish NCM output.")
        edge = client.get(url + "/assertions").json()["items"][0]
        assert edge["evidence"]["text"] == "The gearbox requires a lubricant."
        result = client.get(url + f"/dependencies/{edge['subject_id']}").json()
        assert result["paths"][0]["assertion_ids"] == [edge["id"]]


def test_lexical_context_suggests_duplicates_without_merging():
    data = snapshot(
        "# Bearings\n\nA drive shaft requires two rolling bearings. "
        "A rolling bearing is part of the drive shaft. "
        "Rolling bearings depend on lubrication."
    )
    concepts = {item.normalized: item for item in data.concepts}
    left, right = concepts["rolling bearing"], concepts["rolling bearings"]
    suggestion = next(
        row
        for row in data.duplicate_candidates
        if {row.left_id, row.right_id} == {left.id, right.id}
    )
    assert suggestion.lexical_key == "rolling bearing"
    assert len(suggestion.evidence) == 2
    assert left.id != right.id
