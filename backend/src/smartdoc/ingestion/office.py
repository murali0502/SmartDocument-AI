from importlib.metadata import version
from pathlib import Path, PurePosixPath
from posixpath import normpath
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring

from smartdoc.ingestion.contracts import Extraction, ExtractionError, SourceUnit
from smartdoc.ingestion.text import MAX_CELLS, MAX_COLUMNS, MAX_ROWS
from smartdoc.ingestion.validation import validate_office_archive


def _docx(path: Path) -> tuple[list[SourceUnit], dict, list[str]]:
    from docx import Document
    from docx.table import Table

    document = Document(path)
    properties = document.core_properties
    metadata = {
        "title": properties.title,
        "creator": properties.author,
        "subject": properties.subject,
        "created": properties.created.isoformat() if properties.created else None,
        "modified": properties.modified.isoformat() if properties.modified else None,
    }
    units = []
    cell_count = 0
    for index, block in enumerate(document.iter_inner_content(), 1):
        locator = {"block": index}
        if isinstance(block, Table):
            cell_count += len(block.rows) * len(block.columns)
            if cell_count > MAX_CELLS:
                raise ExtractionError("table_limit", "The DOCX exceeds the table cell limit.")
            units.append(
                SourceUnit(
                    kind="table",
                    locator=locator,
                    data={"rows": [[cell.text for cell in row.cells] for row in block.rows]},
                )
            )
            continue
        style = block.style.name if block.style else ""
        suffix = style.removeprefix("Heading ") if style.startswith("Heading ") else ""
        data = {
            "style": style,
            "hyperlinks": [{"text": link.text, "url": link.url} for link in block.hyperlinks],
        }
        if suffix.isdigit():
            data["level"] = int(suffix)
            kind = "heading"
        elif style.startswith("List") or (
            block._p.pPr is not None and block._p.pPr.numPr is not None
        ):
            kind = "list_item"
        else:
            kind = "paragraph"
        units.append(SourceUnit(kind=kind, locator=locator, text=block.text, data=data))
    warnings = []
    if any(part.partname.endswith("/footnotes.xml") for part in document.part.package.parts):
        warnings.append("Footnotes remain in the original DOCX and were not extracted.")
    return units, metadata, warnings


def _sheet_tables(archive: ZipFile, worksheet_path: str) -> list[dict]:
    worksheet = PurePosixPath(worksheet_path)
    relationships = str(worksheet.parent / "_rels" / (worksheet.name + ".rels"))
    if relationships not in archive.namelist():
        return []
    tables = []
    for relationship in fromstring(archive.read(relationships)):
        if not relationship.get("Type", "").endswith("/table"):
            continue
        if relationship.get("TargetMode") == "External":
            continue
        target = relationship.get("Target", "")
        entry = target.lstrip("/") if target.startswith("/") else str(worksheet.parent / target)
        entry = normpath(entry)
        if not entry.startswith("xl/") or entry not in archive.namelist():
            continue
        table = fromstring(archive.read(entry))
        columns = [
            column.get("name", "") for column in table.findall("./{*}tableColumns/{*}tableColumn")
        ]
        tables.append(
            {
                "name": table.get("displayName", ""),
                "range": table.get("ref", ""),
                "columns": columns,
            }
        )
    return tables


def _xlsx(path: Path) -> tuple[list[SourceUnit], dict, list[str]]:
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    with path.open("rb") as source, ZipFile(path) as archive:
        workbook = load_workbook(source, read_only=True, data_only=False, keep_links=False)
        try:
            properties = workbook.properties
            metadata = {"title": properties.title, "creator": properties.creator}
            units = []
            cell_count = 0
            for sheet in workbook.worksheets:
                if (sheet.max_row or 0) > MAX_ROWS or (sheet.max_column or 0) > MAX_COLUMNS:
                    raise ExtractionError(
                        "table_limit", "The workbook exceeds row or column limits."
                    )
                tables = []
                # Read-only worksheets normally trust the declared dimensions. Recompute rows
                # from the XML so a missing or incorrect dimension cannot hide actual cells.
                sheet.reset_dimensions()
                for row_index, row in enumerate(sheet.iter_rows(), 1):
                    cell_count += len(row)
                    if row_index > MAX_ROWS or len(row) > MAX_COLUMNS or cell_count > MAX_CELLS:
                        raise ExtractionError(
                            "table_limit", "The workbook exceeds extraction limits."
                        )
                    cells = []
                    for column, cell in enumerate(row, 1):
                        value = cell.value
                        if value is None:
                            continue
                        if hasattr(value, "isoformat"):
                            value = value.isoformat()
                        elif not isinstance(value, (str, int, float, bool)):
                            value = getattr(value, "text", None) or str(value)
                        cells.append(
                            {
                                "cell": f"{get_column_letter(column)}{row_index}",
                                "column": column,
                                "type": cell.data_type,
                                "value": value,
                            }
                        )
                    if cells:
                        tables.append({"row": row_index, "cells": cells})
                units.append(
                    SourceUnit(
                        kind="sheet",
                        locator={"sheet": sheet.title},
                        data={
                            "rows": tables,
                            "tables": _sheet_tables(archive, sheet._worksheet_path),
                        },
                    )
                )
        finally:
            workbook.close()
    return units, metadata, []


def _pptx(path: Path) -> tuple[list[SourceUnit], dict, list[str]]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    with path.open("rb") as source:
        deck = Presentation(source)
    properties = deck.core_properties
    metadata = {
        "title": properties.title,
        "creator": properties.author,
        "width_emu": deck.slide_width,
        "height_emu": deck.slide_height,
    }
    units = []
    cells = 0

    def visit(shapes, slide: int) -> None:
        nonlocal cells
        for shape in shapes:
            locator = {"slide": slide, "shape": shape.shape_id}
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                visit(shape.shapes, slide)
            elif shape.has_table:
                table = shape.table
                cells += len(table.rows) * len(table.columns)
                if cells > MAX_CELLS:
                    raise ExtractionError(
                        "table_limit", "The presentation exceeds the table cell limit."
                    )
                units.append(
                    SourceUnit(
                        kind="table",
                        locator=locator,
                        data={"rows": [[cell.text for cell in row.cells] for row in table.rows]},
                    )
                )
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                units.append(SourceUnit(kind="image", locator=locator, data={"name": shape.name}))
            elif shape.has_text_frame:
                units.append(
                    SourceUnit(
                        kind="paragraph",
                        locator=locator,
                        text=shape.text,
                        data={"shape_name": shape.name},
                    )
                )

    for index, slide in enumerate(deck.slides, 1):
        title = slide.shapes.title.text if slide.shapes.title else ""
        notes = slide.notes_slide.notes_text_frame if slide.has_notes_slide else None
        units.append(
            SourceUnit(
                kind="slide",
                locator={"slide": index},
                text=title,
                data={"notes": notes.text if notes else ""},
            )
        )
        visit(slide.shapes, index)

    return units, metadata, []


def parse_office(path: Path, format: str) -> Extraction:
    validate_office_archive(path, format)
    parser, distribution = {
        "docx": (_docx, "python-docx"),
        "xlsx": (_xlsx, "openpyxl"),
        "pptx": (_pptx, "python-pptx"),
    }[format]
    units, metadata, warnings = parser(path)
    return Extraction(
        format=format,
        parser=distribution,
        parser_version=version(distribution),
        metadata=metadata,
        units=units,
        warnings=warnings,
    )
