# SmartDoc AI project status

Updated 22 November 2026. Phase 0 architecture is approved. Phase 1 foundation is implemented and verified on Linux. Phase 2 is pending.

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

Windows and browsers beyond Chromium remain unverified. The GitHub Actions workflow is checked into the workspace and has not run on GitHub. Authentication, business-route authorization, file processing, NCM, retrieval, and production deployment remain future-phase work. The next phase is document ingestion, including validated uploads, durable jobs, parser adapters and fixture tests.
