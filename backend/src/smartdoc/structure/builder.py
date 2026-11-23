import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from smartdoc.chunking.partition import DEFAULT_POLICY, ChunkPolicy, make_chunks
from smartdoc.ingestion.contracts import Extraction, ExtractionError, SourceUnit
from smartdoc.structure.contracts import (
    STRUCTURE_VERSION,
    Chunk,
    Element,
    ElementKind,
    FieldPath,
    Locator,
    SectionRef,
    SourceSpan,
)
from smartdoc.structure.text_blocks import Block, markdown_blocks, plain_blocks, sentences

MAX_ELEMENTS = 130_000
MAX_CHUNKS = 100_000
HEADING_MARKER = re.compile(r"^ {0,3}#{1,6}\s+")
SETEXT_MARKER = re.compile(r"^[=\-]+$")


@dataclass
class Structure:
    elements: list[Element]
    chunks: list[Chunk]


@dataclass(frozen=True)
class TableSource:
    unit: int
    field: FieldPath
    rows: list
    locator: Locator


def recorded_hints(source: SourceUnit) -> list[Block]:
    return [
        Block(
            item["kind"], item["start"], item["end"], item.get("level", 0), item.get("table_number")
        )
        for item in source.data.get("structure_hints", [])
        if 0 <= item["start"] < item["end"] <= len(source.text)
    ]


class StructureBuilder:
    def __init__(
        self,
        document_id: UUID,
        job_id: UUID,
        created_at: datetime,
        policy: ChunkPolicy,
    ) -> None:
        self.document_id = document_id
        self.namespace = uuid5(job_id, STRUCTURE_VERSION)
        self.created_at = created_at
        self.policy = policy
        self.elements: list[Element] = []
        self.chunks: list[Chunk] = []
        self.sections: list[SectionRef] = []
        self.section_nodes: dict[UUID, Element] = {}
        self.nested_lists: dict[UUID, Element] = {}
        self.root = self.element("document", None, identity="root")
        self.slide = self.root
        self.slide_title_shape = None
        self.slide_title = ""
        self.list_parent: Element | None = None
        self.list_items: list[tuple[int, Element]] = []

    def element(
        self,
        kind: ElementKind,
        parent: Element | None,
        *,
        identity: str,
        locator: Locator | None = None,
        source: SourceSpan | None = None,
        label: str | None = None,
    ) -> Element:
        if len(self.elements) >= MAX_ELEMENTS:
            raise ExtractionError(
                "structure_limit", "The document exceeds the structural element limit."
            )
        origin = source.model_dump(mode="json") if source else None
        element = Element(
            id=uuid5(
                self.namespace,
                json.dumps(
                    [kind, str(parent.id) if parent else None, identity, origin],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
            parent_id=parent.id if parent else None,
            ordinal=len(self.elements) + 1,
            kind=kind,
            locator=locator or {},
            section_path=self.sections.copy(),
            source=source,
            label=label,
        )
        self.elements.append(element)
        return element

    def anchored(
        self,
        parent: Element,
        kind: ElementKind,
        unit: int,
        path: FieldPath,
        value: str | int | float | bool,
        locator: Locator,
        *,
        start: int = 0,
        end: int | None = None,
        chunk: bool = True,
    ) -> Element | None:
        text = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
        end = len(text) if end is None else end
        if end <= start or not text[start:end].strip():
            return None
        snippet = text[start:end]
        source = SourceSpan(
            unit=unit,
            field=path,
            start=start,
            end=end,
            projection="text" if isinstance(value, str) else "json_scalar",
        )
        element = self.element(kind, parent, identity="", locator=locator, source=source)
        if chunk:
            for item in make_chunks(
                self.document_id,
                element,
                snippet,
                len(self.chunks) + 1,
                self.created_at,
                self.policy,
            ):
                if len(self.chunks) >= MAX_CHUNKS:
                    raise ExtractionError(
                        "structure_limit", "The document exceeds the chunk limit."
                    )
                self.chunks.append(item)
        if kind == "paragraph":
            for sentence in sentences(snippet, start):
                self.element(
                    "sentence",
                    element,
                    identity="",
                    locator=locator,
                    source=source.model_copy(update={"start": sentence.start, "end": sentence.end}),
                )
        return element

    def heading(
        self,
        container: Element,
        unit: int,
        value: str,
        block: Block,
        locator: Locator,
        field: FieldPath,
    ) -> None:
        level = min(max(block.level, 1), 6)
        while self.sections and self.sections[-1].level >= level:
            self.sections.pop()
        parent = self.parent_for_section(container)
        lines = HEADING_MARKER.sub("", value[block.start : block.end]).strip().splitlines()
        if len(lines) > 1 and SETEXT_MARKER.fullmatch(lines[-1].strip()):
            lines.pop()
        label = " ".join(lines)[:160]
        section = self.element(
            "section",
            parent,
            identity=f"{unit}:{field}:{block.start}",
            locator=locator,
            label=label,
        )
        self.section_nodes[section.id] = section
        self.sections.append(SectionRef(id=section.id, title=label, level=level))
        self.anchored(
            section, "heading", unit, field, value, locator, start=block.start, end=block.end
        )

    def parent_for_section(self, container: Element) -> Element:
        if container.kind not in {"document", "page"}:
            return container
        if not self.sections:
            return container
        return self.section_nodes[self.sections[-1].id]

    def reset_list(self) -> None:
        self.list_parent = None
        self.list_items.clear()

    def list_item(
        self,
        parent: Element,
        unit: int,
        field: FieldPath,
        value: str,
        block: Block,
        locator: Locator,
    ) -> None:
        while self.list_items and self.list_items[-1][0] >= block.level:
            self.list_items.pop()
        if self.list_items:
            current = self.list_items[-1][1]
            if self.nested_lists.get(current.id) is None:
                self.nested_lists[current.id] = self.element(
                    "list", current, identity=f"{unit}:{block.start}", locator=locator
                )
            parent = self.nested_lists[current.id]
        else:
            if self.list_parent is None:
                self.list_parent = self.element(
                    "list", parent, identity=f"{unit}:{block.start}", locator=locator
                )
            parent = self.list_parent
        element = self.anchored(
            parent, "list_item", unit, field, value, locator, start=block.start, end=block.end
        )
        if element:
            self.list_items.append((block.level, element))

    def text_blocks(
        self,
        parent: Element,
        unit: int,
        path: FieldPath,
        value: str,
        blocks: Iterable[Block],
        locator: Locator,
        tables: dict[int, TableSource] | None = None,
    ) -> None:
        previous_end = None
        for block in blocks:
            if block.kind == "list_item":
                if previous_end is not None and value[previous_end : block.start].count("\n") > 1:
                    self.reset_list()
                self.list_item(self.parent_for_section(parent), unit, path, value, block, locator)
                previous_end = block.end
                continue
            self.reset_list()
            if block.kind == "heading":
                self.heading(parent, unit, value, block, locator, path)
            elif block.kind == "table":
                if tables is not None and block.table_number in tables:
                    source = tables.pop(block.table_number)
                    self.table(
                        self.parent_for_section(parent),
                        source.unit,
                        source.field,
                        source.rows,
                        source.locator,
                    )
            else:
                self.anchored(
                    self.parent_for_section(parent),
                    block.kind,
                    unit,
                    path,
                    value,
                    locator,
                    start=block.start,
                    end=block.end,
                )
            previous_end = block.end

    def table(
        self,
        parent: Element,
        unit: int,
        path: FieldPath,
        rows: list,
        locator: Locator,
        *,
        csv: bool = False,
    ) -> None:
        table = self.element("table", parent, identity=f"{unit}:{path}", locator=locator)
        for index, record in enumerate(rows):
            row_number = record["row"] if csv else index + 1
            cells = record["cells"] if csv else record
            row_locator = {**locator, "row": row_number}
            row = self.element("table_row", table, identity=str(index), locator=row_locator)
            for offset, value in enumerate(cells):
                cell_path = (*path, index, "cells", offset) if csv else (*path, index, offset)
                cell_locator = {**row_locator, "column": offset + 1}
                self.cell(row, unit, cell_path, value, cell_locator)

    def cell(
        self,
        row: Element,
        unit: int,
        path: FieldPath,
        value: str | int | float | bool | None,
        locator: Locator,
    ) -> None:
        if value is not None and self.anchored(row, "table_cell", unit, path, value, locator):
            return
        self.element("table_cell", row, identity=f"{unit}:{path}", locator=locator)

    def workbook(self, unit: int, source: SourceUnit) -> None:
        from openpyxl.utils.cell import range_boundaries

        locator = source.locator
        sheet = self.element("sheet", self.root, identity=str(unit), locator=locator)
        bounds = []
        for index, definition in enumerate(source.data.get("tables", [])):
            try:
                left, top, right, bottom = range_boundaries(definition["range"])
            except (KeyError, ValueError, TypeError):
                continue
            if None in (left, top, right, bottom):
                continue
            table = self.element(
                "table",
                sheet,
                identity=str(index),
                locator={**locator, "range": definition["range"]},
                label=definition["name"],
            )
            bounds.append((left, top, right, bottom, table))
        for row_index, record in enumerate(source.data.get("rows", [])):
            number = record["row"]
            row_nodes: dict[UUID, Element] = {}
            active = [
                (left, right, table)
                for left, top, right, bottom, table in bounds
                if top <= number <= bottom
            ]
            for cell_index, item in enumerate(record["cells"]):
                column = item["column"]
                container = next(
                    (table for left, right, table in active if left <= column <= right),
                    sheet,
                )
                if container.id not in row_nodes:
                    row_nodes[container.id] = self.element(
                        "table_row",
                        container,
                        identity=str(number),
                        locator={**container.locator, "row": number},
                    )
                cell_locator = {
                    **row_nodes[container.id].locator,
                    "column": column,
                    "cell": item["cell"],
                }
                self.cell(
                    row_nodes[container.id],
                    unit,
                    ("data", "rows", row_index, "cells", cell_index, "value"),
                    item["value"],
                    cell_locator,
                )

    def unlocated_tables(self, parent: Element, tables: Iterable[TableSource]) -> None:
        sections, self.sections = self.sections, []
        try:
            for table in tables:
                self.table(parent, table.unit, table.field, table.rows, table.locator)
        finally:
            self.sections = sections

    def page(self, unit: int, source: SourceUnit) -> None:
        page = self.element("page", self.root, identity=str(unit), locator=source.locator)
        tables = {
            index: TableSource(
                unit, ("data", "tables", index - 1), rows, {**source.locator, "table": index}
            )
            for index, rows in enumerate(source.data.get("tables", []), 1)
        }
        if source.text.strip():
            self.text_blocks(
                page,
                unit,
                ("text",),
                source.text,
                plain_blocks(source.text, recorded_hints(source), page=True),
                source.locator,
                tables,
            )
        if ocr := source.data.get("ocr"):
            text = ocr.get("text", "")
            locator = {**source.locator, "layer": "ocr"}
            self.reset_list()
            self.text_blocks(
                page,
                unit,
                ("data", "ocr", "text"),
                text,
                plain_blocks(text, [], page=True),
                locator,
            )
        self.unlocated_tables(page, tables.values())

    def build(self, extraction: Extraction) -> Structure:
        markup_tables: dict[int, TableSource] = {}
        if extraction.format in {"md", "html"}:
            key = "line" if extraction.format == "md" else "table"
            markup_tables = {
                int(source.locator[key]): TableSource(
                    unit, ("data", "rows"), source.data.get("rows", []), source.locator
                )
                for unit, source in enumerate(extraction.units, 1)
                if source.kind == "table" and key in source.locator
            }
        for unit, source in enumerate(extraction.units, 1):
            locator = source.locator
            text = source.text
            if source.kind != "list_item":
                self.reset_list()
            if source.kind == "page":
                self.page(unit, source)
            elif source.kind == "slide":
                self.sections.clear()
                self.slide = self.element("slide", self.root, identity=str(unit), locator=locator)
                self.slide_title_shape = source.data.get("title_shape")
                self.slide_title = text
                self.anchored(self.slide, "heading", unit, ("text",), text, locator)
                notes = source.data.get("notes", "")
                self.anchored(
                    self.slide,
                    "paragraph",
                    unit,
                    ("data", "notes"),
                    notes,
                    {**locator, "layer": "notes"},
                )
            elif source.kind == "sheet":
                self.workbook(unit, source)
            elif source.kind == "table":
                if extraction.format in {"md", "html"}:
                    continue
                parent = self.slide if "slide" in locator else self.parent_for_section(self.root)
                self.table(
                    parent,
                    unit,
                    ("data", "rows"),
                    source.data.get("rows", []),
                    locator,
                    csv=extraction.format == "csv",
                )
            elif source.kind == "image":
                parent = self.slide if "slide" in locator else self.root
                figure = self.element(
                    "figure",
                    parent,
                    identity=str(unit),
                    locator=locator,
                    label=source.data.get("name"),
                )
                if ocr := source.data.get("ocr"):
                    self.anchored(
                        figure,
                        "paragraph",
                        unit,
                        ("data", "ocr", "text"),
                        ocr.get("text", ""),
                        {**locator, "layer": "ocr"},
                    )
            elif source.kind == "heading" and extraction.format == "md":
                # The full Markdown field retains the exact heading syntax and coordinates.
                continue
            elif source.kind == "heading" and text.strip():
                self.text_blocks(
                    self.root,
                    unit,
                    ("text",),
                    text,
                    [Block("heading", 0, len(text), source.data.get("level", 1))],
                    locator,
                )
            elif source.kind == "list_item":
                self.list_item(
                    self.parent_for_section(self.root),
                    unit,
                    ("text",),
                    text,
                    Block("list_item", 0, len(text)),
                    locator,
                )
            elif source.kind in {"document", "paragraph"}:
                parent = self.slide if "slide" in locator else self.root
                if parent.kind == "slide" and (
                    locator.get("shape") == self.slide_title_shape
                    and self.slide_title_shape is not None
                    or (
                        self.slide_title_shape is None
                        and text == self.slide_title
                        and "title" in source.data.get("shape_name", "").lower()
                    )
                ):
                    continue
                if extraction.format == "md":
                    blocks = markdown_blocks(text)
                elif extraction.format in {"json", "yaml"}:
                    blocks = iter([Block("code_block", 0, len(text))])
                else:
                    blocks = plain_blocks(text, recorded_hints(source))
                self.text_blocks(parent, unit, ("text",), text, blocks, locator, markup_tables)
        self.unlocated_tables(self.root, markup_tables.values())
        return Structure(self.elements, self.chunks)


def build_structure(
    document_id: UUID,
    job_id: UUID,
    extraction: Extraction,
    created_at: datetime,
    policy: ChunkPolicy = DEFAULT_POLICY,
) -> Structure:
    return StructureBuilder(document_id, job_id, created_at, policy).build(extraction)
