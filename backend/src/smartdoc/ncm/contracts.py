from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from smartdoc.structure.contracts import Locator, SourceSpan

NCM_VERSION = "ncm-v1"
RelationType = Literal[
    "IS_A",
    "PART_OF",
    "HAS_PART",
    "DEPENDS_ON",
    "REQUIRES",
    "CAUSED_BY",
    "LEADS_TO",
    "IMPLEMENTS",
    "USES",
    "PRODUCES",
    "MEASURES",
    "COMPARED_WITH",
    "CONTRADICTS",
    "SUPPORTS",
    "DEFINED_BY",
    "DERIVED_FROM",
    "ASSOCIATED_WITH",
    "PRECEDES",
    "FOLLOWS",
    "INSTANCE_OF",
    "HAS_ATTRIBUTE",
]
Validation = Literal["source_validated", "needs_review", "conflicted", "rejected"]
MentionKind = Literal[
    "heading", "table", "list", "caption", "entity", "phrase", "relation", "alias"
]


class Anchor(BaseModel):
    document_id: UUID
    extraction_job_id: UUID
    chunk_id: UUID
    source: SourceSpan
    locator: Locator
    text: str


class Mention(BaseModel):
    evidence: Anchor
    kind: MentionKind
    label: str | None = None
    lemma_form: str | None = None
    section_id: UUID | None = None
    parent_section_id: UUID | None = None


class Weights(BaseModel):
    definition: float = Field(3, ge=0, le=20)
    heading: float = Field(2, ge=0, le=20)
    relation: float = Field(2, ge=0, le=20)
    entity: float = Field(1, ge=0, le=20)
    frequency: float = Field(1, ge=0, le=20)


class ConceptScore(BaseModel):
    total: float
    features: dict[str, float]


class Alias(BaseModel):
    surface: str
    method: Literal["acronym", "explicit_alias", "explicit_rename", "review"]
    evidence: list[Anchor]


class AliasReview(BaseModel):
    surface: str
    alternatives: list[UUID]
    evidence: list[Anchor]


class DuplicateSuggestion(BaseModel):
    left_id: UUID
    right_id: UUID
    lexical_key: str
    evidence: list[Anchor]


class Definition(BaseModel):
    quote: Anchor
    expression: Anchor
    qualified: bool = False


class Concept(BaseModel):
    id: UUID
    label: str
    normalized: str
    category: str
    sense: str | None
    score: ConceptScore
    mentions: list[Mention]
    aliases: list[Alias] = Field(default_factory=list)
    definitions: list[Definition] = Field(default_factory=list)
    deprecation: list[Anchor] = Field(default_factory=list)


class Assertion(BaseModel):
    id: UUID
    subject_id: UUID
    object_id: UUID
    type: RelationType
    subject: Anchor
    object: Anchor
    predicate: Anchor
    evidence: Anchor
    negated: bool
    modality: str | None
    method: str
    validation: Validation
    confidence: Literal["direct_pattern", "dependency_supported"]
    created_at: datetime


class Hierarchy(BaseModel):
    child_id: UUID
    parent_id: UUID
    kind: Literal["section", "is_a", "part_of", "instance_of"]
    evidence: list[Anchor]
    assertion_id: UUID | None = None


class Snapshot(BaseModel):
    document_id: UUID
    concepts: list[Concept]
    assertions: list[Assertion]
    hierarchy: list[Hierarchy]
    ambiguous_aliases: list[AliasReview]
    duplicate_candidates: list[DuplicateSuggestion] = Field(default_factory=list)
    rejected_candidates: int = 0
