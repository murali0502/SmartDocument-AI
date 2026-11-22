# SmartDoc AI project status

Updated 22 November 2026. The Phase 0 architecture is approved. Phases 1 and 2 are implemented and verified on Linux. Phase 3 is pending.

## Phase 1 implementation report

### Features and decisions

- FastAPI app factory and launcher, environment settings, OpenAPI, real liveness and SQLite readiness, problem responses, structured logs and request correlation.
- SQLite WAL and foreign-key enforcement with the first Alembic revision for users, workspaces and membership roles. Readiness uses a read-only connection and requires the expected revision and tables.
- Local React and TypeScript status screen, same-origin Vite proxy, generated OpenAPI types, real service refresh, and desktop and mobile layout.
- Locked dependencies, Ruff, pytest, Chromium Playwright, and a GitHub Actions workflow.

### Files and dependencies

An empty Git repository was initialized. Added the backend runtime, migrations and tests under `backend/`, the web UI, contracts and browser test under `frontend/`, the export tool under `scripts/`, and the CI workflow under `.github/`. Created README, changelog, project status, plus overview, API, security, development, testing and limitations documents. Carried the Phase 0 architecture, NCM, data, model, roadmap and risk documentation into `docs/`. Updated the project copies of the architecture and data model to reflect approval and implementation. Phase 0 scratch files remain unchanged.

Direct application dependencies are FastAPI, Alembic, SQLAlchemy, Pydantic Settings, Uvicorn, React and React DOM. Development dependencies cover Ruff, pytest, httpx2, TypeScript, Vite, frontend typings, Playwright and the OpenAPI generator. The Python and npm lockfiles record the resolved versions.

### Commands and observed results

| Check | Command | Result |
|---|---|---|
| Reproducible install | `uv sync --locked`, `npm ci` in a clean copy | Both completed. |
| Python quality and tests | `uv run --frozen ruff check`, `uv run --frozen ruff format --check`, `uv run --frozen pytest -q` | Ruff passed and 9 tests passed. |
| Schema | `uv run --frozen alembic upgrade head`, `alembic current`, `alembic check` | Reached `0001_workspace_foundation` with no schema drift. A test also verified downgrade and upgrade. |
| Frontend contract and build | `uv run --project backend --frozen python scripts/export_openapi.py`, `npm run contracts`, `npm run build` | Rebuilt the generated file byte for byte. TypeScript and Vite passed. |
| Browser integration | `SMARTDOC_TEST_CHROMIUM=/usr/bin/chromium npm run test:e2e` | 1 test passed. The UI observed HTTP 503 before migration and HTTP 200 after migration. Refresh, mobile layout and OpenAPI navigation passed. |
| Dependency advisories | `npm audit --audit-level=moderate`, `pip-audit` on the locked Python runtime export | Both scans reported zero known vulnerabilities. |
| Development entry points | `uv run --frozen python -m smartdoc`, `npm run dev`, loopback HTTP checks | The frontend, direct backend readiness, and proxied readiness returned HTTP 200. |

### Performance and security observations

The clean browser run logged the two post-migration readiness requests at 8.38 ms and 8.64 ms server-side. The built JavaScript was about 71 kB gzip. These are single-environment observations. The API default binds to loopback, the readiness response omits internal diagnostics, and tests verified request-ID correlation and removal of sensitive values from error responses and access logs.

### Incomplete and upcoming

Windows and browsers beyond Chromium remain unverified. The Phase 1 GitHub Actions run passed on Linux. At the Phase 1 exit, authentication, file processing, NCM, retrieval, and production deployment were still scheduled for later phases. The next phase is document ingestion, including validated uploads, durable jobs, parser adapters and fixture tests.

## Phase 2 implementation report

### Features and decisions

- Added streamed local uploads, filename and signature validation, SHA-256, workspace-scoped deduplication and managed original storage.
- Added revision `0002_document_ingestion` with document, job and extraction tables. Durable leases recover interrupted claims and fence stale writers. Successful job state and its extraction publish in one transaction.
- Implemented PDF, DOCX, TXT, Markdown, HTML, CSV, XLSX, PPTX, JSON, YAML, PNG, JPEG and TIFF. Retained page, slide, table, block and spreadsheet locators where available. English Tesseract preserves text, confidence and boxes in a separate OCR layer.
- Used a single background worker started by the API. Parsing runs in a bounded subprocess, with Bubblewrap on supported Linux hosts. The browser continues to provide system status. Uploads and extraction review use the local API in this phase.

### Files and dependencies

Created `backend/migrations/versions/0002_document_ingestion.py`, the ingestion routes, upload application service, parser package and worker, persistence models and store, and `backend/tests/test_ingestion.py`. Updated the API launcher/configuration, migration registration, generated frontend contract, CI, lockfile, README, changelog, and API, development, data model, security, testing, overview and limitations documentation.

Added pdfplumber, PDFium bindings, Pillow, python-docx, openpyxl, python-pptx, markdown-it-py, PyYAML and defusedxml. ReportLab builds test PDF fixtures. Tesseract and its English data are system dependencies for OCR. The advisory scan prompted an upgrade from Pillow 12.3.0 to 13.0.0.

### Commands and observed results

| Check | Commands | Result |
|---|---|---|
| Backend and extraction | `uv sync`, `uv run --frozen ruff check`, `ruff format --check`, `uv run --frozen pytest -q` | Ruff passed. 31 backend tests passed, including per-format extraction, real OCR, validation, concurrency and restart checks. |
| Migration and live API | `alembic upgrade 0001_workspace_foundation`, `alembic upgrade head`, `alembic check` and temporary Uvicorn HTTP probe | A database at Phase 1 upgraded with no ORM drift. The live API processed native and scanned PDFs, deduplicated repeats and retained both results after server restart. |
| Frontend regression | OpenAPI export, `npm run contracts`, `npm run build` and `npm run test:e2e` with Chromium | Build and browser status regression passed. |
| Dependency advisory check | `uv export` of locked runtime packages, then `uvx pip-audit` | The rescan after updating Pillow found zero known advisories. |

### Performance and security observations

A local HTTP smoke run took approximately 1.75 seconds for a two-page native PDF and 1.92 seconds for a one-page scanned PDF, including queue polling. Both ran through Bubblewrap. These are individual development fixtures, measured before the Pillow dependency update. Upload limits, traversal rejection, disallowed Office XML and cross-origin behavior are exercised in tests. Windows and production isolation remain unverified.

### Incomplete and upcoming

Legacy DOC, production access controls, browser document workflows, user-triggered reprocessing, and broad OCR accuracy evaluation remain open. Phase 3 should add stable structural IDs, source-offset maps and structure-aware chunking with exact provenance tests.
