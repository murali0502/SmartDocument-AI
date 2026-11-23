# Document structure and chunking

Phase 3 converts each successful ingestion result into a versioned structure. The background worker also processes saved Phase 2 results after migration. The original file and extraction manifest stay available. A build publishes its run, elements and chunks in one transaction. A restarted worker finds unbuilt extractions again.

## Element hierarchy

Elements have a stable ID, ordinal, parent, kind, and physical locator where one exists. The hierarchy includes document, page, slide, sheet, section, heading, paragraph and sentence. It also preserves list and item, table and row and cell, figure, caption, footnote, reference, and code and math where visible in the available extraction records. Section paths carry the IDs, levels and labels of the active logical headings. A chunk on a page after a section begins still carries its own page number.

Markdown headings and table markers come from its parser. DOCX uses styles. HTML records visible structural ranges. PDF headings use native line typography and conservative text rules. Known table ranges stay distinct from native paragraphs. PDF tables from older manifests with unknown position remain accessible under the page without a guessed section. Slides retain shape and notes context. Workbook rows retain A1 references and named table ranges. OCR uses separate text and page or frame locators.

## Source spans

A span addresses an immutable extraction field with a one-based unit number, an array of field keys or zero-based list indices, and a half-open Unicode code-point range. In Python, `field[start:end]` gives the exact excerpt. A text span uses the saved parser string. Numeric and Boolean cells use an explicitly labeled JSON scalar projection. Ranges do not refer to byte positions in PDF, DOCX, or other source containers. Physical page, slide, shape, and cell locators accompany the ranges.

For example, `{"unit":2,"field":["data","ocr","text"],"start":0,"end":22,"projection":"text"}` points to a slice of the second extraction unit's OCR field. The chunk source endpoint resolves the saved field again and verifies the primary and overlap strings.

Build IDs are deterministic within one extraction job and structure version. Element IDs use their type, logical parent and occurrence or source address. Chunk IDs use the parent, strategy and primary range. A different extraction job can assign different IDs.

## Chunk policy

Each chunk uses one anchored structural element. Paragraphs prefer sentence boundaries. Code, math and table cells prefer line boundaries. Both paths fall back to a token or character boundary. The current policy is 160 regex tokens and 1,600 Unicode code points per primary fragment. Every primary fragment has its own range. A following fragment may include up to 24 tokens and 320 characters from the preceding fragment as separately addressed overlap. Token counts are deterministic estimates for Phase 3. They do not represent a future embedding model's tokenizer.

The generated rows are bounded to 130,000 elements and 100,000 chunks per document. Exceeding a limit records a failed structure build while keeping ingestion and the extraction accessible.

The heading and sentence rules are heuristic. Complex layouts can require manual interpretation. DOCX footnotes and original Office layout beyond the saved parser records remain available through the original file. Earlier manifests have their original locator coverage.
