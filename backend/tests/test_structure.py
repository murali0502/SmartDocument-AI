import io
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_ingestion import fixtures, post

from smartdoc.app import create_app
from smartdoc.chunking.partition import ChunkPolicy
from smartdoc.config import Settings
from smartdoc.ingestion.contracts import Extraction, ExtractionError, SourceUnit
from smartdoc.ingestion.extract import extract
from smartdoc.persistence.database import create_database_engine
from smartdoc.persistence.ingestion_models import (
    LOCAL_WORKSPACE_ID,
    Document,
    IngestionJob,
    IngestionResult,
)
from smartdoc.persistence.structure_models import DocumentChunk
from smartdoc.structure.builder import build_structure
from smartdoc.structure.contracts import SourceSpan, resolve_span

BASE = "/api/v1/workspaces/local"


def test_multiple_fragments_have_distinct_exact_unicode_offsets_and_overlap():
    body = "The café sensor uses ΔT and 🌡️. Operate at 12 °C. " * 20
    original = "\r\n# Safety\r\n\r\n" + body.rstrip() + "\r\n\r\nEnd."
    extraction = Extraction(
        format="txt",
        parser="fixture",
        parser_version="1",
        units=[SourceUnit(kind="document", text=original)],
    )
    document_id, job_id = uuid4(), uuid4()
    policy = ChunkPolicy(max_tokens=13, max_characters=80, overlap_tokens=4, overlap_characters=25)
    created = datetime.now(UTC)
    built = build_structure(document_id, job_id, extraction, created, policy)
    repeated = build_structure(document_id, job_id, extraction, created, policy)
    assert built == repeated
    assert len({element.id for element in built.elements}) == len(built.elements)
    assert len({chunk.id for chunk in built.chunks}) == len(built.chunks)
    element = next(
        row for row in built.elements if row.kind == "paragraph" and row.source.start > 10
    )
    chunks = [chunk for chunk in built.chunks if chunk.parent_element_id == element.id]
    assert len(chunks) > 5
    assert chunks[0].primary.start == original.index("The café")
    assert "".join(chunk.text for chunk in chunks) == body.rstrip()
    assert chunks[0].overlap == []
    for index, chunk in enumerate(chunks):
        assert resolve_span(extraction, chunk.primary) == chunk.text
        assert chunk.character_count == len(chunk.text) <= policy.max_characters
        assert chunk.token_count <= policy.max_tokens
        assert chunk.section_path[-1].title == "Safety"
        if index:
            assert chunks[index - 1].primary.end == chunk.primary.start
            assert chunk.overlap, index
            assert all(resolve_span(extraction, item.source) == item.text for item in chunk.overlap)
            assert chunk.overlap[0].source.end == chunk.primary.start
            assert chunk.overlap[0].source.start >= chunks[index - 1].primary.start
    assert [node.kind for node in built.elements].count("sentence") >= 40


def test_offsets_reject_bad_field_bounds_and_false_scalar_projection():
    extraction = Extraction(
        format="txt",
        parser="fixture",
        parser_version="1",
        units=[SourceUnit(kind="document", text="🛠️ Pump")],
    )
    for span in (
        SourceSpan(unit=1, field=("text",), start=0, end=20),
        SourceSpan(unit=1, field=("text",), start=4, end=2),
        SourceSpan(unit=2, field=("text",), start=0, end=1),
        SourceSpan(unit=1, field=("data", "bogus"), start=0, end=1),
        SourceSpan(unit=1, field=("text", 0), start=0, end=1),
        SourceSpan(unit=1, field=("text",), start=0, end=1, projection="json_scalar"),
    ):
        with pytest.raises(ExtractionError, match="recorded source"):
            resolve_span(extraction, span)


def test_oversized_code_tokens_and_newlines_keep_exact_primary_spans():
    body = "aaaaaaaaaaaaaaaaaaaaaaaaaaa\nβ = c\r\nlast\n"
    extraction = Extraction(
        format="md",
        parser="fixture",
        parser_version="1",
        units=[SourceUnit(kind="document", text="\n\n```python\r\n" + body + "```\r\n")],
    )
    built = build_structure(
        uuid4(), uuid4(), extraction, datetime.now(UTC), ChunkPolicy(max_tokens=4, max_characters=9)
    )
    code = next(element for element in built.elements if element.kind == "code_block")
    assert len(built.chunks) > 4
    assert all(
        chunk.strategy == "line-first-v1" and chunk.character_count <= 9 for chunk in built.chunks
    )
    assert all(resolve_span(extraction, chunk.primary) == chunk.text for chunk in built.chunks)
    assert "".join(chunk.text for chunk in built.chunks) == resolve_span(extraction, code.source)
    assert "\r\n" in resolve_span(extraction, code.source)


def rendered(tmp_path: Path, format: str, content: bytes) -> tuple[Extraction, object]:
    path = tmp_path / ("fixture." + format)
    path.write_bytes(content)
    manifest = extract(path, format)
    return manifest, build_structure(uuid4(), uuid4(), manifest, datetime.now(UTC))


def test_markdown_nested_sections_lists_math_and_exact_table_anchors(tmp_path):
    original = (
        "# System\r\n\r\n## Hydraulics\r\n\r\n"
        "- Pump\r\n  - Impeller\r\n- Valve\r\n\r\n"
        "| Part | Rating |\r\n| --- | --- |\r\n| Filter | 100 μm |\r\n\r\n"
        "```math\r\nΔT = T₁ − T₀\r\n```\r\n\r\n"
        "![Pump diagram](diagram.png)\r\n\r\nFigure 1. Pump diagram.\r\n\r\n"
        "[^tip]: Clean the filter.\r\n\r\n[1] Technical handbook.\r\n\r\n"
        "## Controls\r\n\r\nKeep the sensor dry.\r\n"
    )
    extraction, constructed = rendered(tmp_path, "md", original.encode())
    elements = {element.id: element for element in constructed.elements}
    kinds = {element.kind for element in constructed.elements}
    assert {
        "figure",
        "caption",
        "math_expression",
        "footnote",
        "reference",
        "list",
        "list_item",
        "table",
        "table_row",
        "table_cell",
        "section",
    } <= kinds
    items = [chunk for chunk in constructed.chunks if chunk.element_type == "list_item"]
    assert [item.text for item in items] == ["- Pump", "- Impeller", "- Valve"]
    inner_list = elements[elements[items[1].parent_element_id].parent_id]
    assert inner_list.parent_id == items[0].parent_element_id
    table = next(chunk for chunk in constructed.chunks if chunk.text == "100 μm")
    assert table.element_type == "table_cell"
    assert table.locator["row"] == 2 and table.locator["column"] == 2
    assert [section.title for section in table.section_path] == ["System", "Hydraulics"]
    assert resolve_span(extraction, table.primary) == table.text
    assert all(
        resolve_span(extraction, chunk.primary) == chunk.text for chunk in constructed.chunks
    )


@pytest.mark.parametrize("format", ["docx", "html", "csv", "xlsx", "pptx"])
def test_office_and_tabular_sources_keep_native_coordinates(tmp_path, format):
    manifest, constructed = rendered(tmp_path, format, fixtures(format))
    assert constructed.chunks
    assert all(resolve_span(manifest, chunk.primary) == chunk.text for chunk in constructed.chunks)
    cells = [chunk for chunk in constructed.chunks if chunk.element_type == "table_cell"]
    assert cells
    if format == "pptx":
        assert [chunk.text for chunk in constructed.chunks].count("Cooling") == 1
        assert all(chunk.locator["slide"] == 1 for chunk in constructed.chunks)
        assert any(chunk.locator.get("layer") == "notes" for chunk in constructed.chunks)
    elif format == "xlsx":
        formula = next(chunk for chunk in cells if chunk.text == "=SUM(2,3)")
        assert formula.locator["sheet"] == "Cooling"
        assert formula.locator["cell"] == "B2"
        assert formula.locator["range"] == "A1:B2"
    elif format == "html":
        assert cells[0].section_path[-1].title == "Cooling"
    elif format == "docx":
        assert cells[0].section_path[-1].title == "Cooling"


def test_pdf_layout_identifies_heading_and_table_section(tmp_path):
    data = io.BytesIO()
    canvas = Canvas(data)
    canvas.setFont("Helvetica-Bold", 22)
    canvas.drawString(30, 780, "Hydraulic System")
    canvas.setFont("Helvetica", 11)
    canvas.drawString(30, 740, "The centrifugal pump circulates coolant.")
    for x in (30, 140, 240):
        canvas.line(x, 635, x, 710)
    for y in (635, 670, 710):
        canvas.line(30, y, 240, y)
    canvas.drawString(40, 685, "Component")
    canvas.drawString(150, 685, "Material")
    canvas.drawString(40, 650, "Impeller")
    canvas.drawString(150, 650, "Stainless steel")
    canvas.setFont("Helvetica-Bold", 21)
    canvas.drawString(30, 600, "Electrical Controls")
    canvas.setFont("Helvetica", 11)
    canvas.drawString(30, 570, "Keep the sensor dry and check the wiring.")
    canvas.showPage()
    canvas.drawString(30, 760, "A replacement sensor must match the device specification.")
    canvas.save()
    manifest, constructed = rendered(tmp_path, "pdf", data.getvalue())
    assert [
        element.locator["page"] for element in constructed.elements if element.kind == "page"
    ] == [1, 2]
    cell = next(chunk for chunk in constructed.chunks if chunk.text == "Stainless steel")
    assert cell.locator == {"page": 1, "table": 1, "row": 2, "column": 2}
    assert cell.section_path[-1].title == "Hydraulic System"
    assert sum("Stainless steel" in chunk.text for chunk in constructed.chunks) == 1
    last = constructed.chunks[-1]
    assert last.locator["page"] == 2 and last.section_path[-1].title == "Electrical Controls"
    assert all(resolve_span(manifest, chunk.primary) == chunk.text for chunk in constructed.chunks)


def test_numeric_cells_explicitly_anchor_json_and_ocr_uses_its_own_field():
    extraction = Extraction(
        format="pdf",
        parser="fixture",
        parser_version="1",
        units=[
            SourceUnit(
                kind="page",
                locator={"page": 1},
                data={
                    "ocr": {"text": "Pump requires a filter."},
                    "tables": [[[12], [False]]],
                },
            ),
        ],
    )
    built = build_structure(uuid4(), uuid4(), extraction, datetime.now(UTC))
    ocr, number, boolean = built.chunks
    assert ocr.locator == {"page": 1, "layer": "ocr"}
    assert ocr.primary.field == ("data", "ocr", "text")
    assert number.primary.projection == boolean.primary.projection == "json_scalar"
    assert resolve_span(extraction, number.primary) == "12"
    assert resolve_span(extraction, boolean.primary) == "false"


def test_phase_two_database_backfills_and_round_trips_through_api(database, migration):
    command.upgrade(migration, "0002_document_ingestion")
    doc_id, job_id = str(uuid4()), str(uuid4())
    created = datetime.now(UTC).replace(tzinfo=None)
    data = {
        "format": "txt",
        "parser": "python-stdlib",
        "parser_version": "1",
        "units": [{"kind": "document", "text": "Alpha. Beta. " * 200}],
    }
    engine = create_database_engine(database)
    with Session(engine) as session, session.begin():
        session.add(
            Document(
                id=doc_id,
                workspace_id=LOCAL_WORKSPACE_ID,
                filename="manual.txt",
                format="txt",
                sha256="a" * 64,
                size_bytes=2600,
                created_at=created,
            )
        )
        session.flush()
        session.add(
            IngestionJob(
                id=job_id,
                document_id=doc_id,
                status="succeeded",
                attempts=1,
                created_at=created,
                pipeline_version="ingestion-v1",
            )
        )
        session.flush()
        session.add(IngestionResult(job_id=job_id, extraction=data))
    command.upgrade(migration, "head")
    command.check(migration)
    app = create_app(Settings(database_path=database, ingestion_worker=False))
    location = f"{BASE}/documents/{doc_id}"
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get(location + "/structure").json()["status"] == "pending"
        assert client.get(location + "/chunks").json()["code"] == "structure_pending"
        assert app.state.structure_store.build_next()
        assert not app.state.structure_store.build_next()
        ready = client.get(location + "/structure").json()
        assert ready["status"] == "ready" and ready["chunk_count"] > 1
        chunks = client.get(location + "/chunks", params={"limit": 1}).json()
        cursor = chunks["next_cursor"]
        first = chunks["items"][0]
        second = client.get(location + "/chunks", params={"after": cursor}).json()["items"][0]
        assert second["id"] != first["id"]
        assert client.get(location + "/elements").json()["items"][0]["kind"] == "document"
        assert (
            client.get(location + "/extraction").json()["units"][0]["text"]
            == data["units"][0]["text"]
        )

    restarted = create_app(Settings(database_path=database, ingestion_worker=False))
    with TestClient(restarted, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        proof_url = location + "/chunks/" + second["id"] + "/source"
        proof = client.get(proof_url).json()
        assert proof["primary"]["text"] == second["text"]
        assert proof["overlap"] == second["overlap"]
        assert (
            client.get(f"{BASE}/documents/{uuid4()}/chunks/{second['id']}/source").status_code
            == 404
        )
        with Session(engine) as session, session.begin():
            row = session.scalar(select(DocumentChunk).where(DocumentChunk.id == second["id"]))
            row.payload = {**row.payload, "text": "not present in the extraction"}
        response = client.get(proof_url)
        assert (response.status_code, response.json()["code"]) == (409, "invalid_provenance")
    engine.dispose()


def test_running_worker_publishes_new_upload_structure(database, migration):
    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        upload = post(client, "manual.md", b"# Inspection\n\nCheck the main valve.\n")
        assert upload.status_code == 202
        document = UUID(upload.json()["document"]["id"])
        location = f"{BASE}/documents/{document}"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = client.get(location + "/structure").json()
            if result["status"] != "pending":
                assert result["status"] == "ready", result
                break
            time.sleep(0.05)
        else:
            pytest.fail("The running worker did not publish structure.")
        chunks = client.get(location + "/chunks").json()["items"]
        chunk = next(item for item in chunks if item["text"] == "Check the main valve.")
        assert chunk["section_path"][0]["title"] == "Inspection"
        response = client.get(location + f"/chunks/{chunk['id']}/source")
        assert response.json()["primary"]["text"] == "Check the main valve."
