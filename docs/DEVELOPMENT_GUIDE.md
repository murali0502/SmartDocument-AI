# Development guide

The setup uses `uv.lock` and `package-lock.json`. Run the API and Alembic from the backend directory so they agree on the default database path. `SMARTDOC_DATABASE_PATH` may be an absolute path for alternate working directories.

| Environment variable | Default |
|---|---|
| `SMARTDOC_DATABASE_PATH` | `.local/smartdoc.sqlite3` relative to the backend working directory |
| `SMARTDOC_STORAGE_PATH` | Directory next to the selected database, with a `.storage` suffix |
| `SMARTDOC_MAX_UPLOAD_BYTES` | `20971520` (20 MiB) |
| `SMARTDOC_PROCESSING_TIMEOUT` | `90` seconds per document |
| `SMARTDOC_INGESTION_WORKER` | `true` |
| `SMARTDOC_TESSERACT` | `tesseract` on PATH |
| `SMARTDOC_HOST` | `127.0.0.1` |
| `SMARTDOC_PORT` | `8000` |
| `SMARTDOC_LOG_LEVEL` | `INFO` |
| `SMARTDOC_API_ORIGIN` | `http://127.0.0.1:8000`, read by Vite |
| `SMARTDOC_TEST_CHROMIUM` | Unset, Playwright uses its managed Chromium |

Run `uv run --frozen alembic current` from the backend to inspect the schema revision. `uv run --frozen alembic check` compares the migrated database to model metadata. The downgrade command is exercised with a disposable test database because the initial revision drops its data tables.

Regenerate the frontend API types from the project root after a contract change.

```sh
uv run --project backend --frozen python scripts/export_openapi.py
cd frontend
npm run contracts
```

The browser test uses a disposable SQLite file in Playwright's output directory and loopback ports 18080 and 14173. Start it after a frontend build. On Linux, install browser system dependencies with `npx playwright install --with-deps chromium` if needed.

For scans and image files, install Tesseract with English language data. If it is outside PATH on Windows, set `$env:SMARTDOC_TESSERACT` to the executable path before starting the API. Linux uses Bubblewrap automatically when available. Other development hosts use a separate parser subprocess.

The lockfiles are suitable for fresh installation on supported Python and Node versions. Linux was used for Phase 1 and Phase 2 execution. Windows operation requires its own verification.
