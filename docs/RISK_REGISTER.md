# Risk register

| Risk | Mitigation and resolution |
|---|---|
| PDF layout and OCR misplace evidence | Measure native and OCR layers independently. Use page/word geometry, round-trip fixtures and quality warnings. Accept uncertain geometry only with an explicit warning. Phases 2–3. |
| Concept merging loses distinct senses | Resolve scoped exact labels, require independent alias corroboration, audit reversible corrections, measure false merges by domain. Phase 5. |
| Unsupported inference or conflict | Keep asserted edges and typed derivations distinct. Enforce contextual qualifiers, inspect each edge, measure wrong conflict and abstention rates on counterexamples. Phases 8–9. |
| Workspace leakage or stale indexes | Scope joins and ranking. Publish run visibility atomically. Enforce authorization again at citation and preview serving. Verify concurrent claims, reprocess and deletion. Phases 1, 6–7. |
| Input consumes worker resources | Bound archive expansion, native parsers, OCR and jobs. Keep untrusted content and network access out of parser subprocesses. Audit dependencies. Phases 2, 12–13. |
| Corpus scale exceeds CPU profile | Track RSS and p95, cap graph expansion, benchmark filtered exact and ANN paths, serialize heavy tasks. Phases 7, 12. |
| License or platform compatibility differs | Record pinned artifact metadata, verify redistribution notices and benchmark Windows with native or WSL2 paths. Phases 1–4. |
| Optional model invents or discloses information | Explicit profiles, validators, no tools or direct database mutations for model adapters, scoped text, endpoint allowlists, integrity and privacy tests. Phase 9. |
| Dataset leakage inflates results | Group versions and related documents in the same split, preregister evaluation thresholds and report uncertainty. Phases 4–12. |
| Retention and hosting needs are unclear | Local-first is the initial design assumption. Resolve corpus size, SSO, deployment and retention before production configuration. Phase 13. |
