import re
from collections.abc import Iterator
from dataclasses import dataclass

from markdown_it import MarkdownIt

from smartdoc.chunking.partition import SENTENCE_END
from smartdoc.structure.contracts import ElementKind

NEWLINE = re.compile(r"\r\n|\r|\n")
NEWLINE_TOKEN = r"(?:\r\n|\r(?!\n)|(?<!\r)\n)"
PARAGRAPH_BREAK = re.compile(rf"{NEWLINE_TOKEN}(?:[ \t]*{NEWLINE_TOKEN})+")
LIST = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S")
EXPLICIT_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+\S")
NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)+|\d+\.)[ \t]+[A-Z]")
CAPTION = re.compile(r"^(?:Figure|Fig\.|Table)\s+\d+\b", re.I)
REFERENCE = re.compile(r"^\[\d+\]\s+\S")


@dataclass(frozen=True)
class Block:
    kind: ElementKind
    start: int
    end: int
    level: int = 0
    table_number: int | None = None


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _paragraphs(text: str, start: int, end: int) -> Iterator[Block]:
    cursor = start
    for separator in PARAGRAPH_BREAK.finditer(text, start, end):
        begin, stop = _trim(text, cursor, separator.start())
        if begin < stop:
            yield Block("paragraph", begin, stop)
        cursor = separator.end()
    begin, stop = _trim(text, cursor, end)
    if begin < stop:
        yield Block("paragraph", begin, stop)


def plain_blocks(text: str, hints: list[Block], *, page: bool = False) -> Iterator[Block]:
    cursor = 0
    for hint in sorted(hints, key=lambda item: item.start):
        if hint.start < cursor:
            continue
        yield from _plain_unhinted(text, cursor, hint.start, page=page)
        yield hint
        cursor = hint.end
    yield from _plain_unhinted(text, cursor, len(text), page=page)


def _plain_unhinted(text: str, cursor: int, limit: int, *, page: bool) -> Iterator[Block]:
    lines = [cursor, *(newline.end() for newline in NEWLINE.finditer(text, cursor, limit))]
    lines.append(limit)
    for begin, stop in zip(lines, lines[1:], strict=False):
        start, end = _trim(text, begin, stop)
        if start >= end or start < cursor:
            continue
        value = text[start:end]
        if prefix := EXPLICIT_HEADING.match(value):
            yield from _paragraphs(text, cursor, start)
            yield Block("heading", start, end, len(prefix[1]))
        elif (
            page
            and len(value) <= 95
            and (
                (value.isupper() and sum(ch.isalpha() for ch in value) >= 4)
                or (NUMBERED_HEADING.match(value) and "." in value.split()[0].rstrip("."))
            )
        ):
            yield from _paragraphs(text, cursor, start)
            match = NUMBERED_HEADING.match(value)
            level = len(match[1].rstrip(".").split(".")) if match else 1
            yield Block("heading", start, end, min(level, 6))
        elif LIST.match(value):
            yield from _paragraphs(text, cursor, start)
            yield Block("list_item", start, end)
        elif CAPTION.match(value) or REFERENCE.match(value):
            yield from _paragraphs(text, cursor, start)
            yield Block("caption" if CAPTION.match(value) else "reference", start, end)
        else:
            continue
        cursor = end
    yield from _paragraphs(text, cursor, limit)


def markdown_blocks(text: str) -> Iterator[Block]:
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    offsets = [0, *(newline.end() for newline in NEWLINE.finditer(text))]
    offsets.append(len(text))
    covered_paragraphs: set[int] = set()
    for index, token in enumerate(tokens):
        if token.map is None:
            continue
        first_line, last_line = token.map
        start, end = offsets[first_line], offsets[last_line]
        if token.type == "heading_open":
            yield Block("heading", *_trim(text, start, end), int(token.tag[1:]))
        elif token.type == "table_open":
            yield Block("table", start, end, table_number=first_line + 1)
        elif token.type == "list_item_open":
            child = tokens[index + 1]
            if child.type == "paragraph_open" and child.map is not None:
                end = offsets[child.map[1]]
                covered_paragraphs.add(index + 1)
            else:
                end = offsets[first_line + 1]
            yield Block("list_item", *_trim(text, start, end), token.level)
        elif token.type in {"fence", "code_block", "html_block"}:
            kind = (
                "math_expression"
                if token.info.strip() in {"math", "latex", "tex"}
                else "code_block"
            )
            yield Block(kind, start, end)
        elif token.type == "paragraph_open" and index not in covered_paragraphs:
            inline = tokens[index + 1]
            stripped = inline.content.strip()
            if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
                kind = "math_expression"
            elif stripped.startswith("[^") and "]:" in stripped:
                kind = "footnote"
            elif (
                inline.children and len(inline.children) == 1 and inline.children[0].type == "image"
            ):
                kind = "figure"
            elif CAPTION.match(stripped):
                kind = "caption"
            elif REFERENCE.match(stripped):
                kind = "reference"
            else:
                kind = "paragraph"
            begin, stop = _trim(text, start, end)
            yield Block(kind, begin, stop)


def sentences(text: str, source_start: int) -> Iterator[Block]:
    start = 0
    for stop in [*(match.end() for match in SENTENCE_END.finditer(text)), len(text)]:
        begin, end = _trim(text, start, stop)
        if begin < end:
            yield Block("sentence", source_start + begin, source_start + end)
        start = stop
