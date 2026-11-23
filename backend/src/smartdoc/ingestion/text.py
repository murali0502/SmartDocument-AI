import csv
import io
import json
import re
from html.parser import HTMLParser
from importlib.metadata import version
from pathlib import Path

import yaml
from markdown_it import MarkdownIt

from smartdoc.ingestion.contracts import Extraction, ExtractionError, SourceUnit

MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_CELLS = 100_000
MAX_ROWS = 5000
MAX_COLUMNS = 256


def read_text(path: Path) -> tuple[str, str]:
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise ExtractionError("text_limit", "The source exceeds the text extraction limit.")
    content = path.read_bytes()
    for marks, encoding in [
        ((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"), "utf-32"),
        ((b"\xff\xfe", b"\xfe\xff"), "utf-16"),
        ((b"\xef\xbb\xbf",), "utf-8-sig"),
    ]:
        if content.startswith(marks):
            return content.decode(encoding), encoding
    try:
        return content.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return content.decode("cp1252"), "cp1252"


class HTMLDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.position = 0
        self.blocks: list[tuple[str, dict]] = []
        self.hints: list[dict] = []
        self.hidden: list[str] = []
        self.tables: list[list[list[str]]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def append(self, text: str) -> None:
        self.parts.append(text)
        self.position += len(text)

    def document_text(self) -> tuple[str, list[dict]]:
        text = "".join(self.parts)
        left = len(text) - len(text.lstrip())
        end = len(text.rstrip())
        return text.strip(), [
            {**hint, "start": max(hint["start"], left) - left, "end": min(hint["end"], end) - left}
            for hint in self.hints
            if max(hint["start"], left) < min(hint["end"], end)
        ]

    def handle_starttag(self, tag: str, _attrs: list) -> None:
        if tag in {"script", "style", "template"}:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []
            self.tables[-1].append(self.row)
        elif tag in {"th", "td"} and self.row is not None:
            self.cell = []
        if tag in {"p", "br", "li", "tr", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.append("\n")
        info: dict = {"start": self.position}
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            info.update(kind="heading", level=int(tag[1]))
        elif tag == "li":
            info["kind"] = "list_item"
        elif tag == "pre":
            info["kind"] = "code_block"
        elif tag == "table":
            info.update(kind="table", table_number=len(self.tables))
        if "kind" in info:
            self.blocks.append((tag, info))

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in {"td", "th"} and self.cell is not None and self.row is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
            self.append("\t")
        elif tag == "tr":
            self.row = None
        if self.blocks and self.blocks[-1][0] == tag:
            _, block = self.blocks.pop()
            self.hints.append({**block, "end": self.position})
            self.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.append(data)
            if self.cell is not None:
                self.cell.append(data)


def parse_text(path: Path, format: str) -> Extraction:
    text, encoding = read_text(path)
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        raise ExtractionError("file_type_mismatch", "The text contains unsupported control bytes.")
    metadata: dict = {"encoding": encoding}
    warnings = ["Legacy Windows-1252 decoding used."] if encoding == "cp1252" else []
    units = [SourceUnit(kind="document", text=text)]
    parser = "python-stdlib"
    parser_version = "1"

    if format == "csv":
        rows = []
        cells = 0
        for index, row in enumerate(csv.reader(io.StringIO(text, newline=""), strict=True), 1):
            cells += len(row)
            if index > MAX_ROWS or len(row) > MAX_COLUMNS or cells > MAX_CELLS:
                raise ExtractionError("table_limit", "The CSV exceeds extraction limits.")
            rows.append({"row": index, "cells": row})
        units = [
            SourceUnit(
                kind="table", data={"columns": rows[0]["cells"] if rows else [], "rows": rows}
            )
        ]
    elif format == "html":
        html = HTMLDocument()
        html.feed(text)
        html.close()
        normalized, hints = html.document_text()
        units = [SourceUnit(kind="document", text=normalized, data={"structure_hints": hints})]
        units.extend(
            SourceUnit(kind="table", locator={"table": idx}, data={"rows": rows})
            for idx, rows in enumerate(html.tables, 1)
        )
    elif format == "json":
        data = json.loads(text)
        metadata["root_type"] = type(data).__name__
    elif format == "yaml":
        documents = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
        metadata["documents"] = len(documents)
        metadata["root_tags"] = [doc.tag for doc in documents if doc is not None]
        parser, parser_version = "pyyaml", version("pyyaml")
    elif format == "md":
        tokens = MarkdownIt("commonmark").enable("table").parse(text)
        lines = text.splitlines(keepends=True)
        for index, token in enumerate(tokens):
            if token.type == "heading_open" and token.map:
                units.append(
                    SourceUnit(
                        kind="heading",
                        locator={"line": token.map[0] + 1},
                        text=tokens[index + 1].content,
                        data={"level": int(token.tag[1:])},
                    )
                )
            elif token.type == "table_open" and token.map:
                begin, end = token.map
                rows: list[list[str]] = []
                for child in tokens[index + 1 :]:
                    if child.type == "table_close":
                        break
                    if child.type == "tr_open":
                        rows.append([])
                    elif child.type == "inline" and rows:
                        rows[-1].append(child.content)
                units.append(
                    SourceUnit(
                        kind="table",
                        locator={"line": begin + 1},
                        text="".join(lines[begin:end]),
                        data={"rows": rows},
                    )
                )
        parser, parser_version = "markdown-it-py", version("markdown-it-py")

    return Extraction(
        format=format,
        parser=parser,
        parser_version=parser_version,
        metadata=metadata,
        units=units,
        warnings=warnings,
    )
