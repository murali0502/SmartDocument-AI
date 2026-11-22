# CPU model selection

Status: provisional selections after a small feasibility probe.

| Candidate | Disk and licensing | Recommendation |
|---|---|---|
| all-MiniLM-L6-v2 | 22.7M parameters, 384 dimensions. Apache 2.0. 23.05 MB official AVX2 ONNX artifact tested. | Provisional English CPU default. Pin model and tokenizer revisions. |
| E5-small-v2 | 33.4M parameters, 384 dimensions, MIT. 34.12 MB official AVX512 VNNI ONNX artifact tested. | Challenger. Use query and passage prefixes. Benchmark portable quantization on Windows. |
| BGE-small-en-v1.5 | 33.4M parameters, 384 dimensions, MIT. 133.1 MB official FP32 ONNX graph. | Benchmark on technical retrieval with recommended query instruction. |
| multilingual-e5-small | 117.7M parameters, MIT, ~470 MB FP32. | Optional corpus-driven workstream, including language-stratified evaluation. |
| spaCy en_core_web_sm | Small CPU tagging/parser/NER pipeline, MIT model. | Provisional standard English annotations. Benchmark domain entities, dependency rules and install footprint. |
| Stanza | Processor and language-pack costs vary, toolkit Apache 2.0. | Measure the linguistic benefit on a multilingual or difficult-domain corpus before adding runtime/model dependencies. |
| MS MARCO MiniLM L6 cross-encoder | 22.7M parameters, ~91 MB FP32 ONNX, Apache 2.0. | Optional small top-K reranker. Measure against lexical and structural scores. |
| DeBERTa-v3-small NLI | 141.9M parameters, ~568 MB FP32 ONNX. Card declares Apache 2.0. | Deferred unless it improves measured conflict triage under the CPU budget. |
| Qwen2.5-1.5B-Instruct | Apache 2.0. Official Q4_K_M GGUF 1.117 GB. | Optional local candidate through Ollama/llama.cpp. Budget 2–3 GiB runtime as an estimate at capped context and concurrency one. |
| SmolLM2-1.7B-Instruct | Apache 2.0, official unquantized safetensors 3.42 GB. | Alternative for English structured tasks. Inspect pinned GGUF provenance, size and license before download. |

Model cards and registry metadata establish artifact availability at the reviewed revision. Review dependency and model license notices, maintenance and upstream release activity before pinning. The embedding probe tested ONNX Runtime 1.32.0, CPUExecutionProvider and tokenizers 0.23.3. Six illustrative queries over 12 snippets yielded 6/6 top-one for both dense models and 4/6 for FTS5. Intra-op threads 2, inter-op 1, token cap 128, 60 single-query encodes. MiniLM/E5 warm p50 2.91/3.37 ms, p95 3.50/4.04 ms, peak process RSS 118.2/144.6 MiB, session and tokenizer load 145.1/196.4 ms, batch of 12 56.1/40.5 ms. These numbers measure the local probe, without API, corpus-scale indexing or concurrent work. The venv occupied 166 MiB. No production accuracy or SLM throughput measurement is available.

[MiniLM](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) · [E5](https://huggingface.co/intfloat/e5-small-v2) · [BGE](https://huggingface.co/BAAI/bge-small-en-v1.5) · [Multilingual E5](https://huggingface.co/intfloat/multilingual-e5-small) · [spaCy](https://spacy.io/models/en) · [Stanza](https://stanfordnlp.github.io/stanza/pipeline.html) · [Reranker](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) · [NLI](https://huggingface.co/cross-encoder/nli-deberta-v3-small) · [Qwen](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) · [SmolLM2](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct)
