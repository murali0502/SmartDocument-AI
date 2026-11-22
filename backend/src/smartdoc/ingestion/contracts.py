from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class ExtractionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SourceUnit(BaseModel):
    kind: Literal[
        "document", "paragraph", "heading", "list_item", "table", "page", "slide", "sheet", "image"
    ]
    locator: dict[str, int | str] = Field(default_factory=dict)
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class Extraction(BaseModel):
    format: str
    parser: str
    parser_version: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    units: list[SourceUnit]
    warnings: list[str] = Field(default_factory=list)


class Parser(Protocol):
    def __call__(self, path: Path, format: str) -> Extraction: ...
