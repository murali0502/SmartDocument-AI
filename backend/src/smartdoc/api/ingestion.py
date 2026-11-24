from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel
from starlette.requests import ClientDisconnect

from smartdoc.api.errors import problem
from smartdoc.application.uploads import accept_upload
from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.persistence.ingestion_models import Document, IngestionJob
from smartdoc.persistence.ingestion_store import IngestionStore

Status = Literal["queued", "running", "succeeded", "failed"]


class DocumentRecord(BaseModel):
    id: UUID
    filename: str
    format: str
    sha256: str
    size_bytes: int
    created_at: datetime


class JobRecord(BaseModel):
    id: UUID
    document_id: UUID
    status: Status
    attempts: int
    pipeline_version: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class DocumentJob(BaseModel):
    document: DocumentRecord
    job: JobRecord


class UploadReceipt(DocumentJob):
    duplicate: bool


class DocumentList(BaseModel):
    items: list[DocumentJob]
    next_cursor: UUID | None


def document_record(value: Document) -> DocumentRecord:
    return DocumentRecord(
        id=value.id,
        filename=value.filename,
        format=value.format,
        sha256=value.sha256,
        size_bytes=value.size_bytes,
        created_at=value.created_at.replace(tzinfo=UTC),
    )


def job_record(value: IngestionJob) -> JobRecord:
    return JobRecord(
        id=value.id,
        document_id=value.document_id,
        status=value.status,
        attempts=value.attempts,
        pipeline_version=value.pipeline_version,
        created_at=value.created_at.replace(tzinfo=UTC),
        started_at=value.started_at.replace(tzinfo=UTC) if value.started_at else None,
        finished_at=value.finished_at.replace(tzinfo=UTC) if value.finished_at else None,
        error_code=value.error_code,
        error_message=value.error_message,
    )


def require_local(request: Request) -> None:
    if not getattr(request.state, "hosted_workspace_authenticated", False):
        try:
            host = urlsplit(f"//{request.headers.get('host', '')}")
            valid_host = not host.username and host.hostname in {"127.0.0.1", "localhost", "::1"}
            valid_peer = request.client is not None and ip_address(request.client.host).is_loopback
        except ValueError:
            valid_host = valid_peer = False
        origin = request.headers.get("origin")
        if (
            not valid_host
            or not valid_peer
            or (origin and origin != str(request.base_url).rstrip("/"))
        ):
            raise ExtractionError(
                "local_access_only", "Document ingestion is available only to the local workspace."
            )
    if request.app.state.database_readiness.check() != "ready":
        raise ExtractionError(
            "database_not_ready", "Apply the database migrations before using ingestion."
        )


router = APIRouter(
    prefix="/api/v1/workspaces/local", tags=["ingestion"], dependencies=[Depends(require_local)]
)


async def ingestion_error(request: Request, error: ExtractionError) -> Response:
    status = {
        "unsupported_format": 415,
        "file_type_mismatch": 415,
        "content_type": 415,
        "upload_limit": 413,
        "local_access_only": 403,
        "upload_header": 403,
        "database_not_ready": 503,
        "not_found": 404,
        "extraction_pending": 409,
        "extraction_failed": 409,
        "structure_pending": 409,
        "structure_failed": 409,
        "invalid_provenance": 409,
        "nlp_pending": 409,
        "nlp_failed": 409,
        "ncm_pending": 409,
        "ncm_failed": 409,
        "graph_pending": 409,
        "graph_failed": 409,
        "graph_integrity": 409,
        "graph_query_limit": 422,
        "retrieval_limit": 422,
        "revision_conflict": 409,
        "model_unavailable": 503,
    }.get(error.code, 400)
    return problem(request, status, error.code, str(error))


@router.post(
    "/uploads",
    status_code=202,
    responses={200: {"model": UploadReceipt, "description": "This content already exists."}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(
    request: Request,
    response: Response,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    upload_header: Annotated[
        str | None, Header(alias="X-SmartDoc-Upload", description="Must be 1.")
    ] = None,
) -> UploadReceipt:
    if upload_header != "1":
        raise ExtractionError("upload_header", "The X-SmartDoc-Upload header must be 1.")
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/octet-stream"
    ):
        raise ExtractionError("content_type", "Send the raw file as application/octet-stream.")
    limit = request.app.state.settings.max_upload_bytes
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdecimal() or len(declared) > 16:
            raise ExtractionError("invalid_length", "The request has an invalid content length.")
        if int(declared) > limit:
            raise ExtractionError("upload_limit", "The upload exceeds the configured size limit.")
    try:
        document, job, duplicate = await accept_upload(
            request.app.state.ingestion_store, filename, request.stream(), limit
        )
    except ClientDisconnect as error:
        raise ExtractionError("upload_interrupted", "The upload was interrupted.") from error
    response.status_code = 200 if duplicate else 202
    response.headers["Location"] = f"{router.prefix}/jobs/{job.id}"
    response.headers["Cache-Control"] = "no-store"
    return UploadReceipt(
        document=document_record(document), job=job_record(job), duplicate=duplicate
    )


@router.get("/documents")
def documents(
    request: Request,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    after: UUID | None = None,
) -> DocumentList:
    store: IngestionStore = request.app.state.ingestion_store
    rows = store.documents(str(after) if after else "", limit + 1)
    response.headers["Cache-Control"] = "no-store"
    return DocumentList(
        items=[
            DocumentJob(document=document_record(doc), job=job_record(job))
            for doc, job in rows[:limit]
        ],
        next_cursor=rows[limit - 1][0].id if len(rows) > limit else None,
    )


@router.get("/jobs/{job_id}")
def job(request: Request, response: Response, job_id: UUID) -> JobRecord:
    store: IngestionStore = request.app.state.ingestion_store
    record = store.job(str(job_id))
    if record is None:
        raise ExtractionError("not_found", "The ingestion job was not found.")
    response.headers["Cache-Control"] = "no-store"
    return job_record(record)


@router.get("/documents/{document_id}/extraction")
def extraction(request: Request, response: Response, document_id: UUID) -> Extraction:
    store: IngestionStore = request.app.state.ingestion_store
    record = store.extraction(str(document_id))
    if record is None:
        raise ExtractionError("not_found", "The document was not found.")
    status, data = record
    if status == "failed":
        raise ExtractionError(
            "extraction_failed", "Processing failed. See the ingestion job for details."
        )
    if data is None:
        raise ExtractionError("extraction_pending", "The extraction result is still pending.")
    response.headers["Cache-Control"] = "no-store"
    return Extraction.model_validate(data)
