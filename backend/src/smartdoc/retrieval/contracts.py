from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from smartdoc.structure.contracts import ElementKind, Evidence, Locator, SectionRef

Method = Literal["bm25", "structure", "concept", "graph", "dense"]
DEFAULT_METHODS: list[Method] = ["bm25", "structure", "concept", "graph"]


class SearchQuery(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
    methods: list[Method] = Field(default_factory=DEFAULT_METHODS.copy, min_length=1, max_length=5)
    weights: dict[Method, Annotated[float, Field(ge=0, le=10)]] = Field(default_factory=dict)
    document_ids: list[UUID] = Field(default_factory=list, max_length=50)
    element_types: list[ElementKind] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=10, ge=1, le=50)
    rerank: bool = True
    diversity: float = Field(default=0, ge=0, le=0.5)


class SearchHit(BaseModel):
    document_id: UUID
    filename: str
    chunk_id: UUID
    locator: Locator
    section_path: list[SectionRef]
    element_type: ElementKind
    evidence: Evidence
    source_url: str
    score: float
    method_scores: dict[Method, float]


class SearchDiagnostics(BaseModel):
    query_terms: list[str]
    methods: list[Method]
    candidate_counts: dict[Method, int]
    corpus_chunks: int
    ranked_candidates: int
    invalid_sources: int
    duration_ms: float
    graph_version: UUID | None
    dense_truncated: int = 0


class SearchResponse(BaseModel):
    items: list[SearchHit]
    diagnostics: SearchDiagnostics
