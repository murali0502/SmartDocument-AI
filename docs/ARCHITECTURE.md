# SmartDoc AI architecture proposal

Phase 0 architecture approved. Initial scope is local-first and English-first. See the project status for verified implementation.

## Runtime topology

A same-origin React and TypeScript client calls a versioned FastAPI API. SQLAlchemy and Alembic own the SQLite schema. One local ingestion worker claims durable leased jobs and launches resource-bounded document parser and OCR subprocesses. A query service uses immutable, published analysis runs. SQLite owns evidence, jobs, configuration, graph assertions, FTS5 and embedding metadata. A managed local blob directory owns content-addressed originals and generated previews. NetworkX is an on-demand, bounded graph projection. Use Ollama or a compatible local inference service only through an explicitly enabled proposal adapter. Cloud services have no dependency in the default topology.

Flow: validate upload and record digest → claim job → parse and store immutable source units → chunk → annotate → propose and validate concepts and assertions → build scoped indexes → atomically publish analysis run → interpret question → retrieve and rank evidence → reason → verify citations and claim support → return answer, clarification or abstention.

## Contracts

| Boundary | Contract |
|---|---|
| Format adapter | Blob and limits → manifest, source units, element tree, typed tables, locator maps, warnings |
| Chunker | Immutable source view and policy → primary spans, overlap spans and source maps |
| NLP | Sentence with source offsets → tokens, lemmas, entities, dependencies, optional coreference and semantic roles |
| NCM | Annotated spans and policy → immutable mentions, resolution proposals and provenance-linked type assertions |
| Graph | Authorized snapshot and budget → bounded neighborhood, paths or metrics |
| Search | Resolved query and scoped snapshot → ranked candidate spans and channel diagnostics |
| Reasoner | Query plan and validated evidence → typed claim candidates and derivations |
| Citation validator | Candidate and immutable source → locator result and independent support assessment |
| Model adapter | Bounded structured request → proposal envelope with adapter/version and provenance |
| Storage | Transactional records, staged bytes and immutable release pointers |

Scope and run identity travel across all application boundaries. CPU-heavy work is bounded and stays outside HTTP event loops. Workers renew leases and use a fencing token on writes. Failed or stale attempts remain unpublished. The API reports explicit optional-feature degradation.

## API

Base prefix /api/v1. Health and session endpoints sit at the root. All data routes sit under /workspaces/{workspace_id}. Route families cover auth/session, documents, uploads, versions, jobs, source units, chunks, citations, concepts and review revisions, relationships, graph/neighbors and graph/paths, search, questions, stored answers, comparisons, analytics, evaluation runs, and settings. Upload responds with 202 and a job reference. Scope and expected versions are validated on the server. Lists use opaque cursor pagination. Mutations use idempotency keys or revision preconditions as appropriate. RFC 9457 errors carry safe messages and request IDs. Stable citation responses carry revision, pipeline run, source coordinates and excerpt. OpenAPI is generated from request and response contracts.

Use a same-origin frontend, secure session cookies and CSRF controls. Resolve workspace membership before loading or indexing user data. Serve original bytes as attachments, provide controlled safe previews, and log IDs and event classes. Parse files without network or shell access, enforce page, pixel, archive expansion, time and memory budgets, and never execute macros, spreadsheet formulas, external references or embedded instructions. Workspace graph and retrieval diagnostics are authorization-scoped.

## Proposed repository

```text
smartdoc-ai/
  backend/
    src/smartdoc/
      api/              HTTP, security dependencies and schemas
      application/      Upload and question orchestration
      domain/           Typed contracts, spans and review state
      ingestion/        Format adapters and parser worker
      chunking/         Structural segmentation and offset mapping
      nlp/              Preprocessing, linguistic annotations and model ports
      ncm/              Extraction, resolution, scoring, assertions and evolution
      graph/            Scoped projections, traversal and graph analytics
      retrieval/        Index adapters, fusion, ranking and diagnostics
      reasoning/        Query plans, comparison, dependency and numerical rules
      answers/          Evidence selection, templates and citation validation
      persistence/      Repositories, transactions, blobs and jobs
      evaluation/       Benchmark runners and metric implementations
    migrations/
    tests/
  frontend/
    src/features/       Dashboard, library, detail, ask, concepts, graph,
                        comparison, analytics, settings and evaluation
    src/components/
    src/generated/      Typed client generated from the backend OpenAPI contract
    tests/
  evaluation/datasets/  Licensed fixtures and group-level split manifests
  docs/
  infra/
  scripts/
  README.md
  PROJECT_STATUS.md
```

## Profiles and UI

Minimal profile runs SQLite, one worker, sparse/concept/graph retrieval and deterministic answers. The CPU profile adds spaCy and a lazy quantized ONNX encoder. Reranking, NLI, multilingual NLP, remote inference and larger index stores are explicit capabilities with independent acceptance tests.

Dashboard and analytics read persisted run and query telemetry. Document library and detail expose upload, status, version, structured content and provenance. The Ask client displays answer states and ranked evidence. Concept Explorer records reviewed corrections. The graph progressively fetches bounded neighborhoods and supports edge evidence, filters and path discovery. The comparison, settings and evaluation pages expose live backend workflows. Begin with React, Vite and TypeScript. Evaluate Cytoscape.js with accessible list and keyboard navigation alongside the graph.
