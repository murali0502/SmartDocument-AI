import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from smartdoc.structure.contracts import Chunk, Element, Evidence, SourceSpan

TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
SENTENCE_END = re.compile(r"""[.!?。！？]+["'”’)]*(?=\s|$)""")
LINE_END = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True)
class ChunkPolicy:
    max_tokens: int = 160
    max_characters: int = 1600
    overlap_tokens: int = 24
    overlap_characters: int = 320

    def __post_init__(self) -> None:
        if min(self.max_tokens, self.max_characters) < 1:
            raise ValueError("Primary chunk limits must be positive.")
        if min(self.overlap_tokens, self.overlap_characters) < 0:
            raise ValueError("Overlap limits must be nonnegative.")


DEFAULT_POLICY = ChunkPolicy()


def _fragments(
    text: str, boundary: re.Pattern[str], policy: ChunkPolicy
) -> Iterator[tuple[int, int]]:
    start = 0
    while start < len(text):
        limit = min(len(text), start + policy.max_characters)
        candidates = TOKEN.finditer(text, start, limit)
        for index, token in enumerate(candidates):
            if index == policy.max_tokens:
                limit = token.start()
                break
        if limit < len(text):
            earliest = start + (limit - start) // 2
            end = max(
                (match.end() for match in boundary.finditer(text, earliest, limit)), default=limit
            )
        else:
            end = limit
        yield start, end
        start = end


def _subspan(span: SourceSpan, start: int, end: int) -> SourceSpan:
    return span.model_copy(update={"start": span.start + start, "end": span.start + end})


def make_chunks(
    document_id: UUID,
    element: Element,
    text: str,
    first_ordinal: int,
    created_at: datetime,
    policy: ChunkPolicy = DEFAULT_POLICY,
) -> Iterator[Chunk]:
    if element.source is None or not text.strip():
        return
    line_aware = element.kind in {"code_block", "math_expression", "table_cell"}
    boundary = LINE_END if line_aware else SENTENCE_END
    strategy = "line-first-v1" if line_aware else "sentence-first-v1"
    previous_start = None
    for ordinal, (start, end) in enumerate(_fragments(text, boundary, policy), first_ordinal):
        primary = _subspan(element.source, start, end)
        overlap: list[Evidence] = []
        if previous_start is not None and policy.overlap_tokens and policy.overlap_characters:
            tail_start = max(previous_start, start - policy.overlap_characters)
            tokens = list(TOKEN.finditer(text, tail_start, start))
            if tokens:
                tail_start = tokens[max(0, len(tokens) - policy.overlap_tokens)].start()
                overlap.append(
                    Evidence(
                        source=_subspan(element.source, tail_start, start),
                        text=text[tail_start:start],
                    )
                )
        value = text[start:end]
        yield Chunk(
            id=uuid5(element.id, f"{strategy}:{primary.start}:{primary.end}"),
            document_id=document_id,
            parent_element_id=element.id,
            ordinal=ordinal,
            text=value,
            token_count=sum(1 for _ in TOKEN.finditer(value)),
            character_count=len(value),
            primary=primary,
            overlap=overlap,
            strategy=strategy,
            locator=element.locator,
            section_path=element.section_path,
            element_type=element.kind,
            created_at=created_at,
        )
        previous_start = start
