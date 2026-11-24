import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

import pytest
from alembic import command
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook
from openpyxl.worksheet.table import Table
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from smartdoc.app import create_app
from smartdoc.config import Settings
from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.ingestion.worker import IngestionWorker
from smartdoc.persistence import ingestion_store as storage

BASE = "/api/v1/workspaces/local"
HEADERS = {"Content-Type": "application/octet-stream", "X-SmartDoc-Upload": "1"}


@pytest.fixture
def local(migration, database):
    command.upgrade(migration, "head")
    app = create_app(
        Settings(database_path=database, ingestion_worker=False, max_upload_bytes=4_000_000)
    )
    worker = IngestionWorker(app.state.ingestion_store, app.state.database_readiness, 30)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        yield client, worker


def post(client, name, content, headers=HEADERS):
    return client.post(
        f"{BASE}/uploads", params={"filename": name}, content=content, headers=headers
    )


def fixtures(format: str) -> bytes:
    simple = {
        "txt": "Cooling system — café".encode("utf-16"),
        "md": b"# Cooling\n\n| Part | Role |\n| --- | --- |\n| Pump | Moves water |\n",
        "html": b"<h1>Cooling</h1><script>unsafe</script><table><tr><td>Pump</td></tr></table>",
        "csv": b'Part,Role\nPump,"Moves, water"\n',
        "json": b'{"part":"pump"}',
        "yaml": b"part: pump\n---\npart: filter\n",
    }
    if format in simple:
        return simple[format]

    output = io.BytesIO()
    if format == "pdf":
        canvas = Canvas(output)
        canvas.setTitle("Hydraulic reference")
        canvas.drawString(40, 780, "Cooling system")
        for x in (40, 140, 240):
            canvas.line(x, 650, x, 710)
        for y in (650, 680, 710):
            canvas.line(40, y, 240, y)
        for x, y, text in (
            (50, 690, "Part"),
            (150, 690, "Role"),
            (50, 660, "Pump"),
            (150, 660, "Moves water"),
        ):
            canvas.drawString(x, y, text)
        canvas.showPage()
        canvas.drawString(40, 780, "Filters")
        canvas.save()
    elif format == "docx":
        document = Document()
        document.core_properties.title = "Hydraulic reference"
        document.add_heading("Cooling", level=2)
        document.add_paragraph("Pump", style="List Bullet")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Part"
        table.cell(0, 1).text = "Pump"
        document.save(output)
    elif format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Cooling"
        sheet.append(["Part", "Pressure"])
        sheet.append(["Pump", "=SUM(2,3)"])
        sheet.add_table(Table(displayName="CoolingTable", ref="A1:B2"))
        workbook.create_sheet("Backup")
        workbook.save(output)
    elif format == "pptx":
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        slide.shapes.title.text = "Cooling"
        slide.notes_slide.notes_text_frame.text = "Check pressure."
        shape = slide.shapes.add_table(1, 1, Inches(1), Inches(1), Inches(2), Inches(1))
        shape.table.cell(0, 0).text = "Pump"
        presentation.save(output)
    else:
        raise ValueError(format)
    return output.getvalue()


@pytest.mark.parametrize(
    "format", ["pdf", "docx", "txt", "md", "html", "csv", "xlsx", "pptx", "yaml", "json"]
)
def test_formats(local, format):
    client, worker = local
    data = fixtures(format)
    response = post(client, f"reference.{format}", data)
    assert response.status_code == 202, response.text
    receipt = response.json()
    assert receipt["document"]["sha256"] == sha256(data).hexdigest()
    assert receipt["document"]["size_bytes"] == len(data)
    assert worker.store.original_path(sha256(data).hexdigest()).read_bytes() == data
    job_url = response.headers["Location"]
    result_url = f"{BASE}/documents/{receipt['document']['id']}/extraction"
    assert client.get(result_url).json()["code"] == "extraction_pending"
    assert worker.run_one()
    job = client.get(job_url).json()
    assert job["status"] == "succeeded", job.get("error_code")
    assert job["attempts"] == 1
    assert job["pipeline_version"] == "ingestion-v1"
    response = client.get(result_url)
    assert response.status_code == 200, response.text
    output = response.json()
    assert output["format"] == format
    assert output["parser_version"]
    assert output["metadata"]["isolation"] in {"bubblewrap", "process"}
    units = output["units"]

    if format == "pdf":
        assert [unit["locator"]["page"] for unit in units] == [1, 2]
        assert "Filters" in units[1]["text"]
        assert units[0]["data"]["tables"][0][1] == ["Pump", "Moves water"]
        assert all("ocr" not in unit["data"] for unit in units)
    elif format == "docx":
        assert output["metadata"]["title"] == "Hydraulic reference"
        assert [(u["kind"], u["locator"]["block"]) for u in units] == [
            ("heading", 1),
            ("list_item", 2),
            ("table", 3),
        ]
        assert units[0]["data"]["level"] == 2
        assert units[2]["data"]["rows"] == [["Part", "Pump"]]
    elif format == "txt":
        assert units[0]["text"] == "Cooling system — café"
        assert output["metadata"]["encoding"] == "utf-16"
    elif format == "md":
        assert units[1]["locator"]["line"] == 1
        assert units[1]["text"] == "Cooling"
        assert "Moves water" in units[2]["text"]
        assert units[2]["data"]["rows"][1] == ["Pump", "Moves water"]
    elif format == "html":
        assert "unsafe" not in units[0]["text"]
        assert units[1]["data"]["rows"] == [["Pump"]]
    elif format == "csv":
        assert units[0]["data"]["columns"] == ["Part", "Role"]
        assert units[0]["data"]["rows"][1] == {"row": 2, "cells": ["Pump", "Moves, water"]}
    elif format == "xlsx":
        assert [sheet["locator"]["sheet"] for sheet in units] == ["Cooling", "Backup"]
        formula = units[0]["data"]["rows"][1]["cells"][1]
        assert formula == {"cell": "B2", "column": 2, "type": "f", "value": "=SUM(2,3)"}
        assert units[0]["data"]["tables"] == [
            {"name": "CoolingTable", "range": "A1:B2", "columns": ["Part", "Pressure"]}
        ]
    elif format == "pptx":
        assert units[0]["text"] == "Cooling"
        assert "Check pressure." in units[0]["data"]["notes"]
        assert next(u for u in units if u["kind"] == "table")["data"]["rows"] == [["Pump"]]
    elif format == "yaml":
        assert output["metadata"]["documents"] == 2
    elif format == "json":
        assert output["metadata"]["root_type"] == "dict"


@pytest.mark.parametrize("format", ["pdf", "png", "jpeg", "tiff"])
def test_visual_upload_preserves_page_without_ocr(local, format):
    client, worker = local
    with Image.new("RGB", (1050, 270), "white") as image:
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=52)
        draw.text((35, 40), "Pump requires a filter", fill="black", font=font)
        draw.text((35, 125), "Operating pressure", fill="black", font=font)
        output = io.BytesIO()
        image.save(output, format=format.upper())
    response = post(client, f"scan.{format}", output.getvalue())
    assert response.status_code == 202, response.text
    assert worker.run_one()
    record = client.get(response.headers["Location"]).json()
    assert record["status"] == "succeeded", record.get("error_code")
    doc_id = response.json()["document"]["id"]
    unit = client.get(f"{BASE}/documents/{doc_id}/extraction").json()["units"][0]
    assert unit["locator"]["page"] == 1
    assert unit["text"] == ""
    assert unit["data"]["vision_scan"] is True
    assert "ocr" not in unit["data"]


def test_mixed_pdf_indexes_embedded_text_and_marks_image_page(local):
    client, worker = local
    output = io.BytesIO()
    canvas = Canvas(output)
    canvas.drawString(30, 780, "Native page")
    canvas.showPage()
    with Image.new("RGB", (1050, 270), "white") as image:
        draw = ImageDraw.Draw(image)
        draw.text(
            (35, 40), "Filter replacement", fill="black", font=ImageFont.load_default(size=60)
        )
        canvas.drawImage(ImageReader(image), 30, 550, width=500, height=130)
    canvas.save()
    response = post(client, "mixed.pdf", output.getvalue())
    assert response.status_code == 202
    assert worker.run_one()
    record = client.get(response.headers["Location"]).json()
    assert record["status"] == "succeeded", record.get("error_code")
    doc_id = response.json()["document"]["id"]
    first, second = client.get(f"{BASE}/documents/{doc_id}/extraction").json()["units"]
    assert first["text"] == "Native page"
    assert "ocr" not in first["data"]
    assert second["locator"]["page"] == 2
    assert second["text"] == ""
    assert second["data"]["vision_scan"] is True
    assert "ocr" not in second["data"]


def test_missing_vision_model_is_an_explicit_answer_failure(local):
    client, worker = local
    with Image.new("RGB", (50, 50), "white") as image:
        output = io.BytesIO()
        image.save(output, format="PNG")
    response = post(client, "scan.png", output.getvalue())
    assert response.status_code == 202
    assert worker.run_one()
    result = client.get(response.headers["Location"]).json()
    assert result["status"] == "succeeded"
    answer = client.post(
        f"{BASE}/ask",
        json={
            "document_id": response.json()["document"]["id"],
            "question": "What is shown?",
        },
    )
    assert answer.status_code == 503, answer.text
    assert answer.json()["code"] == "vision_unavailable"


def test_duplicate_requests_and_restart(local, database):
    client, worker = local
    payload = b"The pump requires a filter."
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(
            pool.map(lambda index: post(client, f"manual-{index}.txt", payload), range(4))
        )
    assert sorted(r.status_code for r in receipts) == [200, 200, 200, 202]
    doc_id = receipts[0].json()["document"]["id"]
    job_url = receipts[0].headers["Location"]
    assert {r.json()["document"]["id"] for r in receipts} == {doc_id}

    restarted = create_app(Settings(database_path=database, ingestion_worker=False))
    resumed = IngestionWorker(
        restarted.state.ingestion_store, restarted.state.database_readiness, 30
    )
    assert resumed.run_one()
    assert not worker.run_one()
    with TestClient(restarted, base_url="http://localhost", client=("127.0.0.1", 50000)) as second:
        assert second.get(job_url).json()["status"] == "succeeded"
        assert (
            second.get(f"{BASE}/documents/{doc_id}/extraction").json()["units"][0]["text"]
            == payload.decode()
        )


def test_worker_recovers_expired_attempt_and_rejects_stale_claim(local, monkeypatch):
    client, worker = local
    response = post(client, "notes.txt", b"Pump")
    claim = worker.store.claim(30)
    assert claim is not None
    future = storage.now() + timedelta(seconds=35)
    monkeypatch.setattr(storage, "now", lambda: future)
    assert worker.run_one()
    assert not worker.store.finish(claim, ExtractionError("old_worker", "Old worker."))
    job = client.get(response.headers["Location"]).json()
    assert (job["status"], job["attempts"]) == ("succeeded", 2)


def test_malformed_and_unsafe_files_are_reported(local):
    client, worker = local
    archive_bytes = io.BytesIO()
    with ZipFile(archive_bytes, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", b"<!DOCTYPE test><document/>")
    for filename, data, code in [
        ("broken.json", b'{"part": ', "malformed_document"),
        ("bad.docx", archive_bytes.getvalue(), "unsafe_xml"),
        ("broken.pdf", b"%PDF-1.7\ntruncated", "malformed_document"),
    ]:
        response = post(client, filename, data)
        assert response.status_code == 202
        assert worker.run_one()
        record = client.get(response.headers["Location"]).json()
        assert record["status"] == "failed", record
        assert record["error_code"] == code
        doc = response.json()["document"]["id"]
        assert (
            client.get(f"{BASE}/documents/{doc}/extraction").json()["code"] == "extraction_failed"
        )


def test_rejects_wrong_type_traversal_size_and_cross_origin(local, database):
    client, _worker = local
    for name, content, status in [
        ("../notes.txt", b"notes", 400),
        ("plan.exe", b"notes", 415),
        ("broken.pdf", b"ordinary text", 415),
        ("empty.txt", b"", 400),
        ("huge.txt", b"x" * (4_000_000 + 1), 413),
    ]:
        assert post(client, name, content).status_code == status
    stream = (b"x" * 2_000_000 for _ in range(3))
    assert post(client, "stream.txt", stream).status_code == 413
    assert (
        post(client, "notes.txt", b"text", {"Content-Type": "application/octet-stream"}).status_code
        == 403
    )
    assert (
        post(
            client, "notes.txt", b"text", {**HEADERS, "Origin": "https://other.example"}
        ).status_code
        == 403
    )
    assert not list(database.parent.glob("*.storage/.staging/*"))
    assert client.get(f"{BASE}/documents").json() == {"items": [], "next_cursor": None}


def test_documents_paginate(local):
    client, _worker = local
    for index in range(3):
        assert post(client, f"{index}.txt", bytes([index + 32])).status_code == 202
    first = client.get(f"{BASE}/documents", params={"limit": 2}).json()
    assert len(first["items"]) == 2
    second = client.get(
        f"{BASE}/documents", params={"limit": 2, "after": first["next_cursor"]}
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None


def test_lifespan_worker_processes_real_upload(migration, database: Path):
    import time

    command.upgrade(migration, "head")
    app = create_app(Settings(database_path=database, processing_timeout=30))
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        response = post(client, "startup.txt", b"Startup checklist")
        assert response.status_code == 202, response.text
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = client.get(response.headers["Location"]).json()
            if result["status"] in {"succeeded", "failed"}:
                assert result["status"] == "succeeded", result
                break
            time.sleep(0.05)
        else:
            pytest.fail("The background worker did not finish before the deadline.")


def test_process_fallback_without_bubblewrap(local, monkeypatch):
    monkeypatch.setattr("smartdoc.ingestion.worker.shutil.which", lambda _: None)
    client, worker = local
    response = post(client, "fallback.txt", b"Fallback process text")
    assert response.status_code == 202
    assert worker.run_one()
    job = client.get(response.headers["Location"]).json()
    assert job["status"] == "succeeded", job.get("error_code")
    doc_id = response.json()["document"]["id"]
    extraction = client.get(f"{BASE}/documents/{doc_id}/extraction").json()
    assert extraction["metadata"]["isolation"] == "process"
    assert extraction["units"][0]["text"] == "Fallback process text"
