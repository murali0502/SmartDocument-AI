# Testing strategy

Phase 1 backend tests exercise the liveness contract, missing and corrupt storage, migration readiness, OpenAPI publishing, error sanitization, request correlation, and membership constraints against temporary SQLite files. The migration test upgrades, checks schema drift, downgrades, and upgrades again.

The browser test runs the production frontend build and real API on loopback. It observes HTTP 503 with missing storage, migrates a disposable database, refreshes to HTTP 200, verifies the rendered status and public API contract, and checks a mobile viewport. Playwright captures the healthy desktop and mobile states.

Later phases add parser golden files, citation offset and geometry round trips, NLP and NCM annotations, ranked retrieval benchmarks, authorization tests, and the full upload-to-source workflow. The [roadmap](DEVELOPMENT_ROADMAP.md) tracks their exit conditions.
