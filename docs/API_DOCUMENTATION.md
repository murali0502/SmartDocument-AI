# API documentation

The available prefix is `/api/v1`. OpenAPI is served at `/api/v1/openapi.json`. The optional Swagger UI at `/api/v1/docs` uses FastAPI's default third-party static assets.

| Method and path | Response |
|---|---|
| `GET /api/v1/health/live` | HTTP 200 with `status: alive` when the API process is serving requests. |
| `GET /api/v1/health/ready` | HTTP 200 with `status: ready` when SQLite is accessible at the expected migration heads with the required tables. HTTP 503 otherwise, with `status: unavailable` and a database code. |
| `GET /api/v1/openapi.json` | The live OpenAPI contract used for client type generation. |

Readiness includes `database` (`ready`, `missing`, `migration_required`, or `unavailable`) and `checked_at` in UTC. Both health responses set `Cache-Control: no-store`. Every handled response carries an `X-Request-ID` header.

Errors use `application/problem+json` with `type`, `title`, `status`, `code`, `detail` and `request_id`. Readiness HTTP 503 returns the documented readiness payload so monitoring clients can interpret the service state.

Document, workspace administration, ingestion, retrieval and answer routes enter the contract as their phases are implemented.
