import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, StringConstraints

from smartdoc.api.ingestion import require_local
from smartdoc.retrieval.contracts import SearchHit, SearchQuery
from smartdoc.retrieval.ranking import STOP, tokens
from smartdoc.retrieval.service import RetrievalService

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
    citations: list[SearchHit] = Field(default_factory=list)
    related_passages: list[SearchHit] = Field(default_factory=list)


# Supported questions require the subject to occur before an explicit predicate.
PATTERNS = (
    (r"^(?:what does|what do) (.+?) (?:require|need)\??$", r"requires?|needs?"),
    (r"^(?:what does|what do) (.+?) depend on\??$", r"depends? on"),
    (r"^(?:what is|what are|define) (.+?)\??$", r"means?|refers? to|is defined as|is an?|are"),
)
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|\n+")


@router.post("/ask")
def ask(question: Question, request: Request, response: Response) -> Answer:
    response.headers["Cache-Control"] = "no-store"
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
        statements: dict[str, tuple[str, SearchHit]] = {}
        for hit in result.items:
            for fragment in SENTENCE_BREAK.split(hit.evidence.text):
                if predicate_match.match(" ".join(tokens(fragment))):
                    statements.setdefault(" ".join(tokens(fragment)), (fragment.strip(), hit))
        if len(statements) == 1:
            excerpt, citation = next(iter(statements.values()))
            return Answer(status="answered", answer=excerpt, citations=[citation])
        break
    return Answer(status="insufficient_evidence", related_passages=result.items[:3])
