from importlib.metadata import version
from pathlib import Path

from PIL import Image

from smartdoc.ingestion.contracts import Extraction, ExtractionError, SourceUnit
from smartdoc.structure.pdf_layout import page_hints

MAX_PAGES = 100
MAX_PIXELS = 12_000_000
MAX_IMAGE_FRAMES = 20


def parse_pdf(path: Path, format: str) -> Extraction:
    import pdfplumber

    units = []
    with pdfplumber.open(path) as document:
        if len(document.pages) > MAX_PAGES:
            raise ExtractionError("page_limit", "The PDF exceeds the page limit.")
        metadata = {
            key: value
            for key, value in document.metadata.items()
            if isinstance(value, (int, float, str, bool))
        }
        metadata["pages"] = len(document.pages)
        for index, page in enumerate(document.pages, 1):
            native = page.extract_text() or ""
            tables = page.find_tables() if native else []
            data = {
                "width": float(page.width),
                "height": float(page.height),
                "coordinate_unit": "pdf_point",
                "tables": [table.extract() for table in tables],
            }
            if native.strip():
                data["structure_hints"] = page_hints(
                    native, page.extract_text_lines(), [table.bbox for table in tables]
                )
            else:
                data["vision_scan"] = True
            units.append(SourceUnit(kind="page", locator={"page": index}, text=native, data=data))
            page.close()
    return Extraction(
        format=format,
        parser="pdfplumber",
        parser_version=version("pdfplumber"),
        metadata=metadata,
        units=units,
    )


def parse_image(path: Path, format: str) -> Extraction:
    units = []
    with Image.open(path) as image:
        frames = getattr(image, "n_frames", 1)
        if frames > MAX_IMAGE_FRAMES:
            raise ExtractionError("page_limit", "The image exceeds the frame limit.")
        for index in range(frames):
            image.seek(index)
            if image.width * image.height > MAX_PIXELS:
                raise ExtractionError("image_limit", "The decoded image exceeds the pixel limit.")
            image.load()
            units.append(
                SourceUnit(
                    kind="image",
                    locator={"page": index + 1},
                    data={"vision_scan": True, "width": image.width, "height": image.height},
                )
            )
    return Extraction(format=format, parser="pillow", parser_version=version("pillow"), units=units)
