from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field, StringConstraints

from smartdoc.api.ingestion import require_local
from smartdoc.api.structure import Cursor, Limit, document_state
from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.nlp.assets import EMBEDDING_REPO, EMBEDDING_REVISION, NLI_REPO, NLI_REVISION
from smartdoc.nlp.contracts import Annotation
from smartdoc.nlp.inference import LocalInference
from smartdoc.nlp.pipeline import NLP_VERSION
from smartdoc.persistence.nlp_store import NlpStore

router = APIRouter(
    prefix="/api/v1/workspaces/local", tags=["nlp"], dependencies=[Depends(require_local)]
)
DOCUMENT = "/documents/{document_id}"


class NlpStatus(BaseModel):
    status: Literal["pending", "ready", "failed", "unavailable"]
    method: str
    version: str = NLP_VERSION
    annotation_count: int = 0
    completed_at: datetime | None = None
    error_code: str | None = None


class AnnotationPage(BaseModel):
    items: list[Annotation]
    next_cursor: int | None


def status_for(request: Request, response: Response, document_id: UUID) -> tuple[str, NlpStatus]:
    store: NlpStore = request.app.state.nlp_store
    state = document_state(request, response, document_id)
    method = store.pipeline.method
    if state.ingestion_status == "failed" or (state.run and state.run.status == "failed"):
        return state.job_id, NlpStatus(status="failed", method=method, error_code="upstream_failed")
    run = store.run(state.job_id) if state.run else None
    if run is not None and run.status in {"ready", "failed"}:
        return state.job_id, NlpStatus(
            status=run.status,
            method=method,
            annotation_count=run.processed,
            completed_at=run.completed_at.replace(tzinfo=UTC) if run.completed_at else None,
            error_code=run.error_code,
        )
    if state.run and not store.pipeline.available:
        return state.job_id, NlpStatus(
            status="unavailable", method=method, error_code="model_unavailable"
        )
    return state.job_id, NlpStatus(
        status="pending", method=method, annotation_count=run.processed if run else 0
    )


def ready_job(request: Request, response: Response, document_id: UUID) -> str:
    job_id, status = status_for(request, response, document_id)
    failures = {
        "pending": ("nlp_pending", "Linguistic annotations are still being prepared."),
        "failed": ("nlp_failed", "Linguistic annotations are unavailable for this document."),
        "unavailable": ("model_unavailable", "The configured linguistic model is unavailable."),
    }
    if status.status in failures:
        raise ExtractionError(*failures[status.status])
    return job_id


@router.get(DOCUMENT + "/nlp")
def nlp_status(request: Request, response: Response, document_id: UUID) -> NlpStatus:
    return status_for(request, response, document_id)[1]


@router.get(DOCUMENT + "/annotations")
def annotations(
    request: Request,
    response: Response,
    document_id: UUID,
    after: Cursor = 0,
    limit: Limit = 25,
) -> AnnotationPage:
    job_id = ready_job(request, response, document_id)
    store: NlpStore = request.app.state.nlp_store
    rows = store.page(job_id, after, limit + 1)
    return AnnotationPage(
        items=[item for _, item in rows[:limit]],
        next_cursor=rows[limit - 1][0] if len(rows) > limit else None,
    )


@router.get(DOCUMENT + "/chunks/{chunk_id}/annotation")
def annotation(
    request: Request, response: Response, document_id: UUID, chunk_id: UUID
) -> Annotation:
    job_id = ready_job(request, response, document_id)
    store: NlpStore = request.app.state.nlp_store
    value = store.annotation(job_id, chunk_id)
    if value is None:
        raise ExtractionError("not_found", "The chunk annotation was not found.")
    return value


ModelText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class EmbeddingInput(BaseModel):
    texts: list[ModelText] = Field(min_length=1, max_length=12)


class EmbeddingItem(BaseModel):
    vector: list[float]
    truncated: bool


class EmbeddingOutput(BaseModel):
    model: str = EMBEDDING_REPO
    revision: str = EMBEDDING_REVISION
    dimensions: int
    items: list[EmbeddingItem]


class NliPair(BaseModel):
    premise: ModelText
    hypothesis: ModelText


class NliInput(BaseModel):
    pairs: list[NliPair] = Field(min_length=1, max_length=8)


class NliItem(BaseModel):
    label: Literal["entailment", "contradiction", "neutral"]
    scores: dict[str, float]
    truncated: bool


class NliOutput(BaseModel):
    model: str = NLI_REPO
    revision: str = NLI_REVISION
    items: list[NliItem]


def require_model_header(value: str | None, response: Response) -> None:
    if value != "1":
        raise ExtractionError("upload_header", "The X-SmartDoc-Local header must be 1.")
    response.headers["Cache-Control"] = "no-store"


LocalHeader = Annotated[str | None, Header(alias="X-SmartDoc-Local", description="Must be 1.")]


@router.post("/nlp/embeddings")
def embeddings(
    request: Request, response: Response, body: EmbeddingInput, local_header: LocalHeader = None
) -> EmbeddingOutput:
    require_model_header(local_header, response)
    inference: LocalInference = request.app.state.local_inference
    vectors, truncated = inference.embed(body.texts)
    return EmbeddingOutput(
        dimensions=len(vectors[0]),
        items=[
            EmbeddingItem(vector=vector, truncated=flag)
            for vector, flag in zip(vectors, truncated, strict=True)
        ],
    )


@router.post("/nlp/inference")
def infer(
    request: Request, response: Response, body: NliInput, local_header: LocalHeader = None
) -> NliOutput:
    require_model_header(local_header, response)
    inference: LocalInference = request.app.state.local_inference
    scores, truncated = inference.infer([(pair.premise, pair.hypothesis) for pair in body.pairs])
    return NliOutput(
        items=[
            NliItem(label=max(item, key=item.__getitem__), scores=item, truncated=flag)
            for item, flag in zip(scores, truncated, strict=True)
        ]
    )
