import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, StringConstraints

from smartdoc.api.ingestion import require_local
from smartdoc.api.structure import ready_document
from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.persistence.ingestion_store import IngestionStore
from smartdoc.persistence.structure_store import StructureStore
from smartdoc.retrieval.contracts import SearchHit, SearchQuery
from smartdoc.retrieval.ranking import STOP, tokens
from smartdoc.retrieval.service import MAX_CHUNKS, RetrievalService
from smartdoc.retrieval.summary import SUMMARY_REQUEST, representative_excerpts
from smartdoc.structure.contracts import verify_chunk_source

router = APIRouter(
    prefix="/api/v1/workspaces/local",
    tags=["answers"],
    dependencies=[Depends(require_local)],
)


class Question(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
    document_id: UUID


class Answer(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    answer: str | None = None
    summary: list[str] = Field(default_factory=list)
    citations: list[SearchHit] = Field(default_factory=list)
    related_passages: list[SearchHit] = Field(default_factory=list)


# Supported questions require the subject to occur before an explicit predicate.
PATTERNS = (
    (r"^(?:what does|what do) (.+?) (?:require|need)\??$", r"requires?|needs?"),
    (r"^(?:what does|what do) (.+?) depend on\??$", r"depends? on"),
    (r"^(?:what is|what are|define) (.+?)\??$", r"means?|refers? to|is|are"),
)


@router.post("/ask")
def ask(question: Question, request: Request, response: Response) -> Answer:
    response.headers["Cache-Control"] = "no-store"
    if SUMMARY_REQUEST.fullmatch(question.question):
        return summarize(request, response, question.document_id)
    retrieval: RetrievalService = request.app.state.retrieval
    result = retrieval.search(
        SearchQuery(query=question.question, document_ids=[question.document_id], limit=10)
    )
    for pattern, predicate in PATTERNS:
        match = re.fullmatch(pattern, question.question, flags=re.IGNORECASE)
        if not match:
            continue
        subject = " ".join(word for word in tokens(match[1]) if word not in STOP)
        if not subject:
            break
        prefix = rf"^(?:(?:the|a|an) )?{re.escape(subject)}(?: {predicate}) "
        predicate_match = re.compile(prefix)
        negative_statement = re.compile(
            rf"^(?:(?:the|a|an) )?{re.escape(subject)} "
            rf"(?:does not|do not|doesn t|don t) (?:{predicate}) |"
            rf"^(?:(?:the|a|an) )?{re.escape(subject)} (?:is|are) not "
        )
        statements: dict[str, tuple[str, SearchHit]] = {}
        saw_negative = False
        for hit in result.items:
            for fragment in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", hit.evidence.text):
                normalized = " ".join(tokens(fragment))
                if negative_statement.match(normalized):
                    saw_negative = True
                elif predicate_match.match(normalized):
                    statements.setdefault(normalized, (fragment.strip(), hit))
        if len(statements) == 1 and not saw_negative:
            excerpt, citation = next(iter(statements.values()))
            return Answer(status="answered", answer=excerpt, citations=[citation])
        break
    return Answer(status="insufficient_evidence", related_passages=result.items[:3])


def summarize(request: Request, response: Response, document_id: UUID) -> Answer:
    state = ready_document(request, response, document_id)
    structures: StructureStore = request.app.state.structure_store
    ingestion: IngestionStore = request.app.state.ingestion_store
    original = ingestion.original(str(document_id))
    extracted = ingestion.extraction(str(document_id))
    if original is None or extracted is None or extracted[1] is None:
        raise ExtractionError("not_found", "The document source was not found.")
    chunks = structures.chunks(state.job_id, 0, MAX_CHUNKS + 1)
    if len(chunks) > MAX_CHUNKS:
        raise ExtractionError("retrieval_limit", "This document is too large to summarize at once.")
    manifest = Extraction.model_validate(extracted[1])
    summary: list[str] = []
    citations: list[SearchHit] = []
    for chunk, excerpt in representative_excerpts(chunks):
        try:
            evidence = verify_chunk_source(manifest, chunk)
        except ExtractionError:
            continue
        if chunk.document_id != document_id:
            continue
        summary.append(excerpt)
        citations.append(
            SearchHit(
                document_id=document_id,
                filename=original[1],
                chunk_id=chunk.id,
                locator=chunk.locator,
                section_path=chunk.section_path,
                element_type=chunk.element_type,
                evidence=evidence,
                source_url=f"/api/v1/workspaces/local/documents/{document_id}/chunks/{chunk.id}/source",
                score=0,
                method_scores={},
            )
        )
    if not summary:
        return Answer(status="insufficient_evidence")
    return Answer(
        status="answered", answer="\n".join(summary), summary=summary, citations=citations
    )
