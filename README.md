# SmartDoc AI

SmartDoc AI is a local-first project for source-grounded document intelligence. Next Concept Modelling (NCM) is its proposed approach to concept and relationship analysis. The application provides a local system status screen, a versioned FastAPI service, and a document ingestion API backed by SQLite.

## Start locally

### Windows PowerShell

Install Git, `uv` and Node.js 24 LTS. Then clone the project and start the backend.

```powershell
Set-Location $env:USERPROFILE
git clone https://github.com/murali0502/SmartDocument-AI.git
Set-Location .\SmartDocument-AI\backend
uv sync --locked
uv run --frozen alembic upgrade head
uv run --frozen python -m smartdoc
```

In a second PowerShell window, start the frontend.

```powershell
Set-Location "$env:USERPROFILE\SmartDocument-AI\frontend"
npm.cmd ci
npm.cmd run dev
```

### Linux or macOS

Install Python 3.12 through `uv` and use Node.js 24 LTS. From the project root, run the backend in one terminal.

```sh
cd backend
uv sync --locked
uv run --frozen alembic upgrade head
uv run --frozen python -m smartdoc
```

In a second terminal from the project root, start the frontend.

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173 to upload a document and ask a question after it is ready. Open **System status** for API and SQLite checks, or **API workspace** for the API contract.

The backend listens on `127.0.0.1:8000` by default. The frontend forwards same-origin API requests to that backend.

## Hosted deployment

The root `Dockerfile` packages the browser and API together. Deploy one instance behind HTTPS and mount a persistent volume at `/data`. Set `SMARTDOC_HOSTED_PASSWORD` to a randomly generated password of at least 24 ASCII characters. Sign in as `smartdoc` to upload documents and use **Ask SmartDoc**. Railway can use `/api/v1/health/ready` as its health check. The container applies database migrations on startup.

The hosted app uses a single shared workspace. Anyone with the password can access its documents and results. The volume stores the SQLite database and original uploads. Keep the same volume across deployments and back it up separately.

## Ingest a document

Use the [ingestion API guide](docs/API_DOCUMENTATION.md#document-ingestion) to upload a file, check its job, and fetch the extraction. The API starts a local ingestion worker automatically. Install Tesseract with English language data to process scanned PDFs and images. Native documents use their format-specific parsers.

## Inspect document structure

The worker builds paginated structural elements and chunks after extraction. The [API guide](docs/API_DOCUMENTATION.md#document-structure-and-chunks) includes a PowerShell example that retrieves an exact source excerpt for a chunk.

## Inspect linguistic annotations

Phase 4 automatically annotates structured chunks with the standard rules profile. The [NLP pipeline guide](docs/NLP_PIPELINE.md) explains the optional CPU models and [annotation routes](docs/API_DOCUMENTATION.md#linguistic-annotations).

## Inspect concepts and dependencies

Phase 5 builds concepts, aliases, hierarchy links and evidence-backed relationship candidates from completed NLP annotations. The [NCM API guide](docs/API_DOCUMENTATION.md#next-concept-modelling) covers snapshots, dependencies, revisions and comparisons.

## Explore the knowledge graph

Phase 6 publishes a collection graph with source-backed edges and immutable revisions. The [graph API guide](docs/API_DOCUMENTATION.md#knowledge-graph) covers neighborhood, path, evidence and analytics requests.

## Ask a question

Select a ready document and ask for a summary, definition, requirement, or dependency. Summaries select representative excerpts across the document and link each excerpt to its source. The first release quotes direct statements, such as “The pump requires a ceramic filter.” Open the citation to see the exact extracted text and its source location. If the question falls outside those patterns, the evidence disagrees, or no direct statement is found, the app reports insufficient evidence and may show related passages.

## Explore your documents

Use **Documents** to browse extracted passages and download originals. Use **Search** to find passages across uploads, **Concepts** to inspect definitions and mentions, **Knowledge graph** to browse evidence-backed relationships, or **Compare** to review concept differences between documents.

## Search the workspace

Use the [retrieval API](docs/RETRIEVAL.md) to find and verify source excerpts with BM25, document structure, concepts and graph relationships. Dense search is available with the optional local embedding model.

## Develop and verify

```sh
cd backend
uv run --frozen ruff check
uv run --frozen ruff format --check
uv run --frozen pytest
```

Build and verify the frontend in its own directory.

```sh
cd frontend
npm run build
npx playwright install chromium
npm run test:e2e
```

See [development setup](docs/DEVELOPMENT_GUIDE.md), [API contracts](docs/API_DOCUMENTATION.md), [architecture](docs/ARCHITECTURE.md), and [project status](PROJECT_STATUS.md).
