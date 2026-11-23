from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from smartdoc.api.ingestion import require_local
from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.persistence.structure_store import State, StructureStore
from smartdoc.structure.contracts import Chunk, Element, Evidence, Locator, resolve_span

router = APIRouter(
    prefix="/api/v1/workspaces/local/documents/{document_id}",
    tags=["structure"],
    dependencies=[Depends(require_local)],
)
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[int, Query(ge=0, le=2_147_483_647)]


class StructureInfo(BaseModel):
    status: Literal["pending", "ready", "failed"]
    version: str | None = None
    completed_at: datetime | None = None
    element_count: int = 0
    chunk_count: int = 0
    error_code: str | None = None


class ElementPage(BaseModel):
    items: list[Element]
    next_cursor: int | None


class ChunkPage(BaseModel):
    items: list[Chunk]
    next_cursor: int | None


class ChunkSource(BaseModel):
    chunk_id: UUID
    locator: Locator
    primary: Evidence
    overlap: list[Evidence]


def document_state(request: Request, response: Response, document_id: UUID) -> State:
    store: StructureStore = request.app.state.structure_store
    state = store.state(document_id)
    if state is None:
        raise ExtractionError("not_found", "The document was not found.")
    response.headers["Cache-Control"] = "no-store"
    return state


def ready_document(request: Request, response: Response, document_id: UUID) -> State:
    state = document_state(request, response, document_id)
    if state.ingestion_status == "failed" or (state.run and state.run.status == "failed"):
        raise ExtractionError("structure_failed", "Structure is unavailable for this document.")
    if state.run is None:
        raise ExtractionError("structure_pending", "Document structure is still being prepared.")
    return state


@router.get("/structure")
def structure(request: Request, response: Response, document_id: UUID) -> StructureInfo:
    state = document_state(request, response, document_id)
    if state.run is not None:
        run = state.run
        return StructureInfo(
            status=run.status,
            version=run.version,
            completed_at=run.completed_at.replace(tzinfo=UTC),
            element_count=run.element_count,
            chunk_count=run.chunk_count,
            error_code=run.error_code,
        )
    if state.ingestion_status == "failed":
        return StructureInfo(status="failed", error_code="extraction_failed")
    return StructureInfo(status="pending")


@router.get("/elements")
def elements(
    request: Request,
    response: Response,
    document_id: UUID,
    after: Cursor = 0,
    limit: Limit = 25,
) -> ElementPage:
    state = ready_document(request, response, document_id)
    store: StructureStore = request.app.state.structure_store
    rows = store.elements(state.job_id, after, limit + 1)
    return ElementPage(
        items=rows[:limit], next_cursor=rows[limit - 1].ordinal if len(rows) > limit else None
    )


@router.get("/chunks")
def chunks(
    request: Request,
    response: Response,
    document_id: UUID,
    after: Cursor = 0,
    limit: Limit = 25,
) -> ChunkPage:
    state = ready_document(request, response, document_id)
    store: StructureStore = request.app.state.structure_store
    rows = store.chunks(state.job_id, after, limit + 1)
    return ChunkPage(
        items=rows[:limit], next_cursor=rows[limit - 1].ordinal if len(rows) > limit else None
    )


@router.get("/chunks/{chunk_id}/source")
def chunk_source(
    request: Request, response: Response, document_id: UUID, chunk_id: UUID
) -> ChunkSource:
    state = ready_document(request, response, document_id)
    store: StructureStore = request.app.state.structure_store
    result = store.source(state.job_id, chunk_id)
    if result is None:
        raise ExtractionError("not_found", "The chunk was not found.")
    chunk, manifest = result
    primary = resolve_span(manifest, chunk.primary)
    if primary != chunk.text or any(
        resolve_span(manifest, overlap.source) != overlap.text for overlap in chunk.overlap
    ):
        raise ExtractionError("invalid_provenance", "The chunk does not match its recorded source.")
    return ChunkSource(
        chunk_id=chunk.id,
        locator=chunk.locator,
        primary=Evidence(source=chunk.primary, text=primary),
        overlap=chunk.overlap,
    )
