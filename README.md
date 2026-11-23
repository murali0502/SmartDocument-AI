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

Open http://127.0.0.1:5173. The status screen checks the API and SQLite schema on load and when you select **Refresh checks**. The link in the header opens the generated API contract.

The backend listens on `127.0.0.1:8000` by default. The frontend forwards same-origin API requests to that backend.

## Ingest a document

Use the [ingestion API guide](docs/API_DOCUMENTATION.md#document-ingestion) to upload a file, check its job, and fetch the extraction. The API starts a local ingestion worker automatically. Install Tesseract with English language data to process scanned PDFs and images. Native documents use their format-specific parsers.

## Inspect document structure

The worker builds paginated structural elements and chunks after extraction. The [API guide](docs/API_DOCUMENTATION.md#document-structure-and-chunks) includes a PowerShell example that retrieves an exact source excerpt for a chunk.

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
