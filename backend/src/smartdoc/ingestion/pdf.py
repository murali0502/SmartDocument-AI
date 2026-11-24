import csv
import io
import os
import shutil
import subprocess
from functools import cache
from importlib.metadata import version
from math import sqrt
from pathlib import Path
from time import monotonic

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
    deadline = monotonic() + 15
    lines = recognize_lines(executable, image, 3, timeout=12)
    if image.width >= 1700:
        lines = refine_lines(executable, image, lines, deadline)
    words = [word for line in lines for word in line]
    return {
        "text": "\n".join(" ".join(word["text"] for word in line) for line in lines),
        "words": words,
        "width": image.width,
        "height": image.height,
        "coordinate_unit": "pixel",
        "engine": "tesseract",
        "engine_version": tesseract_version(executable),
        "language": "eng",
    }


def recognize_lines(
    executable: str, image: Image.Image, mode: int, *, timeout: float
) -> list[list[dict]]:
    buffer = io.BytesIO()
    if image.mode in {"L", "RGB"}:
        image.save(buffer, format="PNG")
    else:
        with image.convert("RGB") as rgb:
            rgb.save(buffer, format="PNG")
    try:
        process = subprocess.run(
            [
                executable,
                "stdin",
                "stdout",
                "-l",
                "eng",
                "--psm",
                str(mode),
                "-c",
                "tessedit_create_tsv=1",
            ],
            input=buffer.getvalue(),
            capture_output=True,
            check=True,
            timeout=timeout,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except subprocess.TimeoutExpired as error:
        raise ExtractionError("ocr_timeout", "A page exceeded the OCR time limit.") from error
    except (OSError, subprocess.CalledProcessError) as error:
        raise ExtractionError("ocr_failed", "The OCR engine could not process the page.") from error

    lines: dict[tuple[str, str, str], list[dict]] = {}
    rows = csv.DictReader(
        io.StringIO(process.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE
    )
    for row in rows:
        if row["level"] != "5" or not row["text"] or not row["text"].strip():
            continue
        word = row["text"]
        key = (row["block_num"], row["par_num"], row["line_num"])
        lines.setdefault(key, []).append(
            {
                "text": word,
                "confidence": float(row["conf"]),
                "x": int(row["left"]),
                "y": int(row["top"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
            }
        )
    return list(lines.values())


def refine_lines(
    executable: str, image: Image.Image, lines: list[list[dict]], deadline: float
) -> list[list[dict]]:
    refreshed = list(lines)
    attempts = 0
    for index, line in enumerate(lines):
        if attempts >= 4 or deadline - monotonic() < 1:
            break
        if not 4 <= len(line) <= 15 or min(word["confidence"] for word in line) >= 35:
            continue
        if sum(word["text"].isalpha() for word in line) < len(line) - 1:
            continue
        left = max(0, min(word["x"] for word in line) - 5)
        top = max(0, min(word["y"] for word in line) - 5)
        right = min(image.width, max(word["x"] + word["width"] for word in line) + 5)
        bottom = min(image.height, max(word["y"] + word["height"] for word in line))
        if right - left < 45 or not 16 <= bottom - top <= 84:
            continue
        attempts += 1
        with image.crop((left, top, right, bottom)) as crop:
            width = min(1800, (right - left) * 2)
            with crop.convert("L").resize((width, 100)) as scaled:
                guesses = [line]
                for threshold in (185, 0):
                    if deadline - monotonic() < 0.5:
                        break
                    with (
                        (
                            scaled.point(lambda pixel, limit=threshold: 255 if pixel > limit else 0)
                            if threshold
                            else scaled.copy()
                        ) as variant,
                        ImageOps.expand(variant, border=18, fill=255) as padded,
                    ):
                        try:
                            result = recognize_lines(
                                executable, padded, 7, timeout=min(2.0, deadline - monotonic())
                            )
                        except ExtractionError:
                            continue
                        if len(result) != 1 or len(result[0]) != len(line):
                            continue
                        mapped = []
                        for word in result[0]:
                            x = max(0, word["x"] - 18)
                            y = max(0, word["y"] - 18)
                            if x >= width or y >= 100:
                                break
                            mapped.append(
                                {
                                    **word,
                                    "x": left + round(x * (right - left) / width),
                                    "y": top + round(y * (bottom - top) / 100),
                                    "width": max(
                                        1,
                                        round(
                                            min(word["width"], width - x) * (right - left) / width
                                        ),
                                    ),
                                    "height": max(
                                        1,
                                        round(min(word["height"], 100 - y) * (bottom - top) / 100),
                                    ),
                                }
                            )
                        if len(mapped) == len(line):
                            guesses.append(mapped)

                def score(words):
                    return sum(word["confidence"] for word in words)

                best = max(guesses, key=score)
                if score(best) - score(line) >= 5 * len(line):
                    refreshed[index] = best
    return refreshed


def _pdf_ocr(document, index: int) -> dict:
    page = document[index]
    try:
        width, height = page.get_size()
        scale = min(4.0, sqrt(MAX_PIXELS * 0.9 / (width * height)))
        bitmap = page.render(scale=scale)
        try:
            image = bitmap.to_pil()
            try:
                with (
                    image.convert("L") as grayscale,
                    ImageOps.autocontrast(grayscale, cutoff=(1, 5)) as enhanced,
                ):
                    return recognize(enhanced)
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
