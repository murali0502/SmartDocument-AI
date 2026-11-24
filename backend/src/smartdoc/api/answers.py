import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, StringConstraints

from smartdoc.api.ingestion import require_local
from smartdoc.api.structure import ready_document
from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.ncm.contracts import Snapshot
from smartdoc.persistence.graph_store import GraphStore
from smartdoc.persistence.ingestion_store import IngestionStore
from smartdoc.persistence.ncm_store import NcmStore
from smartdoc.persistence.structure_store import StructureStore
from smartdoc.retrieval.contracts import SearchHit, SearchQuery
from smartdoc.retrieval.questions import plan_question
from smartdoc.retrieval.ranking import STOP, tokens
from smartdoc.retrieval.reasoning import (
    CONVERSION_REQUEST,
    UNITS,
    convert_stated_quantity,
    relationship_path,
    stated_date_interval,
)
from smartdoc.retrieval.service import MAX_CHUNKS, RetrievalService
from smartdoc.retrieval.summary import SUMMARY_REQUEST, representative_excerpts
from smartdoc.structure.contracts import Chunk, resolve_span, verify_chunk_source

router = APIRouter(
    prefix="/api/v1/workspaces/local",
    tags=["answers"],
    dependencies=[Depends(require_local)],
)


class Question(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
    document_id: UUID


class Answer(BaseModel):
    status: Literal["answered", "insufficient_evidence", "clarification_required"]
    answer: str | None = None
    reasoning: list[str] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    citations: list[SearchHit] = Field(default_factory=list)
    related_passages: list[SearchHit] = Field(default_factory=list)


# Supported questions require the subject to occur before an explicit predicate.
PATTERNS = (
    (r"^(?:what does|what do) (.+?) (?:require|need)\??$", r"requires?|needs?"),
    (r"^(?:what does|what do) (.+?) depend on\??$", r"depends? on"),
    (
        r"^when was (.+?) (introduced|published|released|approved)\??$",
        r"was {action} (?:on|in) (?:[0-9]{4}|[a-z]+ [0-9]{1,2})",
    ),
    (r"^(?:what is|what are|define) (.+?)\??$", r"means?|refers? to|is|are"),
)


@router.post("/ask")
def ask(question: Question, request: Request, response: Response) -> Answer:
    response.headers["Cache-Control"] = "no-store"
    if SUMMARY_REQUEST.fullmatch(question.question):
        return summarize(request, response, question.document_id)
    plan = plan_question(question.question)
    retrieval: RetrievalService = request.app.state.retrieval
    if plan.intent in {"dependency", "relationship"}:
        if plan.section:
            return Answer(
                status="clarification_required",
                answer="Graph paths cover the whole document. Ask a direct question for a section.",
            )
        return explain_relationship(
            request,
            response,
            question.document_id,
            *plan.concepts,
            dependencies=plan.intent == "dependency",
        )
    if plan.intent in {"comparison", "timeline"}:
        prompts = [
            f"When was {concept} {plan.action}?"
            if plan.intent == "timeline"
            else f"What is {concept}?"
            for concept in plan.concepts
        ]
        return compare_answers(
            [
                direct_answer(retrieval, question.document_id, prompt, plan.section)
                for prompt in prompts
            ],
            timeline=plan.intent == "timeline",
        )
    return direct_answer(retrieval, question.document_id, plan.text, plan.section)


def direct_answer(
    retrieval: RetrievalService, document_id: UUID, question_text: str, section: str
) -> Answer:
    conversion = CONVERSION_REQUEST.fullmatch(question_text)
    prompt = f"What is {conversion[1]}?" if conversion else question_text
    result = retrieval.search(
        SearchQuery(query=prompt, document_ids=[document_id], limit=50 if section else 10)
    )
    passages = [
        hit
        for hit in result.items
        if not section or any(" ".join(tokens(item.title)) == section for item in hit.section_path)
    ]
    for pattern, predicate in PATTERNS:
        match = re.fullmatch(pattern, prompt, flags=re.IGNORECASE)
        if not match:
            continue
        subject_words = tokens(match[1])
        if not set(subject_words) - STOP:
            break
        subject = (
            " ".join(subject_words).removeprefix("the ").removeprefix("an ").removeprefix("a ")
        )
        dated = match.lastindex == 2
        if dated:
            predicate = predicate.replace("{action}", re.escape(match[2].casefold()))
        boundary = r"(?: |$)" if dated else " "
        prefix = rf"^(?:(?:the|a|an) )?{re.escape(subject)} (?:{predicate}){boundary}"
        predicate_match = re.compile(prefix)
        negation = (
            rf"was not {re.escape(match[2].casefold())}(?: |$)"
            if dated
            else rf"(?:(?:does not|do not|doesn t|don t) (?:{predicate}) |(?:is|are) not )"
        )
        negative_statement = re.compile(rf"^(?:(?:the|a|an) )?{re.escape(subject)} {negation}")
        statements: dict[str, tuple[str, SearchHit]] = {}
        saw_negative = False
        for hit in passages:
            for fragment in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", hit.evidence.text):
                normalized = " ".join(tokens(fragment))
                if negative_statement.match(normalized):
                    saw_negative = True
                elif predicate_match.match(normalized):
                    statements.setdefault(normalized, (fragment.strip(), hit))
        if len(statements) == 1 and not saw_negative:
            excerpt, citation = next(iter(statements.values()))
            if conversion:
                target = next(
                    (unit for unit in UNITS if unit.casefold() == conversion[2].casefold()),
                    conversion[2],
                )
                converted = convert_stated_quantity(excerpt, target)
                if converted is None:
                    return Answer(status="insufficient_evidence", related_passages=[citation])
                return Answer(
                    status="answered", answer=converted, reasoning=[excerpt], citations=[citation]
                )
            return Answer(status="answered", answer=excerpt, citations=[citation])
        if len(statements) > 1 or saw_negative and statements:
            return Answer(
                status="clarification_required",
                answer=(
                    "The document contains competing statements. "
                    "Add “in section” followed by a section title to narrow the evidence."
                ),
                related_passages=passages[:3],
            )
        break
    return Answer(status="insufficient_evidence", related_passages=passages[:3])


def compare_answers(answers: list[Answer], *, timeline: bool) -> Answer:
    citations: dict[UUID, SearchHit] = {}
    for answer in answers:
        for hit in [*answer.citations, *answer.related_passages]:
            citations[hit.chunk_id] = hit
    if any(answer.status != "answered" or not answer.answer for answer in answers):
        return Answer(
            status="clarification_required",
            answer="Check the names or add a section so I can find evidence for both sides.",
            related_passages=list(citations.values())[:4],
        )
    values = [answer.answer for answer in answers if answer.answer]
    if not timeline:
        return Answer(
            status="answered",
            answer="The document states:",
            reasoning=values,
            citations=list(citations.values()),
        )
    # Compare only stated years or full ISO dates. Year intervals preserve date precision.
    ranges = [stated_date_interval(value) for value in values]
    if ranges[0] is None or ranges[1] is None:
        return Answer(status="insufficient_evidence", related_passages=list(citations.values()))
    if ranges[0][1] < ranges[1][0]:
        first, second = values
    elif ranges[1][1] < ranges[0][0]:
        second, first = values
    else:
        return Answer(
            status="clarification_required",
            answer="The stated dates overlap at their recorded precision.",
            related_passages=list(citations.values()),
        )
    return Answer(
        status="answered",
        answer="The first event occurred earlier.",
        reasoning=[first, second],
        citations=list(citations.values()),
    )


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
            citation = cited_chunk(document_id, original[1], chunk, manifest)
        except ExtractionError:
            continue
        summary.append(excerpt)
        citations.append(citation)
    if not summary:
        return Answer(status="insufficient_evidence")
    return Answer(
        status="answered", answer="\n".join(summary), summary=summary, citations=citations
    )


def explain_relationship(
    request: Request,
    response: Response,
    document_id: UUID,
    source: str,
    target: str,
    *,
    dependencies: bool,
) -> Answer:
    state = ready_document(request, response, document_id)
    concepts: NcmStore = request.app.state.ncm_store
    row = concepts.load(state.job_id)
    if row is None or row.status != "ready" or row.payload is None:
        return Answer(status="insufficient_evidence")
    graph: GraphStore = request.app.state.graph_store
    path, nodes, ambiguous = relationship_path(
        graph,
        Snapshot.model_validate(row.payload),
        source,
        target,
        row.id,
        dependencies=dependencies,
    )
    if ambiguous:
        return Answer(
            status="clarification_required",
            answer="More than one graph concept matches. Use a more specific concept label.",
        )
    if path is None:
        return Answer(status="insufficient_evidence")
    ingestion: IngestionStore = request.app.state.ingestion_store
    original = ingestion.original(str(document_id))
    extracted = ingestion.extraction(str(document_id))
    if original is None or extracted is None or extracted[1] is None:
        return Answer(status="insufficient_evidence")
    manifest = Extraction.model_validate(extracted[1])
    structures: StructureStore = request.app.state.structure_store
    citations: dict[UUID, SearchHit] = {}
    reasoning = []
    for step in path.steps:
        edge, anchor = step.edge, step.evidence
        linked = structures.source(state.job_id, anchor.chunk_id)
        if (
            linked is None
            or anchor.document_id != document_id
            or str(anchor.extraction_job_id) != state.job_id
            or edge.source_id not in nodes
            or edge.target_id not in nodes
        ):
            return Answer(status="insufficient_evidence")
        chunk = linked[0]
        try:
            if (
                anchor.source.unit != chunk.primary.unit
                or anchor.source.field != chunk.primary.field
                or anchor.source.projection != chunk.primary.projection
                or not chunk.primary.start
                <= anchor.source.start
                < anchor.source.end
                <= chunk.primary.end
                or resolve_span(manifest, anchor.source) != anchor.text
            ):
                return Answer(status="insufficient_evidence")
            citations[chunk.id] = cited_chunk(document_id, original[1], chunk, manifest)
        except ExtractionError:
            return Answer(status="insufficient_evidence")
        relation = edge.predicate.lower().replace("_", " ")
        reasoning.append(f"{nodes[edge.source_id].label} {relation} {nodes[edge.target_id].label}.")
    return Answer(
        status="answered",
        answer=(
            "The document supports this dependency chain."
            if dependencies
            else "The document supports these connections."
        ),
        reasoning=reasoning,
        citations=list(citations.values()),
    )


def cited_chunk(document_id: UUID, filename: str, chunk: Chunk, manifest: Extraction) -> SearchHit:
    if chunk.document_id != document_id:
        raise ExtractionError("invalid_provenance", "Chunk identity differs from its source.")
    return SearchHit(
        document_id=document_id,
        filename=filename,
        chunk_id=chunk.id,
        locator=chunk.locator,
        section_path=chunk.section_path,
        element_type=chunk.element_type,
        evidence=verify_chunk_source(manifest, chunk),
        source_url=f"/api/v1/workspaces/local/documents/{document_id}/chunks/{chunk.id}/source",
        score=0,
        method_scores={},
    )
