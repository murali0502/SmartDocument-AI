# SmartDoc AI project status

Updated 24 November 2026. The Phase 0 architecture is approved. Phases 1 through 7 are implemented and verified on Linux. Phase 8 is pending.

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
- Used a single background worker started by the API. Parsing runs in a bounded subprocess. A synthetic extraction verifies that Bubblewrap can start with the required filesystem mounts before the worker sends it a document. The browser continues to provide system status. Uploads and extraction review use the local API in this phase.

### Files and dependencies

Created `backend/migrations/versions/0002_document_ingestion.py`, the ingestion routes, upload application service, parser package and worker, persistence models and store, and `backend/tests/test_ingestion.py`. Updated the API launcher/configuration, migration registration, generated frontend contract, CI, lockfile, README, changelog, and API, development, data model, security, testing, overview and limitations documentation.

Added pdfplumber, PDFium bindings, Pillow, python-docx, openpyxl, python-pptx, markdown-it-py, PyYAML and defusedxml. ReportLab builds test PDF fixtures. Tesseract and its English data are system dependencies for OCR. The advisory scan prompted an upgrade from Pillow 12.3.0 to 13.0.0.

### Commands and observed results

| Check | Commands | Result |
|---|---|---|
| Backend and extraction | `uv sync`, `uv run --frozen ruff check`, `ruff format --check`, `uv run --frozen pytest -q` | Ruff passed. 32 backend tests passed, including per-format extraction, real OCR, validation, concurrency and restart checks. |
| Migration and live API | `alembic upgrade 0001_workspace_foundation`, `alembic upgrade head`, `alembic check` and temporary Uvicorn HTTP probe | A database at Phase 1 upgraded with no ORM drift. The live API processed native and scanned PDFs, deduplicated repeats and retained both results after server restart. |
| Frontend regression | OpenAPI export, `npm run contracts`, `npm run build` and `npm run test:e2e` with Chromium | Build and browser status regression passed. |
| Dependency advisory check | `uv export` of locked runtime packages, then `uvx pip-audit` | The rescan after updating Pillow found zero known advisories. |

### Performance and security observations

A local HTTP smoke run took approximately 1.75 seconds for a two-page native PDF and 1.92 seconds for a one-page scanned PDF, including queue polling. Both ran through Bubblewrap. These are individual development fixtures, measured before the Pillow dependency update. Upload limits, traversal rejection, disallowed Office XML and cross-origin behavior are exercised in tests. The first hosted run exposed a parser startup difference on GitHub's Linux image. The worker now verifies its full sandbox configuration with synthetic input before selecting it and reports its fallback mode. Windows and production isolation remain unverified.

### Incomplete and upcoming

Legacy DOC, production access controls, browser document workflows, user-triggered reprocessing, and broad OCR accuracy evaluation remain open. Phase 3 should add stable structural IDs, source-offset maps and structure-aware chunking with exact provenance tests.

## Phase 3 implementation report

### Features and decisions

- Added versioned structural snapshots, stable element and chunk IDs, nested section and list paths, and document, page, slide, sheet, table, row and cell locators.
- Built chunks within their structural element. Sentence or line boundaries take precedence where possible. Every primary fragment has its own half-open Unicode range. Overlap is stored with independent provenance.
- Added exact-source verification against the saved ingestion manifest, including text and numeric or Boolean cell projections. New PDF and HTML parser hints improve heading and table placement. Older manifests use their existing metadata.
- Added paginated elements and chunks APIs and an exact-source endpoint. The single existing background worker backfills unbuilt successful extractions and publishes each snapshot atomically.

### Files and dependencies

Created `backend/migrations/versions/0003_document_structure.py`, the structural contracts and builders, chunk policy and partitioner, structure storage, API routes, and `backend/tests/test_structure.py`. Updated the ingestion worker and PDF, HTML and slide adapters, the generated API types, README, changelog, and implementation guides. Added `docs/STRUCTURE_AND_CHUNKING.md`. No dependencies were added.

### Commands and observed results

| Check | Commands or workflow | Result |
|---|---|---|
| Backend and chunking | `uv sync --locked`, Ruff lint and format, and `uv run --frozen pytest -q` | 45 backend tests passed, including 13 Phase 3 cases. |
| Schema and backfill | `alembic upgrade head`, `alembic check`, and a populated Phase 2 migration test | Reached `0003_document_structure` with no ORM drift. The existing extraction produced a snapshot without another upload. |
| Live source workflow | Temporary Uvicorn server and HTTP upload, structure, chunk and source requests | The repository architecture document and a mixed native/scanned technical PDF retained identical verified excerpts after API restart. |
| Frontend contract and regression | OpenAPI export, `npm run contracts`, `npm run build` and Chromium Playwright | Generated types, TypeScript, Vite and the browser status test passed. |

### Performance and security observations

In one local HTTP run, the repository's architecture document produced 101 elements and 38 chunks in 1.81 seconds. A two-page mixed PDF produced 9 elements and 3 chunks in 1.94 seconds. These measurements include ingestion and queue polling. The API checks the local workspace and validates requested source spans. Tests verified that a mismatched excerpt returns a provenance error and a chunk cannot be located through another document.

### Incomplete and upcoming

PDF heading inference remains heuristic. An offset refers to an extracted field rather than a location in the binary file. Browser document workflows, legacy DOC, Windows execution and production isolation remain unverified or scheduled for later phases. Phase 4 should add and evaluate CPU-friendly linguistic annotation on top of the stable source spans.

## Phase 4 implementation report

### Features and decisions

- Added durable linguistic annotations with exact spans into saved Phase 3 chunks. The default rules profile supports terms, normalized tokens, sentences, dates, times, measurements, limited relationship and role candidates, and conservative demonstrative coreference.
- The optional English spaCy profile adds learned named entities, noun phrases, lemmas, POS and dependencies. It checks dependency support for matching relation candidates. The rules and trained profiles both preserve negation and modality.
- Added local, opt-in MiniLM embeddings and discriminative three-way NLI. The installer verifies pinned artifacts, and API calls load them lazily. The default API starts without model resources. Phase 4 performs annotation and direct model inference. Corpus retrieval begins in Phase 7.
- Added migration `0004_linguistic_annotations`. A versioned profile key defines each run. The worker commits numbered batches and resumes from saved progress after restart. Earlier structured documents enter the queue automatically.

### Files and dependencies

Created the migration, NLP package, annotation store and models, NLP routes and `backend/tests/test_nlp.py`. Added `docs/NLP_PIPELINE.md`, `evaluation/datasets/phase4-test.json` and `scripts/eval_nlp.py`. Updated the worker, schema registration, configuration, generated frontend API contract and development, API, model, data and testing docs. Added spaCy, ONNX Runtime and tokenizers under the optional `nlp` extra. No models or installation cache files are stored in Git.

### Commands and observed results

| Check | Commands or workflow | Result |
|---|---|---|
| Schema and resume | Alembic upgrade from populated Phase 3, `alembic check`, and annotation API tests | The migration preserved source data. Partial annotation batches resumed after restart. |
| Backend | `uv sync --locked`, Ruff lint and format, and `uv run --frozen pytest -q` | The default backend profile passed with the opt-in model test skipped. |
| Optional real models | `uv sync --extra nlp`, explicit pinned artifact installer, then `SMARTDOC_TEST_MODEL_DIR=… uv run --frozen --extra nlp pytest -q` | 51 tests passed with real spaCy, embeddings, and NLI. |
| Frontend | OpenAPI export, `npm run contracts`, `npm run build`, and Playwright Chromium | Passed. |
| Evaluation and scope | `scripts/eval_nlp.py --models …`, plus `pip-audit` against locked runtime packages | 9 entity and 6 relation labels were evaluated. The dependency audit found no known advisories. |

### Performance and security observations

The rules profile scored 0.80 entity F1 and the optional spaCy profile scored 0.90. Exact relation F1 was 0.80 in both. The embedding probe ranked four labeled passages first. NLI classified six labeled pairs correctly. These are small engineering samples. With all three optional resources, peak benchmark RSS was about 315 MiB. In one run, a warm embedding took about 2.8 ms and a warm NLI pair took about 7.5 ms on the development CPU. These timings exclude API latency.

The model endpoints require the local workspace and explicit request header, and do not send the input text to any service. ONNX and tokenizer bytes are hash-checked before loading. Optional integration tests confirm an unavailable model returns an explicit error.

### Incomplete and upcoming

Cross-chunk coreference, broad multilingual analysis, calibrated confidence, larger benchmarks, Windows execution, and optional model support outside the tested Linux CPU remain unverified. Phase 5 should use the annotated spans to build versioned, evidence-grounded concept and relationship candidates with conservative alias resolution.

## Phase 5 implementation report

### Features and decisions

- Added exact-anchor concept and assertion extraction, document-scoped canonicalization, explicit aliases, unresolved senses and lexical duplicate suggestions. Lexical similarity produces review suggestions.
- Added configurable scoring with per-feature contributions, structural and semantic hierarchy links, and bounded prerequisites, impact and cycle analysis.
- Added versioned NCM snapshots and audited local merge, reject, rebuild and restore actions. Comparisons link each side to its source and use user-declared ordering only when given.
- Added read and review APIs and a background build step for existing NLP results.

### Files and dependencies

Created `backend/migrations/versions/0005_ncm_snapshots.py`, the NCM modelling, scoring, acquisition, comparison and dependency modules, the snapshot store and API, and `backend/tests/test_ncm.py`. Added `scripts/eval_ncm.py` and `evaluation/datasets/phase5-test.json`. Updated the application worker, migration registration, configuration, generated API types, README, changelog, and methodology, data, API and testing docs. This phase adds no dependencies or model downloads.

### Commands and observed results

| Check | Commands or workflow | Result |
|---|---|---|
| Backend | `uv sync --locked`, Ruff lint and format, and `uv run --frozen pytest -q` | 59 passed and the existing optional-model test skipped. With the models enabled, all 60 tests passed. |
| Schema and revisions | Alembic upgrade of a populated Phase 4 database, `alembic check` and review API tests | Backfilled existing NLP results, rejected stale edits, preserved older revisions and restored a prior revision. No schema drift. |
| Live API | Uvicorn upload, NCM status, assertions, dependencies, comparison and restart | Three assertion excerpts matched the extraction fields. Two dependency paths and both sides of a changed definition were verified. The snapshot survived restart. |
| Frontend | OpenAPI export, contract generation, TypeScript/Vite build and Playwright | Passed. |
| NCM evaluation | `uv run --project backend --frozen python scripts/eval_ncm.py` and optional spaCy evaluation | Both independently checked all emitted evidence anchors against the original extraction fields. |

### Evaluation and performance observations

The seven hand-labeled documents contain 21 concept names, nine relations, two accepted alias pairs, and one ambiguous acronym. The names metric does not score fine-grained senses.

| Profile | Concept F1 | Relation F1 | Verified anchors | Accepted aliases | Ambiguity found |
|---|---:|---:|---:|---:|---:|
| Rules | 0.923 | 0.941 | 77 | 2/2 | 1/1 |
| Optional spaCy | 0.955 | 0.875 | 119 | 2/2 | 1/1 |

Rules found 18 of 21 concepts and 8 of 9 relations with no extra predictions in those categories. The spaCy profile found all 21 concept names, added two extras, and found 7 of 9 relations. This is a small feasibility fixture. Rules took about 11 ms for all seven local examples. The spaCy run took about 974 ms including model loading. Neither figure includes file ingestion or HTTP latency.

### Security and remaining work

NCM reads and review mutations are limited to the local workspace. The review header and expected revision are mandatory. The worker verifies exact extraction spans and reconstructs the relation pattern before accepting Phase 4 proposals. Tests include a fabricated relation candidate and a changed source string.

The relation rules and alias patterns remain limited. Cross-document alignment is conservative. Source publication dates, broader authority and contradiction adjudication, and collection graph storage remain later work. Windows execution remains unverified. Phase 6 should build the versioned knowledge graph from NCM evidence.

## Phase 6 implementation report

### Features and decisions

- Added versioned collection graph storage using SQLite. Each version freezes its source NCM and extraction records. Graph publication verifies source anchors and endpoints and publishes nodes, edges and evidence together.
- Preserved document-scoped concepts. A shared definition node links uniquely named, compatible concepts with identical unqualified definition text. Case-sensitive distinctions are preserved.
- Added filtered browsing, bounded neighborhoods and paths, orphan detection, and NetworkX components, degree centrality, cycles and optional communities.
- Added graph replay after NCM review and fallback to last ready data when a new projection fails.

### Files and dependencies

Created `backend/migrations/versions/0006_knowledge_graph.py`, graph contracts, projection, query and analytics modules, relational storage, API routes and `backend/tests/test_graph.py`. Added `docs/KNOWLEDGE_GRAPH_DESIGN.md`. Updated the application worker, migration registration, generated API contract, README, changelog, and graph, data, API and testing documentation. Added NetworkX 3.7 through the runtime lock. There is no new model download or service.

### Commands and observed results

| Check | Commands or workflow | Result |
|---|---|---|
| Backend | `uv sync --locked`, Ruff lint and format, and `uv run --frozen pytest -q` | 68 passed with one optional-model check skipped. All 69 passed with pinned models enabled. |
| Migration | Standalone `alembic upgrade head` and `alembic check`, plus upgrade from populated Phase 5 data | Passed. The standalone check initially exposed missing ORM registrations. Explicit imports and a CLI regression test now cover this path. |
| Live HTTP | Two uploads, graph publication, filtered nodes, four-hop path, source comparison, analytics and restart | Both documents contributed verified excerpts, and the same version and path survived restart. |
| Frontend | OpenAPI export, generated client check, `npm run build` and Playwright Chromium | Passed. |
| Dependency advisories | `pip-audit` on the locked runtime export including optional packages | No known vulnerabilities reported. |

### Performance and security observations

The small live HTTP check published 17 nodes and 26 stored edges in 2.04 seconds from two uploads, including ingestion and queue polling. A four-hop path took 20.8 ms median across 15 warm HTTP requests. These are development measurements on a tiny graph. Larger corpus throughput and storage sizing remain unverified.

Graph records stay within the local workspace and active configuration. Tests cover rejected, conflicted and conditional assertions, tampered evidence and foreign endpoint identifiers. Version publication preserves prior ready data if a new build fails.

### Incomplete and upcoming

The browser graph view, global identity merges, production audit and retention policies, large-graph evaluation, and Windows execution remain unverified or planned. Phase 7 should add sparse, dense, concept, structure and graph retrieval, then evaluate ranking and filtering against annotated queries.

## Phase 7 implementation report

- Added workspace search with BM25, structural, NCM concept, graph and opt-in CPU dense retrieval. The API supports filtered search, weighted reciprocal rank fusion, lexical reranking and optional maximum marginal relevance. The existing source endpoint and retrieval use the same provenance validator.
- Added the retrieval service and route, generated OpenAPI types, integration tests, an annotated benchmark with eight queries, and the [retrieval guide](docs/RETRIEVAL.md). The default runtime added no dependencies or migrations. Dense search reuses the pinned MiniLM embedding model.
- Ran backend lint, format and pytest, OpenAPI export, TypeScript/Vite build, Chromium Playwright, and the retrieval benchmark with and without the model. The benchmark used the normal upload and search endpoints and independently checked every returned excerpt against its source.
- The search endpoint uses existing local or hosted authorization, enforces workspace and document filters before ranking, omits invalid excerpts, and returns non-cacheable responses.

| Corpus | Variant | Recall@5 | MRR@5 | Server p50 |
|---|---|---:|---:|---:|
| 17 chunks | BM25 | 0.875 | 0.750 | 2.10 ms |
| 17 chunks | Default model-free search | 1.000 | 0.729 | 5.14 ms |
| 17 chunks | MiniLM dense only | 1.000 | 0.854 | 47.73 ms |
| 65 chunks | BM25 | 0.875 | 0.688 | 3.54 ms |
| 65 chunks | Default model-free search | 1.000 | 0.692 | 7.61 ms |
| 65 chunks | MiniLM dense only | 1.000 | 0.854 | 132.82 ms |

On both corpora the structural signal increased recall from 0.875 to 1.000 in the unreranked ablation. Concept and graph signals did not add recall and reduced MRR in that ablation. The default model-free benchmark process peaked at 98.7 MiB. The optional-model runs peaked at 211.0 MiB and 215.9 MiB. These are small synthetic Linux benchmarks, and the process timings include retrieval and provenance verification.

Search computes rankings on demand within explicit corpus limits. Persistent indexing, cross-encoder evaluation, independent corpus-scale evaluation, and the browser search experience remain open. Phase 8 should consume the verified candidate contract and test intent, ambiguity, evidence selection, and bounded reasoning.

## Client release

The browser now supports document upload, processing status, scoped questions, and citation inspection. The answer API quotes matching source statements for definitions, requirements, and dependencies. It abstains when a supported, unambiguous statement is unavailable among the retrieved passages. The hosted release retains the existing password gate and persistent SQLite workspace. Broader question interpretation and reasoning remain scoped to the Phase 8 roadmap.


## Client release expansion

| Phase | Release evidence |
|---|---|
| 8. Reasoning | Source-scoped dependency chains, explicit dates, checked electrical conversions, and clarification when statements conflict. Broader context resolution remains open. |
| 9. Answering | Deterministic cited answers, representative summaries, and abstention. Path evidence is rechecked against the active document and source offsets. Optional SLM proposal validation remains open. |
| 10. Document intelligence | Concept revisions, extracted tables and structured fields, summaries, comparison and disconnected concepts in the browser. Direct opposing assertions are surfaced for review. Corpus-wide contradiction adjudication remains open. |
| 11. Frontend | Ten screens, reusable source views, light and dark themes, responsive layout, keyboard focus and reduced-motion support. |
| 12. Evaluation | Packaged measured synthetic retrieval benchmark, end-to-end browser tests and PDF citation coverage. Independent corpus-scale evaluation remains open. |
| 13. Release | Password-gated Docker deployment, secure response headers, health and structured logs, verified snapshot and local restore drill. Independent security signoff and production restore drill remain open. |

See the [client release guide](docs/CLIENT_RELEASE.md) for measured results and operating procedures.

### Phase 8 reasoning increment

Added structured question plans for section constraints, two-concept comparisons, stated-date ordering, and directed or undirected source-backed graph paths. Graph questions now link both canonical concepts and accepted aliases against the active snapshot. Ambiguous aliases, unresolved comparisons and overlapping date intervals produce clarification. Exact electrical conversions reject ambiguous ranges and incompatible units. The integration suite verifies independently cited comparisons, paths and chronology, including incomplete date precision. Supported patterns remain English and deliberately bounded.

### Phase 9 answer and evidence increment

Answer responses now map extractive statements, checked conversions, graph steps, and temporal conclusions to their supporting chunk IDs. Unsupported or conflicting propositions abstain. The opt-in local claim checker uses the pinned NLI model, rejects truncated inputs, and abstains when retrieved evidence contradicts a proposal. The default answer flow stays model-free. The pinned model accepted a supported paraphrase and rejected its negation in an isolated integration run. This verifies the integration on two cases.
