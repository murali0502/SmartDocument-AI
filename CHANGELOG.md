# Changelog

## Phase 5 — NCM core

- Added source-verified concepts, conservative aliases, scoring, assertions and hierarchy.
- Added dependency and impact traversal with cited edges and cycle detection.
- Added immutable review revisions, evidence-backed snapshot comparison and a dedicated evaluation fixture.

## Phase 4 — Linguistic annotations

- Added durable, source-anchored lexical and optional trained English annotations.
- Added opt-in CPU embeddings and three-way NLI using pinned local ONNX artifacts.
- Added annotation APIs, migration and model tests, and a reproducible feasibility dataset.

## Phase 3 — Document structure and chunks

- Added stable structural nodes, page and section locators, and format-aware table and list hierarchy.
- Added bounded chunks with exact Unicode spans and separate overlap evidence.
- Added persisted structure snapshots, automatic backfill, and paginated structure and source APIs.

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
