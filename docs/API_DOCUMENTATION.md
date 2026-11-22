# API documentation

The available prefix is `/api/v1`. OpenAPI is served at `/api/v1/openapi.json`. The optional Swagger UI at `/api/v1/docs` uses FastAPI's default third-party static assets.

| Method and path | Response |
|---|---|
| `GET /api/v1/health/live` | HTTP 200 with `status: alive` when the API process is serving requests. |
| `GET /api/v1/health/ready` | HTTP 200 with `status: ready` when SQLite is accessible at the expected migration heads with the required tables. HTTP 503 otherwise, with `status: unavailable` and a database code. |
| `GET /api/v1/openapi.json` | The live OpenAPI contract used for client type generation. |

Readiness includes `database` (`ready`, `missing`, `migration_required`, or `unavailable`) and `checked_at` in UTC. Both health responses set `Cache-Control: no-store`. Every handled response carries an `X-Request-ID` header.

Errors use `application/problem+json` with `type`, `title`, `status`, `code`, `detail` and `request_id`. Readiness HTTP 503 returns the documented readiness payload so monitoring clients can interpret the service state.


## Document ingestion

These routes are scoped to the local workspace under `/api/v1/workspaces/local`.

| Method and path | Behavior |
|---|---|
| `POST /uploads?filename=...` | Body is the raw file with `Content-Type: application/octet-stream` and `X-SmartDoc-Upload: 1`. Returns 202 for new content or 200 for a workspace duplicate. The `Location` header points to the job. |
| `GET /documents?limit=25&after=...` | Lists documents and jobs. Continue via `next_cursor` until it is null. |
| `GET /jobs/{job_id}` | Returns queued, running, succeeded or failed status, attempt count, UTC timestamps and a failure code and message when applicable. |
| `GET /documents/{document_id}/extraction` | Returns the parser name and version, metadata, source units and warnings. A pending or failed extraction returns a specific 409 problem response. |

### Upload from PowerShell

Start the migrated API as described in the README. Replace the example file path with a file on your computer.

```powershell
$file = "C:\Users\yourname\Documents\sample.pdf"
$api = "http://127.0.0.1:8000/api/v1/workspaces/local"
$name = [Uri]::EscapeDataString([IO.Path]::GetFileName($file))
$uri = "$api/uploads?filename=$name"
$headers = @{"X-SmartDoc-Upload"="1"}
$upload = Invoke-RestMethod -Method Post -Uri $uri -InFile $file -ContentType "application/octet-stream" -Headers $headers
Invoke-RestMethod -Uri "$api/jobs/$($upload.job.id)"
```

Once the job reports `succeeded`, fetch its extraction.

```powershell
Invoke-RestMethod -Uri "$api/documents/$($upload.document.id)/extraction" |
  ConvertTo-Json -Depth 20
```

The receipt records filename, format, byte length and SHA-256. Locators use one-based page, slide, block and CSV row indices. Workbook cells use A1 references. PDF page sizes use points. OCR word boxes use raster pixels with a top-left origin and carry confidence and engine version. Native page text remains in `text`. OCR is in `data.ocr`. The extraction metadata records whether Bubblewrap or a standalone process isolated the parser.
