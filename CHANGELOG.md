# Changelog

## Phase 2 — Document ingestion

- Added streamed uploads, checksums, workspace deduplication, durable jobs and persisted extraction manifests.
- Added native document parsers and Tesseract OCR for scan-only PDF pages and supported image files.
- Added format, input validation, restart recovery and concurrent upload tests.

## 0.1.0 — Phase 1 foundation

- Added a local React status screen and a versioned FastAPI health and OpenAPI contract.
- Added locked development dependencies, structured request logging, and problem responses.
- Added SQLite WAL setup, the workspace schema, and Alembic migration and rollback.
- Added backend tests, a browser integration test, and a CI workflow.

## Phase 0

- Documented the approved architecture and ran PDF, OCR, FTS5, and quantized embedding feasibility probes.
