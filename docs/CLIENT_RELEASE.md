# SmartDoc AI client release

Open the main application and sign in with the workspace credentials. Use **Ask SmartDoc** to upload a document, wait for processing, ask a question and inspect its sources. Ask “Summarize this document” for cited excerpts. Ask “How does the pump depend on the valve?” for a source-backed dependency chain when the document graph contains that path. Date questions and electrical unit conversions require a directly stated date or an unambiguous compatible measurement.

Use **Documents** for extracted passages, structured fields and concept revisions. **Concepts**, **Knowledge graph** and **Compare** expose source-backed relationships and differences. **Analytics** shows graph coverage and disconnected concepts that may merit review. **Evaluation** displays the packaged result from the reproducible synthetic benchmark below. **Settings** controls theme and interface motion for the current browser.

## Hosted operation

Deploy the Dockerfile as one instance over HTTPS and mount persistent storage at `/data`. Configure `SMARTDOC_HOSTED_PASSWORD` in the host secret settings. The service uses a shared workspace for the trusted client team. Keep the readiness URL at `/api/v1/health/ready`. Railway logs expose request IDs, route templates, response status, and request duration for troubleshooting.

Back up or restore into a fresh directory with the snapshot utility. It copies SQLite through its online backup API, checks database integrity, and verifies the SHA-256 digest of each copied original. Use an authorized shell with access to both the database and its originals. Keep snapshots in private storage outside the service volume.

```sh
python scripts/snapshot_workspace.py \
  --database /data/smartdoc.sqlite3 --storage /data/uploads \
  --destination /backups/smartdoc-snapshot

python scripts/snapshot_workspace.py \
  --database /backups/smartdoc-snapshot/smartdoc.sqlite3 \
  --storage /backups/smartdoc-snapshot/uploads \
  --destination /restore/smartdoc
```

Start a separate service against the restored SQLite file and uploads directory. Check readiness, list documents, and download a known original before any production cutover.

## Evidence and limits

On the frozen synthetic fixture (six documents, eight questions, 17 chunks), the keyword baseline achieved 87.5% recall@5 and 0.750 MRR@5. Model-free reranked search achieved 100% recall@5 and 0.729 MRR@5. The measured service-side median was 5.04 ms for reranked search, with peak benchmark-process memory of 97.8 MiB. The fixture is an engineering check. It does not establish accuracy or capacity on the client’s corpus.

Run the benchmark from the repository root with `uv run --project backend --frozen python scripts/eval_retrieval.py`. Review broad multilingual accuracy, optional model-assisted answer validation, large-corpus performance, and formal independent security assessment separately from this release.

## Verify a release

1. Confirm the deployment source commit in Railway and check the public readiness endpoint.
2. Confirm signed-out requests receive an authentication challenge. Sign in and use a non-sensitive fixture to verify upload, a cited answer, and original download.
3. Review Railway request logs for unexpected errors and check that the production volume is mounted. Correlate failures with the response request ID.
4. Run the automated hosted restore test. For an operations rehearsal, restore an approved snapshot into an isolated Railway service and compare document and citation results before considering a cutover.

The automated restore test snapshots an active hosted fixture, starts a separate application on the restored copy, and checks access control, original bytes, and citation fidelity. It uses temporary storage and no production documents.

## Visual Q&A for scans and images

Configure a trusted, self-hosted vision model that accepts OpenAI-compatible chat completions, image data URLs, and JSON responses. For a model server running on the same machine as the API, the settings look like this:

```sh
SMARTDOC_VISION_URL=http://127.0.0.1:11434/v1/chat/completions
SMARTDOC_VISION_MODEL=qwen2.5vl:7b
```

Use the model name installed on your server. For Railway, use the model service's private address in the same environment. The app accepts only loopback or private endpoints, disables proxy forwarding and redirects, and does not download a model. Configure model capacity and `SMARTDOC_VISION_TIMEOUT` to fit your hardware.

Scanned PDF pages and image uploads use visual Q&A from the stored originals. The model receives numbered PDF page images or image frames and returns an answer plus page references. The app checks that cited page numbers belong to the images sent and links to the original images. Model transcriptions and answers may still contain reading errors. The default page limit is eight, configurable via `SMARTDOC_VISION_MAX_PAGES` up to sixteen.

This path handles single-document Ask SmartDoc requests. It does not create an index from the model's answers, so Search, Concepts, and Knowledge Graph use native text and any previously saved OCR, rather than new image-only pages. Without a configured model, visual questions return an explicit model setup error. Before changing production settings, verify the page 1 definition and page 3 indicator table in the chemistry scan against the original page images.

## Netlify frontend with a separately hosted API

The split deployment uses the same Python container and storage layout. Deploy the API to a container host with persistent storage at `/data` and an HTTPS public origin. Configure the existing workspace password through that host's secret settings. Set `SMARTDOC_FRONTEND_ORIGIN` to the exact HTTPS origin of the production Netlify site, and configure the private vision server on the backend network.

Set `VITE_SMARTDOC_API_ORIGIN` in the Netlify build environment to the backend's HTTPS origin. This origin is public configuration. Workspace credentials are entered by users and held in browser memory until reload or sign-out. The frontend calls the backend directly so vision requests can run beyond Netlify's rewrite timeout. The backend allows authenticated requests from the configured frontend origin and rejects foreign origins for writes.

Restore an approved, hash-verified Railway snapshot into the replacement volume before switching users over. Check login, document listing, original downloads, typed answers, cited scan answers and persistence after restart. Retire Railway only after the replacement and backup both pass verification.
