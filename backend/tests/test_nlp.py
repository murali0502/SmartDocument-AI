import math
import os
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
from smartdoc.ingestion.contracts import Extraction, SourceUnit
from smartdoc.nlp.pipeline import LanguagePipeline
from smartdoc.structure.contracts import Chunk, SourceSpan

BASE = "/api/v1/workspaces/local"
MODEL_HEADER = {"X-SmartDoc-Local": "1"}


def make_chunk(text: str, offset: int = 11) -> Chunk:
    return Chunk(
        id=uuid4(),
        document_id=uuid4(),
        parent_element_id=uuid4(),
        ordinal=1,
        text=text,
        token_count=len(text.split()),
        character_count=len(text),
        locator={"page": 3},
        section_path=[],
        element_type="paragraph",
        strategy="sentence-first-v1",
        primary=SourceSpan(unit=2, field=("text",), start=offset, end=offset + len(text)),
        overlap=[],
        created_at=datetime.now(UTC),
    )


def test_rules_annotate_entities_dates_and_normalize_without_moving_ranges(tmp_path):
    chunk = make_chunk(
        "The café controller uses Python at 100 kPa on February 29, 2024. Restart today."
    )
    pipeline = LanguagePipeline("rules", tmp_path, {"DEVICE": ["controller"]})
    item = next(pipeline.annotate_batch([chunk]))
    assert item.language == "en"
    assert item.source == chunk.primary
    assert item.tokens[0].span.start == chunk.primary.start
    assert all(token.lemma is None and token.dependency is None for token in item.tokens)
    assert {(x.label, x.span.text) for x in item.entities} == {
        ("TECHNOLOGY", "Python"),
        ("MEASUREMENT", "100 kPa"),
        ("DATE", "February 29, 2024"),
        ("DATE", "today"),
        ("DEVICE", "controller"),
    }
    assert [(value.kind, value.normalized) for value in item.temporal] == [
        ("date", "2024-02-29"),
        ("relative", None),
    ]
    for span in [
        *item.sentences,
        *(row.span for row in item.tokens),
        *(row.span for row in item.entities),
    ]:
        assert (
            chunk.text[span.start - chunk.primary.start : span.end - chunk.primary.start]
            == span.text
        )
    assert item.relations == []  # A coordinated date and measurement makes this rule decline.
    text = "The Ｐump requires a filter."
    second = next(pipeline.annotate_batch([make_chunk(text)]))
    token = next(row for row in second.tokens if row.span.text == "Ｐump")
    assert token.normalized == "pump"


def test_relations_preserve_negation_modality_and_exact_evidence(tmp_path):
    text = (
        "The controller does not require a battery. "
        "The controller may use a backup sensor. "
        "The pump requires a filter when the circuit is active. "
        "A transducer measures pressure."
    )
    chunk = make_chunk(text)
    item = next(LanguagePipeline("rules", tmp_path, {}).annotate_batch([chunk]))
    assert [rel.type for rel in item.relations] == ["REQUIRES", "USES", "MEASURES"]
    first, second, _last = item.relations
    assert first.negated and first.subject.text == "controller" and first.object.text == "battery"
    assert second.modality == "may" and second.object.text == "backup sensor"
    assert item.frames[0].negated and item.frames[1].modality == "may"
    assert [role.label for role in item.frames[1].arguments] == ["agent", "instrument"]
    more = make_chunk(
        "The controller doesn’t require a battery. The pump cannot use plastic tubing. "
        "The machine uses no lubricant. Does the pump require a filter?"
    )
    comparison = next(LanguagePipeline("rules", tmp_path, {}).annotate_batch([more]))
    assert [
        (result.subject.text, result.negated, result.modality) for result in comparison.relations
    ] == [
        ("controller", True, None),
        ("pump", True, "can"),
    ]
    for row in item.relations:
        for span in (row.subject, row.predicate, row.object, row.evidence):
            assert (
                text[span.start - chunk.primary.start : span.end - chunk.primary.start] == span.text
            )


def test_coreference_keeps_unresolved_mentions_and_ignores_non_english(tmp_path):
    engine = LanguagePipeline("rules", tmp_path, {})
    chunks = [
        make_chunk(
            "Neural networks are widely used. These models can learn. This controller is new."
        ),
        make_chunk("压力传感器。阀门有过滤器。"),
    ]
    first, second = list(engine.annotate_batch(chunks))
    assert first.coreferences[0].mention.text == "These models"
    assert first.coreferences[0].antecedent.text == "Neural networks"
    assert first.coreferences[1].status == "unresolved"
    assert second.language == "und" and second.tokens and second.warnings
    assert not second.relations and not second.coreferences


def test_migration_and_resume_nlp_batches_from_existing_phase_three_results(
    database, migration, tmp_path
):
    command.upgrade(migration, "0003_document_structure")
    settings = Settings(
        database_path=database, ingestion_worker=False, nlp_model_dir=tmp_path / "models"
    )
    app = create_app(settings)
    text = "# Maintenance\n\n" + ("The pump requires a filter. The valve measures pressure. " * 350)
    path = tmp_path / "phase3.md"
    path.write_text(text, encoding="utf-8")
    from hashlib import sha256

    from smartdoc.persistence.ingestion_store import Upload

    payload = path.read_bytes()
    document, _, _ = app.state.ingestion_store.accept(
        Upload(path, "phase3.md", "md", sha256(payload).hexdigest(), len(payload))
    )
    claim = app.state.ingestion_store.claim(30)
    assert claim
    assert app.state.ingestion_store.finish(
        claim,
        Extraction(
            format="md",
            parser="phase3",
            parser_version="1",
            units=[SourceUnit(kind="document", text=text)],
        ),
    )
    assert app.state.structure_store.build_next()
    command.upgrade(migration, "head")
    command.check(migration)

    root = f"{BASE}/documents/{document.id}"
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get(root + "/nlp").json()["status"] == "pending"
        assert app.state.nlp_store.build_next()
        state = client.get(root + "/nlp").json()
        assert state["status"] == "pending" and state["annotation_count"] == 12
        assert client.get(root + "/annotations").json()["code"] == "nlp_pending"

    restarted = create_app(settings)
    while restarted.state.nlp_store.build_next():
        pass
    with TestClient(restarted, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        ready = client.get(root + "/nlp").json()
        assert ready["status"] == "ready" and ready["annotation_count"] > 12
        page = client.get(root + "/annotations", params={"limit": 2}).json()
        second = page["items"][1]
        detail = client.get(root + "/chunks/" + second["chunk_id"] + "/annotation").json()
        assert detail == second
        assert (
            client.get(root + "/annotations", params={"after": page["next_cursor"]}).json()[
                "items"
            ][0]
            != second
        )
        assert client.get(root + f"/chunks/{uuid4()}/annotation").status_code == 404


def test_worker_annotates_new_upload_and_unavailable_models_are_explicit(
    database, migration, tmp_path
):
    command.upgrade(migration, "head")
    path = tmp_path / "no-models"
    app = create_app(Settings(database_path=database, nlp_model_dir=path))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        upload = post(client, "manual.txt", b"The pump requires a filter.")
        assert upload.status_code == 202
        root = f"{BASE}/documents/{upload.json()['document']['id']}"
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            status = client.get(root + "/nlp").json()
            if status["status"] != "pending":
                assert status["status"] == "ready", status
                break
            time.sleep(0.05)
        else:
            pytest.fail("Worker did not publish NLP annotations.")
        annotations = client.get(root + "/annotations").json()["items"]
        assert annotations[0]["relations"][0]["type"] == "REQUIRES"
        request = {"texts": ["The pump requires a filter."]}
        assert client.post(BASE + "/nlp/embeddings", json=request).status_code == 403
        reply = client.post(BASE + "/nlp/embeddings", json=request, headers=MODEL_HEADER)
        assert (reply.status_code, reply.json()["code"]) == (503, "model_unavailable")

    optional = create_app(
        Settings(
            database_path=database, nlp_profile="spacy", nlp_model_dir=path, ingestion_worker=False
        )
    )
    with TestClient(optional, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get(root + "/nlp").json()["status"] == "unavailable"
        assert client.get(root + "/annotations").status_code == 503


def test_real_models_when_explicitly_installed(database, migration):
    root = os.environ.get("SMARTDOC_TEST_MODEL_DIR")
    if not root:
        pytest.skip("Set SMARTDOC_TEST_MODEL_DIR to run the optional local models.")
    pipeline = LanguagePipeline("spacy", Path(root), {})
    assert pipeline.available
    text = "Microsoft uses cloud services. The pumps required new filters."
    item = next(pipeline.annotate_batch([make_chunk(text)]))
    assert any(
        entity.label == "ORG" and entity.span.text == "Microsoft" for entity in item.entities
    )
    assert any(token.lemma == "pump" and token.dependency == "nsubj" for token in item.tokens)
    assert item.relations[0].method == "dependency-pattern"
    assert any(
        phrase.label == "noun_phrase" and "cloud services" in phrase.span.text
        for phrase in item.phrases
    )

    command.upgrade(migration, "head")
    app = create_app(
        Settings(database_path=database, nlp_model_dir=Path(root), ingestion_worker=False)
    )
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        embedding = client.post(
            BASE + "/nlp/embeddings",
            headers=MODEL_HEADER,
            json={"texts": ["A pump requires a filter.", "A filter is required by the pump."]},
        ).json()
        assert embedding["dimensions"] == 384
        left, right = [row["vector"] for row in embedding["items"]]
        assert math.isclose(sum(x * x for x in left), 1, rel_tol=1e-5)
        assert sum(x * y for x, y in zip(left, right, strict=True)) > 0.8
        nli = client.post(
            BASE + "/nlp/inference",
            headers=MODEL_HEADER,
            json={
                "pairs": [
                    {"premise": "The valve is open.", "hypothesis": "The valve is closed."},
                    {"premise": "A red dog runs in a park.", "hypothesis": "A dog is running."},
                    {"premise": "A dog is running.", "hypothesis": "The dog is hungry."},
                ]
            },
        ).json()
        assert [item["label"] for item in nli["items"]] == [
            "contradiction",
            "entailment",
            "neutral",
        ]
