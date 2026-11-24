# Known limitations

- The local API exposes ingestion, structure and chunks. The browser application displays system status. The document workspace UI is planned for a later phase.
- Supported formats are PDF, DOCX, TXT, Markdown, HTML, CSV, XLSX, PPTX, JSON, YAML, PNG, JPEG and TIFF. Legacy binary DOC and macro-enabled Office files are outside the current format support.
- Scanned PDFs and image files need a private vision-language model for Ask SmartDoc. New image-only pages have no text index, and real model accuracy on handwritten or noisy pages depends on the chosen model. Native PDF reading order and tables rely on parser layout heuristics.
- Source offsets address immutable extracted fields. PDF typography and Markdown and HTML syntax supply structural hints where available. PDF reading order and heading inference are heuristic. DOCX footnotes remain in the original file, and HTML extraction supports common flat tables. Saved Phase 2 results use the metadata they already contain.
- Identical bytes reuse one document and job in the local workspace. User-triggered retries, version management, deletion and orphaned-blob cleanup are future work.
- The built-in ingestion routes are loopback-only for the development profile. Sign-in, tenant authorization and production deployment are pending. Windows and browsers beyond Chromium remain unverified.

- Phase 4 linguistic rules target English and its relation and coreference outputs are limited candidates. The optional model evaluation uses a small fixture. Language coverage, production calibration and model support outside the tested Linux AVX2 environment remain unverified.

- Phase 5 concept identities are document-scoped. Similarity only suggests review. Relation patterns cover a limited vocabulary. Comparisons preserve ambiguity and do not infer chronology from ingestion metadata. Phase 6 projects a collection graph with conservative definition-based alignment.

- Phase 6 builds full local graph snapshots with explicit size limits. Navigation is budgeted, and analytics use a bounded simple graph projection. Collection-wide identity merging, distributed graph storage, retention policies and the browser graph view remain future work.
