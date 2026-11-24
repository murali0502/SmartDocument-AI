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

The receipt records filename, format, byte length and SHA-256. Locators use one-based page, slide, block and CSV row indices. Workbook cells use A1 references. PDF page sizes use points. Native page text stays in `text`. Scanned PDF pages and image frames are marked by `data.vision_scan`. Ask SmartDoc returns visual citations that link to authenticated page images. Older extraction records may contain `data.ocr` for existing citations. The extraction metadata records whether Bubblewrap or a standalone process isolated the parser.

## Document structure and chunks

Use the `document.id` returned by the upload. The paths below are relative to `/api/v1/workspaces/local/documents/{document_id}`.

| Method and path | Behavior |
|---|---|
| `GET /structure` | Returns `pending`, `ready`, or `failed`, with a version and counts after a completed build. |
| `GET /elements?limit=25&after=0` | Lists ordered logical elements, their parent IDs, and available anchors and locators. |
| `GET /chunks?limit=25&after=0` | Lists ordered chunks, their primary evidence, separate overlap, section paths and physical locators. |
| `GET /chunks/{chunk_id}/source` | Reopens the saved extraction fields and returns verified excerpts with their spans. A mismatch returns `409 invalid_provenance`. |

Element and chunk pages use the last returned ordinal as `next_cursor`. Data is available once structure status is `ready`. A pending or failed build returns a specific 409 from the data routes. See [the chunking contract](STRUCTURE_AND_CHUNKING.md) for offset units and rules.

### Check a chunk in PowerShell

After uploading with the example above, run these requests when structure is ready.

```powershell
$document = "$api/documents/$($upload.document.id)"
Invoke-RestMethod -Uri "$document/structure"
$page = Invoke-RestMethod -Uri "$document/chunks?limit=1"
$chunk = $page.items[0]
Invoke-RestMethod -Uri "$document/chunks/$($chunk.id)/source" |
  ConvertTo-Json -Depth 12
```

## Linguistic annotations

The default rules profile starts automatically after structure is ready. The following paths are relative to `/api/v1/workspaces/local/documents/{document_id}`.

| Method and path | Behavior |
|---|---|
| `GET /nlp` | Returns pending, ready, failed, or unavailable, with method and annotation count. |
| `GET /annotations?limit=25&after=0` | Lists chunks' annotations in ordinal order. Use `next_cursor` when present. |
| `GET /chunks/{chunk_id}/annotation` | Returns the annotation for one chunk of the current document and profile. |

A pending build returns HTTP 409 from the annotation routes. A missing configured model returns HTTP 503. Offsets are relative to the extraction field specified by `source`. The returned token array provides indices for dependency heads.

Install the optional models as described in the [NLP guide](NLP_PIPELINE.md) to use the two local inference endpoints below. Send JSON with `X-SmartDoc-Local: 1`.

| Method and path under the local workspace | JSON input | Result |
|---|---|---|
| `POST /nlp/embeddings` | `{"texts":["An example sentence."]}` | Model revision and a normalized vector and truncation flag per input. Accepts up to 12 texts. |
| `POST /nlp/inference` | `{"pairs":[{"premise":"The valve is open.","hypothesis":"The valve is closed."}]}` | Three-way prediction, scores and truncation flag per pair. Accepts up to 8 pairs. |

These endpoints run on the local CPU. They do not retrieve documents or send text to an external service.

## Next Concept Modelling

The worker schedules a snapshot after NLP is ready. These routes are relative to `/api/v1/workspaces/local/documents/{document_id}/ncm`.

| Method and path | Purpose |
|---|---|
| `GET` on the `/ncm` path itself | Read latest status, snapshot revision and counts. |
| `GET /concepts` or `/concepts/{concept_id}` | Read ranked concepts, mentions, aliases, definitions and score contributions. |
| `GET /assertions` and `GET /hierarchy` | Read typed assertions and hierarchy links with source evidence. |
| `GET /alias-candidates` and `GET /duplicate-candidates` | Read unresolved alias and lexical suggestions for review. |
| `GET /dependencies/{concept_id}?direction=prerequisites&depth=4` | Read bounded prerequisite chains, their assertion IDs and cycles. Use `direction=impact` for reverse traversal. |
| `GET /revisions` | Read revision metadata and review history. |
| `POST /revisions` | Publish an audited `merge`, `reject_assertion`, `rebuild` or `restore` revision. |

List endpoints are paginated. Snapshot data endpoints accept `revision=...`. Revision writes require `X-SmartDoc-Local: 1`, a reason and `expected_revision`. A stale edit returns HTTP 409. Example merge input is `{"action":"merge","expected_revision":1,"reason":"Confirmed terminology in this manual","source":"source-uuid","target":"target-uuid"}`.

Use `GET /api/v1/workspaces/local/ncm/compare?left=...&right=...` for evidence-backed differences. Supply optional left and right revision numbers. Chronology defaults to `unspecified`. `declared_left_before_right` records a caller-provided ordering. Every returned side retains its own anchors.

## Knowledge graph

Routes are relative to `/api/v1/workspaces/local/graph`. Graph endpoints use the most recent ready version unless `version_id` is supplied.

| Method and path | Purpose |
|---|---|
| `GET` on the `/graph` path itself | Read the most recent build status, source revision IDs and available ready version. |
| `GET /versions` and `GET /versions/{version_id}` | Read graph version history or one version. |
| `GET /nodes` and `GET /nodes/{node_id}` | Browse nodes or read a node. Use `document_id`, `kind` and `query` for node browsing. |
| `GET /edges` and `GET /edges/{edge_id}/evidence` | Read exact stored edges and their evidence. Edge filters include `document_id`, `node_id`, `predicate`, `kind` and `validation`. |
| `GET /neighbors?node_id=...&direction=both` | Expand up to three hops. Each returned edge contains a source excerpt. |
| `GET /paths?source=...&target=...&direction=both` | Find an evidenced path, with an explicit result if traversal is bounded or finds no route. |
| `GET /orphans` | List concept-bearing nodes without traversable edges in the selected view. |
| `GET /analytics?communities=true` | Calculate components, degree centrality, isolated nodes, cycle groups and optional communities. |

Use `view=semantic`, `view=dependencies` or `view=all` for navigation filters. The semantic view is the default for paths and neighborhoods. Edge browsing defaults to all records. Set `version_id` from the first page before continuing with `next_cursor`. The [graph design](KNOWLEDGE_GRAPH_DESIGN.md) explains link semantics, scope and bounds.
