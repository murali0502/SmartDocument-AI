from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field, StringConstraints

from smartdoc.api.ingestion import require_local
from smartdoc.api.nlp import status_for
from smartdoc.api.structure import Cursor, Limit, document_state
from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.ncm.contracts import (
    NCM_VERSION,
    AliasReview,
    Assertion,
    Concept,
    DuplicateSuggestion,
    Hierarchy,
    Snapshot,
)
from smartdoc.ncm.dependencies import DependencyView, Direction, dependency_view
from smartdoc.ncm.revisions import (
    Change,
    Chronology,
    OpposingStatements,
    compare,
    merge,
    opposing_statements,
    reject_assertion,
)
from smartdoc.persistence.ncm_models import NcmSnapshot
from smartdoc.persistence.ncm_store import NcmStore

router = APIRouter(
    prefix="/api/v1/workspaces/local", tags=["ncm"], dependencies=[Depends(require_local)]
)
DOC = "/documents/{document_id}/ncm"
Revision = Annotated[int, Query(ge=1, le=2_147_483_647)]


class SnapshotStatus(BaseModel):
    status: Literal["pending", "ready", "failed", "unavailable"]
    version: str = NCM_VERSION
    id: UUID | None = None
    revision: int | None = None
    parent_id: UUID | None = None
    completed_at: datetime | None = None
    concept_count: int = 0
    assertion_count: int = 0
    error: str | None = None
    audit: dict | None = None


class Page[T](BaseModel):
    items: list[T]
    next_cursor: int | None


def summary(row: NcmSnapshot) -> SnapshotStatus:
    return SnapshotStatus(
        status=row.status,
        version=row.version,
        id=row.id,
        revision=row.revision,
        parent_id=row.parent_id,
        completed_at=row.completed_at.replace(tzinfo=UTC),
        concept_count=row.concept_count,
        assertion_count=row.assertion_count,
        error=row.error,
        audit=row.audit,
    )


def stored_snapshot(
    request: Request, response: Response, document_id: UUID, revision: int | None
) -> tuple[NcmSnapshot, Snapshot]:
    state = document_state(request, response, document_id)
    store: NcmStore = request.app.state.ncm_store
    row = store.load(state.job_id, revision)
    if row is None:
        if revision is not None:
            raise ExtractionError("not_found", "The requested NCM revision was not found.")
        _, nlp = status_for(request, response, document_id)
        if nlp.status == "unavailable":
            raise ExtractionError("model_unavailable", "The configured NLP model is unavailable.")
        if nlp.status == "failed":
            raise ExtractionError("ncm_failed", "Upstream processing did not complete.")
        raise ExtractionError("ncm_pending", "The NCM snapshot is still being prepared.")
    return row, snapshot_value(row)


def snapshot_value(row: NcmSnapshot) -> Snapshot:
    if row.status != "ready" or row.payload is None:
        raise ExtractionError("ncm_failed", "The NCM snapshot is unavailable for this revision.")
    return Snapshot.model_validate(row.payload)


def page[T](items: list[T], after: int, limit: int) -> Page[T]:
    next_cursor = after + limit if len(items) > after + limit else None
    return Page(items=items[after : after + limit], next_cursor=next_cursor)


def concept_by_id(snapshot: Snapshot, concept_id: UUID) -> Concept:
    concept = next((item for item in snapshot.concepts if item.id == concept_id), None)
    if concept is None:
        raise ExtractionError("not_found", "The concept was not found in this revision.")
    return concept


@router.get(DOC)
def status(request: Request, response: Response, document_id: UUID) -> SnapshotStatus:
    state = document_state(request, response, document_id)
    store: NcmStore = request.app.state.ncm_store
    row = store.load(state.job_id, content=False)
    if row:
        return summary(row)
    _, nlp = status_for(request, response, document_id)
    return SnapshotStatus(
        status="pending" if nlp.status == "ready" else nlp.status, error=nlp.error_code
    )


@router.get(DOC + "/concepts")
def concepts(
    request: Request,
    response: Response,
    document_id: UUID,
    after: Cursor = 0,
    limit: Limit = 25,
    revision: Revision | None = None,
) -> Page[Concept]:
    _, snapshot = stored_snapshot(request, response, document_id, revision)
    return page(snapshot.concepts, after, limit)


@router.get(DOC + "/concepts/{concept_id}")
def concept(
    request: Request,
    response: Response,
    document_id: UUID,
    concept_id: UUID,
    revision: Revision | None = None,
) -> Concept:
    _, snapshot = stored_snapshot(request, response, document_id, revision)
    return concept_by_id(snapshot, concept_id)


@router.get(DOC + "/assertions")
def assertions(
    request: Request,
    response: Response,
    document_id: UUID,
    after: Cursor = 0,
    limit: Limit = 25,
    revision: Revision | None = None,
) -> Page[Assertion]:
    _, snapshot = stored_snapshot(request, response, document_id, revision)
    return page(snapshot.assertions, after, limit)


@router.get(DOC + "/hierarchy")
def hierarchy(
    request: Request,
    response: Response,
    document_id: UUID,
    after: Cursor = 0,
    limit: Limit = 25,
    revision: Revision | None = None,
) -> Page[Hierarchy]:
    _, snapshot = stored_snapshot(request, response, document_id, revision)
    return page(snapshot.hierarchy, after, limit)


@router.get(DOC + "/alias-candidates")
def aliases(
    request: Request,
    response: Response,
    document_id: UUID,
    after: Cursor = 0,
    limit: Limit = 25,
    revision: Revision | None = None,
) -> Page[AliasReview]:
    _, snapshot = stored_snapshot(request, response, document_id, revision)
    return page(snapshot.ambiguous_aliases, after, limit)


@router.get(DOC + "/duplicate-candidates")
def duplicates(
    request: Request,
    response: Response,
    document_id: UUID,
    after: Cursor = 0,
    limit: Limit = 25,
    revision: Revision | None = None,
) -> Page[DuplicateSuggestion]:
    _, snapshot = stored_snapshot(request, response, document_id, revision)
    return page(snapshot.duplicate_candidates, after, limit)


@router.get(DOC + "/dependencies/{concept_id}")
def dependencies(
    request: Request,
    response: Response,
    document_id: UUID,
    concept_id: UUID,
    direction: Direction = "prerequisites",
    depth: Annotated[int, Query(ge=1, le=8)] = 4,
    revision: Revision | None = None,
) -> DependencyView:
    _, snapshot = stored_snapshot(request, response, document_id, revision)
    concept_by_id(snapshot, concept_id)
    return dependency_view(snapshot.assertions, concept_id, direction, depth)


@router.get(DOC + "/revisions")
def revisions(
    request: Request, response: Response, document_id: UUID, after: Cursor = 0, limit: Limit = 25
) -> Page[SnapshotStatus]:
    state = document_state(request, response, document_id)
    store: NcmStore = request.app.state.ncm_store
    rows = store.history(state.job_id, after, limit + 1)
    return Page(
        items=[summary(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].revision if len(rows) > limit else None,
    )


class ReviewRequest(BaseModel):
    expected_revision: int = Field(ge=1, le=2_147_483_647)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class MergeRequest(ReviewRequest):
    action: Literal["merge"]
    source: UUID
    target: UUID


class RejectRequest(ReviewRequest):
    action: Literal["reject_assertion"]
    assertion_id: UUID


class RestoreRequest(ReviewRequest):
    action: Literal["restore"]
    restore_revision: int = Field(ge=1, le=2_147_483_647)


class RebuildRequest(ReviewRequest):
    action: Literal["rebuild"]


Review = Annotated[
    MergeRequest | RejectRequest | RestoreRequest | RebuildRequest, Field(discriminator="action")
]


@router.post(DOC + "/revisions", status_code=201)
def review(
    request: Request,
    response: Response,
    document_id: UUID,
    body: Review,
    local_header: Annotated[str | None, Header(alias="X-SmartDoc-Local")] = None,
) -> SnapshotStatus:
    if local_header != "1":
        raise ExtractionError("upload_header", "The X-SmartDoc-Local header must be 1.")
    state = document_state(request, response, document_id)
    store: NcmStore = request.app.state.ncm_store

    def transform(row: NcmSnapshot) -> Snapshot:
        if isinstance(body, RebuildRequest):
            return store.materialize(state.job_id, document_id)
        if isinstance(body, RestoreRequest):
            selected = store.load(state.job_id, body.restore_revision)
            if selected is None or selected.revision >= row.revision:
                raise ExtractionError("invalid_review", "Choose an earlier revision to restore.")
            return snapshot_value(selected)
        snapshot = snapshot_value(row)
        if isinstance(body, MergeRequest):
            return merge(snapshot, body.source, body.target, store.weights)
        return reject_assertion(snapshot, body.assertion_id, store.weights)

    audit = body.model_dump(mode="json", exclude={"expected_revision"})
    audit["actor"] = "local_reviewer"
    return summary(store.append(state.job_id, body.expected_revision, transform, audit))


class Comparison(BaseModel):
    chronology: Chronology
    left_revision: SnapshotStatus
    right_revision: SnapshotStatus
    changes: Page[Change]
    opposing_statements: list[OpposingStatements] = Field(default_factory=list)
    opposing_truncated: bool = False


@router.get("/ncm/compare")
def compare_documents(
    request: Request,
    response: Response,
    left: UUID,
    right: UUID,
    chronology: Chronology = "unspecified",
    left_revision: Revision | None = None,
    right_revision: Revision | None = None,
    after: Cursor = 0,
    limit: Limit = 25,
) -> Comparison:
    left_row, first = stored_snapshot(request, response, left, left_revision)
    right_row, second = stored_snapshot(request, response, right, right_revision)
    contradictions = opposing_statements(first, second, limit + 1)
    return Comparison(
        chronology=chronology,
        left_revision=summary(left_row),
        right_revision=summary(right_row),
        changes=page(compare(first, second), after, limit),
        opposing_statements=contradictions[:limit],
        opposing_truncated=len(contradictions) > limit,
    )
