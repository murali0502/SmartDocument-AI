import json
import sys
from pathlib import Path

from smartdoc.ingestion.contracts import Extraction, ExtractionError, Parser
from smartdoc.ingestion.validation import (
    IMAGE_SIGNATURES,
    OFFICE_SIGNATURES,
    TEXT_FORMATS,
    validate_signature,
)

MAX_RESULT_BYTES = 16 * 1024 * 1024


def extract(path: Path, format: str) -> Extraction:
    validate_signature(path, format)
    parser: Parser
    if format in TEXT_FORMATS:
        from smartdoc.ingestion.text import parse_text

        parser = parse_text
    elif format in OFFICE_SIGNATURES:
        from smartdoc.ingestion.office import parse_office

        parser = parse_office
    elif format in IMAGE_SIGNATURES:
        from smartdoc.ingestion.pdf import parse_image

        parser = parse_image
    else:
        from smartdoc.ingestion.pdf import parse_pdf

        parser = parse_pdf
    return parser(path, format)


def apply_limits() -> None:
    if sys.platform == "linux":
        import resource

        for limit, maximum in (
            (resource.RLIMIT_AS, 1536 * 1024 * 1024),
            (resource.RLIMIT_FSIZE, MAX_RESULT_BYTES),
            (resource.RLIMIT_CPU, 85),
        ):
            _, hard = resource.getrlimit(limit)
            ceiling = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
            resource.setrlimit(limit, (ceiling, ceiling))

    def prevent_io(event: str, args: tuple) -> None:
        if event.startswith("socket.") or event in {
            "os.system",
            "os.exec",
            "os.posix_spawn",
            "subprocess.Popen",
        }:
            raise PermissionError(
                "Network access and shell commands are disabled during extraction."
            )

    sys.addaudithook(prevent_io)


def main() -> None:
    path, format, output = sys.argv[1:]
    apply_limits()
    try:
        extraction = extract(Path(path), format)
        payload = extraction.model_dump_json(by_alias=True).encode()
        if len(payload) > MAX_RESULT_BYTES - 100:
            raise ExtractionError(
                "result_limit", "The extracted content exceeded the result size limit."
            )
        content = b'{"result":' + payload + b"}"
    except ExtractionError as error:
        content = json.dumps({"code": error.code, "message": str(error)}).encode()
    except MemoryError:
        content = b'{"code":"resource_limit","message":"The parser exceeded the memory limit."}'
    except Exception:
        content = (
            b'{"code":"malformed_document","message":"The parser could not read the document."}'
        )
    Path(output).write_bytes(content)


if __name__ == "__main__":
    main()
