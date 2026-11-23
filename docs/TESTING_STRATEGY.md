# Testing strategy

Phase 1 backend tests exercise the liveness contract, missing and corrupt storage, migration readiness, OpenAPI publishing, error sanitization, request correlation, and membership constraints against temporary SQLite files. The migration test upgrades, checks schema drift, downgrades, and upgrades again.

The browser test runs the production frontend build and real API on loopback. It observes HTTP 503 with missing storage, migrates a disposable database, refreshes to HTTP 200, verifies the rendered status and public API contract, and checks a mobile viewport. Playwright captures the healthy desktop and mobile states.

Phase 2 exercises upload, claiming, subprocess extraction and persistence on independent fixtures for every supported format. OCR assertions cover scanned PDFs and three image types and verify page selection on a mixed PDF. Tests check invalid inputs, streamed size limits, concurrent deduplication, restart recovery and fencing of expired claims. OCR-enabled CI installs Tesseract English data.

Phase 3 covers Unicode and CRLF spans, fragment boundaries and overlap, hierarchy, table cell anchors, and separate OCR and slide fields. Integration checks migrate a populated Phase 2 database, build a snapshot, verify source ranges after restart, and reject mismatched evidence.

Phase 4 tests exact linguistic spans, preservation of negation and modality, conservative coreference, Phase 3 upgrade and batch resume, and explicit unavailable-model behavior. The optional integration test uses the pinned local models when `SMARTDOC_TEST_MODEL_DIR` is set and `--extra nlp` is active. The default CI suite uses the download-free profile.

Phase 5 tests exact concept and relationship anchors, ambiguous aliases and scoped definitions, negative and conflicting claims, dependency cycles and impact, score overrides, review history, rebuild, and backfill. `scripts/eval_ncm.py` reports precision, recall, F1 and evidence round trips on the independent small Phase 5 fixture.

Phase 6 tests immutable revisions and migration from existing NCM snapshots, exact definition alignment, case-sensitive distinctions, evidence reproduction, foreign endpoint rejection, graph fallback on failed builds, filtered paths, dependency cycles, orphans and communities.

Later phases add viewer geometry round trips, NLP and NCM annotations, ranked retrieval benchmarks, authorization tests, and the full upload-to-source workflow. The [roadmap](DEVELOPMENT_ROADMAP.md) tracks their exit conditions.
