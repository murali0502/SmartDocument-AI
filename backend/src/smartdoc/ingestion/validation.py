import re
import unicodedata
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from smartdoc.ingestion.contracts import ExtractionError

TEXT_FORMATS = {"txt", "md", "html", "csv", "json", "yaml"}
OFFICE_SIGNATURES = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}
IMAGE_SIGNATURES = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpeg": (b"\xff\xd8\xff",),
    "tiff": (b"II*\x00", b"MM\x00*"),
}
SUPPORTED = TEXT_FORMATS | OFFICE_SIGNATURES.keys() | IMAGE_SIGNATURES.keys() | {"pdf"}
ALIASES = {"markdown": "md", "htm": "html", "yml": "yaml", "jpg": "jpeg", "tif": "tiff"}
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_ARCHIVE_FILES = 5000


def upload_name(filename: str) -> tuple[str, str]:
    name = unicodedata.normalize("NFC", filename).strip()
    if (
        not name
        or len(name) > 255
        or name in {".", ".."}
        or any(
            character in "/\\:" or unicodedata.category(character).startswith("C")
            for character in name
        )
    ):
        raise ExtractionError("invalid_filename", "Use a plain filename without path separators.")
    _, separator, extension = name.rpartition(".")
    format = ALIASES.get(extension.lower(), extension.lower()) if separator else ""
    if format not in SUPPORTED:
        raise ExtractionError("unsupported_format", "This filename has an unsupported extension.")
    return name, format


def validate_signature(path: Path, format: str) -> None:
    with path.open("rb") as file:
        sample = file.read(4096)
    if not sample:
        raise ExtractionError("empty_upload", "The uploaded file is empty.")
    if format in TEXT_FORMATS:
        unicode_bom = sample.startswith((b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff"))
        if not unicode_bom and (b"\x00" in sample or sample.startswith((b"%PDF-", b"PK\x03\x04"))):
            raise ExtractionError(
                "file_type_mismatch", "The upload does not match its text extension."
            )
        return
    if format == "pdf":
        matches = sample.lstrip(b" \t\r\n").startswith(b"%PDF-")
    elif format in OFFICE_SIGNATURES:
        matches = sample.startswith(b"PK\x03\x04")
    else:
        matches = sample.startswith(IMAGE_SIGNATURES[format])
    if not matches:
        raise ExtractionError("file_type_mismatch", "The upload does not match its extension.")


def validate_office_archive(path: Path, format: str) -> None:
    try:
        with ZipFile(path) as archive:
            members = archive.infolist()
            names = {member.filename for member in members}
            if (
                len(members) > MAX_ARCHIVE_FILES
                or sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES
            ):
                raise ExtractionError(
                    "archive_limit", "The Office archive exceeds extraction limits."
                )
            if (
                len(names) != len(members)
                or not {"[Content_Types].xml", OFFICE_SIGNATURES[format]} <= names
            ):
                raise ExtractionError(
                    "malformed_document", "The Office package is incomplete or ambiguous."
                )
            for member in members:
                name = member.filename
                parts = PurePosixPath(name).parts
                if (
                    name.startswith("/")
                    or "\\" in name
                    or ":" in name
                    or ".." in parts
                    or member.flag_bits & 1
                ):
                    raise ExtractionError(
                        "unsafe_archive", "The Office package contains an unsafe entry."
                    )
                if name.lower().endswith("vbaproject.bin"):
                    raise ExtractionError(
                        "macros_unsupported", "Office packages with macros are unsupported."
                    )
                if name.lower().endswith((".xml", ".rels")):
                    with archive.open(member) as stream:
                        tail = b""
                        while block := stream.read(65536):
                            content = tail + block
                            if re.search(
                                rb"<!\s*(DOCTYPE|ENTITY)\b", content.replace(b"\0", b""), re.I
                            ):
                                raise ExtractionError(
                                    "unsafe_xml", "DTD and entity declarations are unsupported."
                                )
                            tail = content[-100:]
    except (BadZipFile, NotImplementedError, RuntimeError) as error:
        raise ExtractionError(
            "malformed_document", "The Office archive could not be read."
        ) from error
