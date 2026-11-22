# Known limitations

- Phase 2 exposes local document ingestion through the API. The browser application displays system status. The document workspace UI is planned for a later phase.
- Supported formats are PDF, DOCX, TXT, Markdown, HTML, CSV, XLSX, PPTX, JSON, YAML, PNG, JPEG and TIFF. Legacy binary DOC and macro-enabled Office files are outside the current format support.
- English OCR runs on image files and PDF pages with empty native text. Quality on noisy scans, handwriting, non-English text and images embedded on native-text pages remains unverified. Native PDF reading order and tables rely on parser layout heuristics.
- Source units preserve available format locators and structural data. Stable element IDs, unified source offsets and chunking are Phase 3 work. DOCX footnotes remain in the original file. HTML extraction supports common flat tables.
- Identical bytes reuse one document and job in the local workspace. User-triggered retries, version management, deletion and orphaned-blob cleanup are future work.
- The built-in ingestion routes are loopback-only for the development profile. Sign-in, tenant authorization and production deployment are pending. Windows and browsers beyond Chromium remain unverified.
