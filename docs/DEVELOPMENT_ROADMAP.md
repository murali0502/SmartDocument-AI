# Development roadmap

| Phase | Exit evidence |
|---|---|
| 0. Feasibility and architecture | Architecture, methodology, model review, data model, repository structure, roadmap and risks available for user approval. |
| 1. Foundation | Fresh Linux bootstrap, Windows check or documented issue, migration up and down, real health checks, structured errors, frontend/API integration and initial CI. |
| 2. Ingestion | Independent fixture per supported file type, corrupt and duplicate uploads, mixed native and scanned PDFs, reproducible jobs and durable originals. |
| 3. Structure and chunking | Golden hierarchy, table cells and format locators. Unicode span, fragment/overlap and source-view round trips. |
| 4. NLP | Measured tagging, entities, dependency and confidence-aware coreference against annotated text. CPU model profiles and documented unsupported languages. |
| 5. NCM | Concept, alias, hierarchy, dependency and evolution metrics. Manual merges and splits tested against ambiguous terms and unchanged historical evidence. |
| 6. Graph | Published and filtered snapshots, evidence-bearing neighborhoods/paths, cycle and centrality checks and versioned replay. |
| 7. Retrieval | Text, concept, structure, dense and graph ablations with fused, reranked and diversified results, measured at multiple corpus sizes. |
| 8. Reasoning | Intent, clarification, dependency rules, conflicting contexts, date anchoring and checked quantity conversions. |
| 9. Answering | Claim-to-evidence checks, insufficient evidence behavior, optional proposal validation, and verified full NCM-only flow. |
| 10. Document intelligence | Annotated examples for comparisons, contradictions, summaries, structured extraction, possible gaps and evolution. |
| 11. Frontend | All ten pages use live API data and receive accessibility and end-to-end workflow verification. |
| 12. Evaluation | Locked held-out suite, document-to-answer browser scenario, benchmark report, resource profiling and dependency audit. |
| 13. Release | Hardened deployment, backup-restore drill, observability and security review. Release status follows actual results. |

Each phase maintains PROJECT_STATUS.md and reports files, dependencies, commands, tests, actual results, risks, performance, security and the next recommendation. Suggested document ownership is README, project overview, development guide and changelog in Phase 1. Add API/security/testing documentation during foundations and API extensions, NLP during Phase 4, graph during Phase 6, retrieval during Phase 7, evaluation methodology before data labeling and deployment during Phase 13. Maintain known limitations continuously.

## Evaluation design

Version fixtures and adjudicated annotations. Split by document family and revision chain to avoid leakage. Preserve domain, format, OCR, intent, ambiguity and answerability strata. Define positive, negative and multi-evidence labels. Double-label and adjudicate a subset. Freeze held-out manifests and thresholds before final runs. Report dataset size, license and limitations. Use paired document-group bootstrap intervals where the sample supports them.

Metrics include ingest success, OCR word/character error rates, structural and locator fidelity; entity, relation, canonicalization and path precision/recall/F1; Recall@K, Precision@K, MRR, nDCG and hit rate; citation coverage and precision, unsupported claim rate, answer relevance and abstention; p50/p95 end-to-end, step timing, RSS, CPU and storage. Cite actual below-target results. Phase gates include all golden source anchors round-tripping, zero cross-workspace visibility in integration fixtures and no unsupported claims in accepted golden answers. Agree on corpus-scale quality and latency targets before release benchmarking.

The final browser test uploads a licensed multi-page technical PDF, checks text and table structure, follows a verified answer citation back to the original page, explores related concepts and verifies persistence after restart.
