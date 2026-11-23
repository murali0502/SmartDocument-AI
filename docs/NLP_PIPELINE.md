# Phase 4 NLP pipeline

The worker annotates Phase 3 primary chunks and writes each batch transactionally. It uses the same worker that handles ingestion and structure. Existing structured documents enter the queue automatically. The persisted profile key includes the pipeline version, method and glossary. When that key changes, the worker builds a new annotation run from the saved chunks. Interrupted runs resume from the last committed ordinal. Annotations become available when the configured profile finishes.

Every annotation carries the chunk's source address. Token, phrase, entity, sentence, dependency argument, temporal, and coreference spans use the same half-open Unicode code-point coordinates as the chunk. Token normalization uses NFKC and case folding and preserves the original span. The dependency head is a zero-based index into the returned token list. A null head means a root or unavailable head. The NLP stage reads primary text. It does not duplicate inherited overlap.

## Execution profiles

| Profile | Capabilities |
|---|---|
| `rules` (default) | Surface tokens, separate normalized tokens, sentence boundaries, English heuristics, a configurable term list, explicit dates and times, measurement and technology labels, bounded relationship patterns, and conservative within-chunk reference candidates. Lemmas, POS and dependencies are null in this profile. |
| `spacy` | Adds English trained tokenization, lemmas, POS, dependencies, noun phrases and named entities using spaCy `en_core_web_sm` 3.8.0. It checks whether the dependency tree supports each matching relationship pattern. |

Both profiles report lexical or dependency-supported candidates with exact evidence, polarity and optional modality. The role labels cover supported predicates and are rule-derived. Some multi-clause constructions are deliberately excluded. Coreference handles a narrow set of demonstrative references from the preceding sentence and preserves ambiguity. Relative dates remain unresolved when a reliable reference date is unavailable. Language detection returns `en` when there is sufficient English lexical evidence and `und` otherwise. The optional English model is skipped on chunks with primarily non-Latin scripts.

These outputs are candidate annotations. Phase 5 will use them with additional corroboration for canonical concepts and graph assertions. Phase 7 adds retrieval and ranking.

## Optional local models

From `backend`, install the optional runtime and pinned model files explicitly.

```powershell
uv sync --locked --extra nlp
uv run --frozen --extra nlp python -m smartdoc.nlp.assets english embedding nli
$env:SMARTDOC_NLP_PROFILE = "spacy"
uv run --frozen --extra nlp python -m smartdoc
```

On Bash, use `export SMARTDOC_NLP_PROFILE=spacy`. Select any subset of `english`, `embedding` and `nli` in the installer. Use `SMARTDOC_NLP_MODEL_DIR` to set the cache directory. The default is `backend/.local/nlp-models` when launched from `backend`. Restart after installing a missing model. Set the profile back to `rules` for a download-free runtime.

The explicit installer checks pinned SHA-256 digests before installation. The API uses local resources only and loads models on demand. The runtime verifies the ONNX and tokenizer files before loading them. The tested quantized exports target x86-64 CPUs with AVX2. Their compatibility on Windows or other architectures was not verified.

| Artifact | Download size | License |
|---|---:|---|
| spaCy English small pipeline | About 13 MB | MIT |
| MiniLM-L6-v2 AVX2 embedding graph | About 23 MB, plus tokenizer | Apache 2.0 |
| NLI MiniLM2-L6-H768 AVX2 classifier | About 83 MB, plus tokenizer | Apache 2.0 |

Embeddings use attention-masked mean pooling and L2 normalization, yielding 384-dimensional vectors. The NLI classifier outputs three scores with labeled entailment, contradiction and neutral candidates. Both expose truncation at a 256-token model input limit. The scores are uncalibrated and do not verify the source of a claim. Models can fail on technical conditions, numbers and different meanings of the same term.

[spaCy English model](https://github.com/explosion/spacy-models/releases/tag/en_core_web_sm-3.8.0) · [MiniLM embeddings](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) · [MiniLM2 NLI](https://huggingface.co/cross-encoder/nli-MiniLM2-L6-H768)

## Evaluation

The 12 linguistic inputs, four retrieval queries over six passages, and six NLI pairs in `evaluation/datasets/phase4-test.json` were manually labeled for a small engineering feasibility check. The code reports exact text-and-label entity F1, exact relation and polarity F1, temporal and coreference F1, embedding reciprocal ranks and NLI accuracy. Run it from the repository root.

```sh
uv run --project backend --frozen --extra nlp python scripts/eval_nlp.py --models backend/.local/nlp-models
```

Omit `--models` to evaluate the rules profile alone. The checked-in fixtures and application tests are small and English-first. Corpus-wide performance, language coverage and confidence calibration remain later evaluation work.

| Test | Rules | spaCy or ONNX |
|---|---:|---:|
| Entity F1 on 9 labels | 0.80 | 0.90 |
| Relation F1 on 6 labels | 0.80 | 0.80 |
| Exact temporal matches | 3/3 | 3/3 |
| Antecedent matches | 1/1 | 1/1 |
| MiniLM top-one retrieval probe | — | 4/4, MRR 1.00 |
| NLI classifications | — | 6/6 |

The entity F1 increase came with two additional predictions beyond the nine labeled entities. The relation rules found four of the six labeled relations in both profiles. In one run, the optional probe peaked at about 315 MiB RSS across spaCy and both lazily cached ONNX models. The installed model data occupied 118 MiB. These are local development measurements on a small fixture, without concurrent workloads or a deployed retrieval engine.
