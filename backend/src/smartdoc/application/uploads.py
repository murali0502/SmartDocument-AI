from collections.abc import AsyncIterable
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import anyio
from starlette.concurrency import run_in_threadpool

from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.ingestion.validation import upload_name, validate_signature
from smartdoc.persistence.ingestion_models import Document, IngestionJob
from smartdoc.persistence.ingestion_store import IngestionStore, Upload


async def accept_upload(
    store: IngestionStore, filename: str, stream: AsyncIterable[bytes], limit: int
) -> tuple[Document, IngestionJob, bool]:
    name, format = upload_name(filename)
    spool = store.storage / ".staging"
    await run_in_threadpool(spool.mkdir, parents=True, exist_ok=True)
    with TemporaryDirectory(dir=spool) as directory:
        path = Path(directory) / "upload"
        digest = sha256()
        size = 0
        async with await anyio.open_file(path, "wb") as output:
            async for block in stream:
                size += len(block)
                if size > limit:
                    raise ExtractionError(
                        "upload_limit", "The upload exceeds the configured size limit."
                    )
                digest.update(block)
                await output.write(block)

        def commit() -> tuple[Document, IngestionJob, bool]:
            validate_signature(path, format)
            return store.accept(Upload(path, name, format, digest.hexdigest(), size))

        return await run_in_threadpool(commit)
