import base64
import io
import json
import sys
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

from PIL import Image, ImageOps
from pypdfium2 import PdfDocument, PdfiumError

from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.ingestion.extract import apply_limits
from smartdoc.ingestion.pdf import MAX_PIXELS
from smartdoc.ingestion.validation import IMAGE_SIGNATURES


def render(path: Path, pages: list[int]) -> Iterator[bytes]:
    try:
        with PdfDocument(path) as document:
            for number in pages:
                if not 1 <= number <= len(document):
                    raise ExtractionError("not_found", "The page does not exist.")
                with closing(document[number - 1]) as page:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise ExtractionError(
                            "vision_unavailable", "The PDF page could not be rendered."
                        )
                    with closing(page.render(scale=min(4, 2500 / max(width, height)))) as bitmap:
                        with bitmap.to_pil() as image, image.convert("RGB") as rgb:
                            output = io.BytesIO()
                            rgb.save(output, format="JPEG", quality=84)
                            yield output.getvalue()
    except (PdfiumError, OSError, ValueError) as error:
        raise ExtractionError(
            "vision_unavailable", "The PDF page could not be rendered."
        ) from error


def render_image(path: Path, pages: list[int]) -> Iterator[bytes]:
    try:
        with Image.open(path) as image:
            for number in pages:
                if not 1 <= number <= getattr(image, "n_frames", 1):
                    raise ExtractionError("not_found", "The image frame does not exist.")
                image.seek(number - 1)
                if image.width * image.height > MAX_PIXELS:
                    raise ExtractionError(
                        "image_limit", "The decoded image exceeds the pixel limit."
                    )
                with ImageOps.exif_transpose(image) as oriented, oriented.convert("RGB") as rgb:
                    rgb.thumbnail((2500, 2500))
                    output = io.BytesIO()
                    rgb.save(output, format="JPEG", quality=84)
                    yield output.getvalue()
    except (OSError, ValueError) as error:
        raise ExtractionError("vision_unavailable", "The image could not be rendered.") from error


def main() -> None:
    _, path, output, format, *numbers = sys.argv
    apply_limits()
    try:
        coded = []
        size = 0
        if format not in IMAGE_SIGNATURES and format != "pdf":
            raise ExtractionError("not_found", "The source is not a visual document.")
        renderer = render if format == "pdf" else render_image
        for page in renderer(Path(path), list(map(int, numbers))):
            size += len(page)
            if size > 10 * 1024 * 1024:
                raise ExtractionError("vision_unavailable", "Page images exceed the size limit.")
            coded.append(base64.b64encode(page).decode("ascii"))
        result = {"images": coded}
    except ExtractionError as error:
        result = {"code": error.code, "message": str(error)}
    Path(output).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
