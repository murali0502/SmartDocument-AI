# Retrieval

Submit a JSON request to `POST /api/v1/workspaces/local/search`. The same operation is available in the API workspace at `/api/v1/docs`. Search uses the existing local or authenticated hosted workspace and covers documents with ready structure snapshots. Earlier documents become searchable without re-upload or a schema migration.

```sh
curl -fsS http://127.0.0.1:8000/api/v1/workspaces/local/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"What does the pump require?","limit":5}'
```

| Method | What it ranks |
|---|---|
| `bm25` | Unicode-normalized primary chunk text with BM25 term frequencies and corpus statistics. Duplicate query terms do not affect scoring. |
| `structure` | Document filenames and section titles using the same lexical scoring. |
| `concept` | Mentions and definitions from the latest ready NCM snapshots when a concept label or accepted alias matches the query terms. |
| `graph` | Source chunks attached to traversable assertion or hierarchy edges incident to matching concept nodes. Graph evidence must come from an in-scope document whose latest ready NCM revision matches the graph revision. |
| `dense` | Cosine similarity using the pinned optional MiniLM CPU embeddings. The service encodes primary chunks in batches on demand. |

The first four methods are enabled by default. Choose individual methods with `methods`, adjust their relative contributions with `weights`, or filter the corpus by `document_ids` and `element_types`. Unknown document IDs yield no hits unless another requested ID matches. BM25 statistics are calculated over the filtered corpus. Reciprocal rank fusion combines ranks with equal default weights. A small lexical-coverage bonus reranks fused scores by default. Set `rerank` to false for an unmodified fusion ranking. A nonzero `diversity` value enables maximal marginal relevance using token-set similarity on the first 100 candidates.

Each hit carries its document and chunk IDs, filename, structural locator, section path, exact excerpt and source offsets, per-method scores, and a source endpoint that independently returns the excerpt. Invalid candidate sources are omitted. Diagnostics include candidate counts per method, corpus size, ranked candidate count, invalid sources encountered while filling the result page, graph version when usable, dense input truncation count, and server duration. Scores are ranking signals. Relevance and source fidelity do not establish that an excerpt supports a proposed answer.

The model-free path supports up to 5,000 chunks per request. Dense requests support up to 256 chunks and require the optional runtime and pinned embedding assets. Use filters to narrow a larger corpus. A missing dense model returns `503 model_unavailable`. Graph scoring is skipped when an eligible graph is unavailable or exceeds 10,000 nodes or edges. Search holds a consistent SQLite read transaction. It builds rankings on demand and introduces no background indexing or stored embeddings. A cross-encoder, persistent vector indexing, and large-corpus validation remain future work.

## Reproduce the benchmark

From the repository root on Linux, run the small model-free corpus or compare both corpus sizes using the optional model. See the NLP guide for installing the `embedding` asset.

```sh
uv run --project backend --frozen python scripts/eval_retrieval.py
uv run --project backend --frozen --extra nlp python scripts/eval_retrieval.py \
  --models backend/.local/nlp-models
uv run --project backend --frozen --extra nlp python scripts/eval_retrieval.py \
  --models backend/.local/nlp-models --distractors 24
```

The benchmark uploads the frozen fixture through the API, waits for graph publication, compares each retrieval method and selected fusions, and checks all returned excerpts against their source endpoints. It reports recall and mean reciprocal rank at five, server-side p50/p95 duration, and peak process memory. The eight annotated queries and synthetic distractors form a small technical smoke benchmark. Corpus-scale and independent evaluation remain open.
