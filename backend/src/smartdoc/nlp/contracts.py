from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from smartdoc.structure.contracts import SourceSpan


class TextSpan(BaseModel):
    start: int
    end: int
    text: str


class LinguisticToken(BaseModel):
    span: TextSpan
    normalized: str
    lemma: str | None = None
    pos: str | None = None
    dependency: str | None = None
    head: int | None = None


class NamedSpan(BaseModel):
    span: TextSpan
    label: str
    method: str


class TemporalSpan(BaseModel):
    span: TextSpan
    kind: Literal["date", "time", "relative"]
    normalized: str | None


class RelationCandidate(BaseModel):
    subject: TextSpan
    predicate: TextSpan
    object: TextSpan
    evidence: TextSpan
    type: str
    negated: bool
    modality: str | None
    method: Literal["lexical-pattern", "dependency-pattern"]


class Role(BaseModel):
    label: str
    span: TextSpan


class PredicateFrame(BaseModel):
    predicate: TextSpan
    arguments: list[Role]
    negated: bool
    modality: str | None
    method: str


class CoreferenceCandidate(BaseModel):
    mention: TextSpan
    antecedent: TextSpan | None
    alternatives: list[TextSpan]
    status: Literal["candidate", "ambiguous", "unresolved"]


class Annotation(BaseModel):
    chunk_id: UUID
    source: SourceSpan
    language: Literal["en", "und"]
    method: str
    warnings: list[str]
    sentences: list[TextSpan]
    tokens: list[LinguisticToken]
    entities: list[NamedSpan]
    phrases: list[NamedSpan]
    temporal: list[TemporalSpan]
    relations: list[RelationCandidate]
    frames: list[PredicateFrame]
    coreferences: list[CoreferenceCandidate]
