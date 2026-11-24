import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from smartdoc.ingestion.contracts import Extraction, ExtractionError

STRUCTURE_VERSION = "structure-v1"
Locator = dict[str, int | str]
FieldPath = tuple[str | int, ...]
ElementKind = Literal[
    "document",
    "page",
    "slide",
    "sheet",
    "section",
    "heading",
    "paragraph",
    "sentence",
    "table",
    "table_row",
    "table_cell",
    "list",
    "list_item",
    "figure",
    "caption",
    "footnote",
    "reference",
    "code_block",
    "math_expression",
]


class SourceSpan(BaseModel):
    unit: int = Field(ge=1)
    field: FieldPath
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    projection: Literal["text", "json_scalar"] = "text"


class SectionRef(BaseModel):
    id: UUID
    title: str
    level: int


class Element(BaseModel):
    id: UUID
    parent_id: UUID | None
    ordinal: int
    kind: ElementKind
    locator: Locator
    section_path: list[SectionRef]
    source: SourceSpan | None = None
    label: str | None = None


class Evidence(BaseModel):
    source: SourceSpan
    text: str


class Chunk(BaseModel):
    id: UUID
    document_id: UUID
    parent_element_id: UUID
    ordinal: int
    text: str
    token_count: int
    character_count: int
    locator: Locator
    section_path: list[SectionRef]
    element_type: ElementKind
    strategy: str
    primary: SourceSpan
    overlap: list[Evidence]
    created_at: datetime


def field_text(extraction: Extraction, span: SourceSpan) -> str:
    try:
        if not span.field or not 1 <= span.unit <= len(extraction.units):
            raise ValueError("Unknown source unit")
        root = span.field[0]
        if root not in {"text", "data"}:
            raise ValueError("Unknown source field")
        value = getattr(extraction.units[span.unit - 1], root)
        for key in span.field[1:]:
            if isinstance(value, list) and isinstance(key, int) and key >= 0:
                value = value[key]
            elif isinstance(value, dict) and isinstance(key, str):
                value = value[key]
            else:
                raise ValueError("Invalid source field path")
        if span.projection == "text" and isinstance(value, str):
            return value
        if span.projection == "json_scalar" and type(value) in {bool, int, float}:
            return json.dumps(value, allow_nan=False)
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise ExtractionError(
            "invalid_provenance", "The recorded source field is unavailable."
        ) from error
    raise ExtractionError("invalid_provenance", "The recorded source field is unavailable.")


def resolve_span(extraction: Extraction, span: SourceSpan) -> str:
    text = field_text(extraction, span)
    if not 0 <= span.start < span.end <= len(text):
        raise ExtractionError("invalid_provenance", "The recorded source range is invalid.")
    return text[span.start : span.end]


def verify_chunk_source(extraction: Extraction, chunk: Chunk) -> Evidence:
    primary = resolve_span(extraction, chunk.primary)
    if primary != chunk.text or any(
        resolve_span(extraction, overlap.source) != overlap.text for overlap in chunk.overlap
    ):
        raise ExtractionError("invalid_provenance", "The chunk does not match its recorded source.")
    return Evidence(source=chunk.primary, text=primary)
