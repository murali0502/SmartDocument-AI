import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread
from time import monotonic, sleep

import pytest
from alembic import command
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from test_ingestion import post

from smartdoc.app import create_app
from smartdoc.config import Settings

BASE = "/api/v1/workspaces/local"


@pytest.mark.parametrize("format", ["pdf", "tiff"])
def test_scans_use_vision_without_ocr_and_link_to_original_page(database, migration, format):
    captured = []

    class ModelHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            page = 2 if len(captured) == 1 else 3
            result = {
                "answer": "A test page.",
                "evidence": [{"page": page, "excerpt": "Test page"}],
            }
            response = json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(response.encode())

    command.upgrade(migration, "head")
    source = BytesIO()
    with (
        Image.new("RGB", (56, 84), color="white") as first,
        Image.new("RGB", (56, 84), color="black") as second,
    ):
        if format == "pdf":
            canvas = Canvas(source)
            for image in (first, second):
                canvas.drawImage(ImageReader(image), 35, 680, 56, 84)
                canvas.showPage()
            canvas.save()
        else:
            first.save(source, format="TIFF", save_all=True, append_images=[second])
    with ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = Settings(
                database_path=database,
                vision_url=f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                vision_model="fixture",
            )
            app = create_app(settings)
            with TestClient(
                app, base_url="http://localhost", client=("127.0.0.1", 50000)
            ) as client:
                receipt = post(client, f"scanned.{format}", source.getvalue())
                assert receipt.status_code == 202, receipt.text
                document = receipt.json()["document"]["id"]
                deadline = monotonic() + 12
                while (
                    client.get(f"{BASE}/documents/{document}/structure").json()["status"] != "ready"
                ):
                    assert monotonic() < deadline
                    sleep(0.1)
                extraction = client.get(f"{BASE}/documents/{document}/extraction").json()
                assert all(
                    unit["data"]["vision_scan"] and "ocr" not in unit["data"]
                    for unit in extraction["units"]
                )
                answer = client.post(
                    f"{BASE}/ask", json={"document_id": document, "question": "What is visible?"}
                )
                assert answer.status_code == 200, answer.text
                citation = answer.json()["visual_citations"][0]
                assert citation["page"] == 2
                image = client.get(citation["image_url"])
                assert image.headers["content-type"] == "image/jpeg"
                assert image.content[:2] == b"\xff\xd8"
                assert client.get(citation["image_url"].rsplit("/", 1)[0] + "/3").status_code == 404
                parts = captured[0]["messages"][1]["content"]
                assert [part["text"] for part in parts if "text" in part] == [
                    "What is visible?",
                    "Original page 1",
                    "Original page 2",
                ]
                assert sum(part["type"] == "image_url" for part in parts) == 2
                unsupported = client.post(
                    f"{BASE}/ask", json={"document_id": document, "question": "What is visible?"}
                ).json()
                assert unsupported["status"] == "insufficient_evidence"
                assert unsupported["visual_citations"] == []

        finally:
            server.shutdown()
            thread.join()
