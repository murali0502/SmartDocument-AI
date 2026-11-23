import csv
import io
import os
import shutil
import subprocess
from functools import cache
from importlib.metadata import version
from math import sqrt
from pathlib import Path

from PIL import Image, ImageOps

from smartdoc.ingestion.contracts import Extraction, ExtractionError, SourceUnit
from smartdoc.structure.pdf_layout import page_hints

MAX_PAGES = 100
MAX_PIXELS = 12_000_000
MAX_OCR_PAGES = 20


@cache
def tesseract_version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, check=True, timeout=4
        )
        return result.stdout.decode("utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError, subprocess.SubprocessError):
        return "unknown"


def recognize(image: Image.Image) -> dict:
    executable = shutil.which(os.getenv("SMARTDOC_TESSERACT", "tesseract"))
    if not executable:
        raise ExtractionError("ocr_unavailable", "Tesseract is required for image-only pages.")
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    try:
        process = subprocess.run(
            [executable, "stdin", "stdout", "-l", "eng", "--psm", "3", "tsv"],
            input=buffer.getvalue(),
            capture_output=True,
            check=True,
            timeout=15,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except subprocess.TimeoutExpired as error:
        raise ExtractionError("ocr_timeout", "A page exceeded the OCR time limit.") from error
    except (OSError, subprocess.CalledProcessError) as error:
        raise ExtractionError("ocr_failed", "The OCR engine could not process the page.") from error

    words = []
    lines: dict[tuple[str, str, str], list[str]] = {}
    rows = csv.DictReader(
        io.StringIO(process.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE
    )
    for row in rows:
        if row["level"] != "5" or not row["text"] or not row["text"].strip():
            continue
        word = row["text"]
        words.append(
            {
                "text": word,
                "confidence": float(row["conf"]),
                "x": int(row["left"]),
                "y": int(row["top"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
            }
        )
        key = (row["block_num"], row["par_num"], row["line_num"])
        lines.setdefault(key, []).append(word)
    return {
        "text": "\n".join(" ".join(line) for line in lines.values()),
        "words": words,
        "width": image.width,
        "height": image.height,
        "coordinate_unit": "pixel",
        "engine": "tesseract",
        "engine_version": tesseract_version(executable),
        "language": "eng",
    }


def _pdf_ocr(document, index: int) -> dict:
    page = document[index]
    try:
        width, height = page.get_size()
        scale = min(2.5, sqrt(MAX_PIXELS * 0.9 / (width * height)))
        bitmap = page.render(scale=scale)
        try:
            image = bitmap.to_pil()
            try:
                return recognize(image)
            finally:
                image.close()
        finally:
            bitmap.close()
    finally:
        page.close()


def parse_pdf(path: Path, format: str) -> Extraction:
    import pdfplumber
    from pypdfium2 import PdfDocument

    units = []
    warnings = []
    ocr_pages = 0
    renderer = None
    try:
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
                if not native.strip():
                    ocr_pages += 1
                    if ocr_pages > MAX_OCR_PAGES:
                        raise ExtractionError(
                            "ocr_page_limit", "The PDF exceeds the image-only page limit."
                        )
                    try:
                        if renderer is None:
                            renderer = PdfDocument(path)
                            metadata["pdfium_version"] = version("pypdfium2")
                        data["ocr"] = _pdf_ocr(renderer, index - 1)
                        if not data["ocr"]["text"]:
                            warnings.append(f"Page {index} contains no recognized text.")
                    except ExtractionError as error:
                        warnings.append(f"Page {index}: {error}")
                units.append(
                    SourceUnit(kind="page", locator={"page": index}, text=native, data=data)
                )
                page.close()
    finally:
        if renderer is not None:
            renderer.close()

    if ocr_pages and not any(unit.text.strip() or "ocr" in unit.data for unit in units):
        raise ExtractionError(
            "ocr_incomplete", warnings[0] if warnings else "OCR could not be completed."
        )
    return Extraction(
        format=format,
        parser="pdfplumber",
        parser_version=version("pdfplumber"),
        metadata=metadata,
        units=units,
        warnings=warnings,
    )


def parse_image(path: Path, format: str) -> Extraction:
    units = []
    warnings = []
    with Image.open(path) as image:
        frames = getattr(image, "n_frames", 1)
        if frames > MAX_OCR_PAGES:
            raise ExtractionError("ocr_page_limit", "The image exceeds the frame limit.")
        for index in range(frames):
            image.seek(index)
            if image.width * image.height > MAX_PIXELS:
                raise ExtractionError("image_limit", "The decoded image exceeds the pixel limit.")
            oriented = ImageOps.exif_transpose(image)
            try:
                ocr = recognize(oriented)
                if not ocr["text"]:
                    warnings.append(f"Image {index + 1} contains no recognized text.")
            finally:
                oriented.close()
            units.append(SourceUnit(kind="image", locator={"page": index + 1}, data={"ocr": ocr}))
    return Extraction(
        format=format,
        parser="pillow+tesseract",
        parser_version=version("pillow"),
        units=units,
        warnings=warnings,
    )
