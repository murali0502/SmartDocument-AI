import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.ncm.contracts import Anchor, Mention, MentionKind
from smartdoc.nlp.contracts import Annotation, RelationCandidate, TextSpan
from smartdoc.nlp.lexical import TOKEN, sentences
from smartdoc.nlp.relations import find_relations
from smartdoc.structure.contracts import Chunk, resolve_span

ARTICLES = re.compile(r"^(?:the|an|a)\s+", re.I)
INITIALS = re.compile(
    r"\b(?P<long>(?:[A-Za-z][\w-]* +){1,7}[A-Za-z][\w-]*)\s*\((?P<short>[A-Z][A-Z0-9]{1,9})\)"
)
EXPLICIT_ALIAS = re.compile(
    r"(?P<long>.+?) (?P<verb>is also known as|is now called) (?P<short>.+?)\.?$", re.I
)
TYPE_PATTERN = re.compile(
    r"(?P<subject>.+?) (?P<predicate>is an instance of|is part of|is a type of|"
    r"is a kind of|precedes|follows|implements|is derived from|is caused by) (?P<object>.+?)\.?$",
    re.I,
)
TYPE_LABELS = {
    "is an instance of": "INSTANCE_OF",
    "is part of": "PART_OF",
    "is a type of": "IS_A",
    "is a kind of": "IS_A",
    "precedes": "PRECEDES",
    "follows": "FOLLOWS",
    "implements": "IMPLEMENTS",
    "is derived from": "DERIVED_FROM",
    "is caused by": "CAUSED_BY",
}
DEPRECATED = re.compile(r"(?P<label>.+?) is (?:deprecated|obsolete|retired)\.?$", re.I)
COMPLEX = re.compile(
    r"[,;:!?]|\b(?:if|unless|when|although|but|not|never|neither|and|or|because|that|which|during|no|without|claims?|says?|believes?|suggests?)\b",
    re.I,
)
GENERIC = {
    "this",
    "that",
    "these",
    "those",
    "they",
    "them",
    "it",
    "we",
    "i",
    "you",
    "he",
    "she",
    "overview",
    "introduction",
    "conclusion",
}
TYPED_LABELS = {
    "PERSON",
    "ORG",
    "GPE",
    "LOC",
    "PRODUCT",
    "TECHNOLOGY",
    "EVENT",
    "LANGUAGE",
    "METHOD",
}


def normalized(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value)
        .casefold()
        .translate(str.maketrans("‐‑–—", "----"))
        .split()
    )


def label_text(value: str) -> str:
    return ARTICLES.sub("", value).strip()


def valid_label(value: str) -> bool:
    return (
        1 < len(value) <= 130
        and any(character.isalpha() for character in value)
        and 1 <= len(TOKEN.findall(value)) <= 16
        and all(character.isalnum() or character in " -/+'’._μ°" for character in value)
        and not value.startswith("=")
        and normalized(value) not in GENERIC
    )


@dataclass
class Inputs:
    chunk: Chunk
    annotation: Annotation


@dataclass(frozen=True)
class AliasClaim:
    source: Mention
    target: Mention
    method: str
    evidence: Anchor


@dataclass(frozen=True)
class Relation:
    candidate: RelationCandidate
    subject: Mention
    object: Mention
    predicate: Anchor
    evidence: Anchor


class Extractor:
    def __init__(self, document_id: UUID, job_id: UUID, extraction: Extraction) -> None:
        self.document_id = document_id
        self.job_id = job_id
        self.extraction = extraction

    def anchor(self, chunk: Chunk, span: TextSpan) -> Anchor:
        if not chunk.primary.start <= span.start < span.end <= chunk.primary.end:
            raise ExtractionError(
                "invalid_provenance", "A concept span is outside its source chunk."
            )
        source = chunk.primary.model_copy(update={"start": span.start, "end": span.end})
        if resolve_span(self.extraction, source) != span.text:
            raise ExtractionError(
                "invalid_provenance", "The concept span disagrees with its extraction."
            )
        return Anchor(
            document_id=self.document_id,
            extraction_job_id=self.job_id,
            chunk_id=chunk.id,
            source=source,
            locator=chunk.locator,
            text=span.text,
        )

    def mention(
        self, chunk: Chunk, span: TextSpan, kind: MentionKind, label: str | None = None
    ) -> Mention | None:
        surface = label_text(span.text)
        if not valid_label(surface):
            return None
        trimmed = span.model_copy(update={"text": surface})
        # Trimming the article and whitespace keeps the span aligned with the original.
        position = span.text.find(surface)
        trimmed = trimmed.model_copy(
            update={"start": span.start + position, "end": span.start + position + len(surface)}
        )
        return Mention(
            evidence=self.anchor(chunk, trimmed),
            kind=kind,
            label=label,
            section_id=chunk.section_path[-1].id if chunk.section_path else None,
            parent_section_id=chunk.section_path[-2].id if len(chunk.section_path) >= 2 else None,
        )

    @staticmethod
    def span(chunk: Chunk, start: int, end: int) -> TextSpan:
        return TextSpan(
            start=chunk.primary.start + start,
            end=chunk.primary.start + end,
            text=chunk.text[start:end],
        )

    def mentions(self, row: Inputs) -> Iterator[Mention]:
        chunk, annotation = row.chunk, row.annotation
        structural = {
            "heading": "heading",
            "table_cell": "table",
            "list_item": "list",
            "caption": "caption",
        }
        if kind := structural.get(chunk.element_type):
            text = chunk.text.strip().removeprefix("#").lstrip("# ").rstrip()
            text = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", text)
            if text and (
                candidate := self.mention(
                    chunk,
                    self.span(chunk, chunk.text.index(text), chunk.text.index(text) + len(text)),
                    kind,
                )
            ):
                yield candidate
        for item in annotation.entities:
            if item.label not in {
                "DATE",
                "TIME",
                "MONEY",
                "CARDINAL",
                "ORDINAL",
                "QUANTITY",
                "MEASUREMENT",
                "PERCENT",
            }:
                if mention := self.mention(chunk, item.span, "entity", item.label):
                    yield mention
        for item in annotation.phrases:
            if item.label == "noun_phrase" and (
                mention := self.mention(chunk, item.span, "phrase")
            ):
                yield mention

    def aliases(self, chunk: Chunk, ranges: list[tuple[int, int]]) -> Iterator[AliasClaim]:
        for match in INITIALS.finditer(chunk.text):
            words = list(re.finditer(r"[A-Za-z][\w-]*", match["long"]))
            length = len(match["short"])
            significant = [
                word
                for word in words
                if word[0].casefold() not in {"of", "the", "and", "for", "in"}
            ]
            if (
                len(significant) < length
                or "".join(word[0][0].upper() for word in significant[-length:]) != match["short"]
            ):
                continue
            start = match.start("long") + significant[-length].start()
            long = self.mention(chunk, self.span(chunk, start, match.end("long")), "alias")
            short = self.mention(chunk, self.span(chunk, *match.span("short")), "alias")
            if long and short:
                yield AliasClaim(
                    short, long, "acronym", self.anchor(chunk, self.span(chunk, start, match.end()))
                )
        for start, end in ranges:
            piece = chunk.text[start:end]
            if (match := EXPLICIT_ALIAS.fullmatch(piece)) and not COMPLEX.search(piece):
                source = self.mention(
                    chunk,
                    self.span(chunk, start + match.start("long"), start + match.end("long")),
                    "alias",
                )
                target = self.mention(
                    chunk,
                    self.span(chunk, start + match.start("short"), start + match.end("short")),
                    "alias",
                )
                if source and target:
                    verb = match["verb"].casefold()
                    if verb == "is also known as":
                        source, target = target, source
                    yield AliasClaim(
                        source,
                        target,
                        "explicit_rename" if verb == "is now called" else "explicit_alias",
                        self.anchor(chunk, self.span(chunk, start, end)),
                    )

    def relations(self, row: Inputs, ranges: list[tuple[int, int]]) -> tuple[list[Relation], int]:
        chunk, annotation = row.chunk, row.annotation
        if chunk.element_type in {"code_block", "math_expression", "reference"}:
            return [], 0
        if annotation.source != chunk.primary:
            raise ExtractionError(
                "invalid_provenance", "The NLP source no longer matches its chunk."
            )
        known_ranges = {(span.start, span.end) for span in annotation.sentences}
        proposals = []
        rejected = 0
        for candidate in annotation.relations:
            start, end = candidate.evidence.start, candidate.evidence.end
            if (
                start,
                end,
            ) not in known_ranges or not chunk.primary.start <= start < end <= chunk.primary.end:
                rejected += 1
                continue
            reconstructed = find_relations(
                chunk.text,
                [(start - chunk.primary.start, end - chunk.primary.start)],
                lambda left, right: self.span(chunk, left, right),
                annotation.tokens,
            )
            if candidate not in reconstructed:
                rejected += 1
                continue
            proposals.append(candidate)
        for start, end in ranges:
            piece = chunk.text[start:end]
            if COMPLEX.search(piece) or not (match := TYPE_PATTERN.fullmatch(piece)):
                continue
            subject, predicate, obj = [
                self.span(chunk, start + match.start(name), start + match.end(name))
                for name in ("subject", "predicate", "object")
            ]
            proposals.append(
                RelationCandidate(
                    subject=subject,
                    object=obj,
                    predicate=predicate,
                    evidence=self.span(chunk, start, end),
                    type=TYPE_LABELS[predicate.text.casefold()],
                    negated=False,
                    modality=None,
                    method="lexical-pattern",
                )
            )
        rows = []
        for candidate in proposals:
            subject = self.mention(chunk, candidate.subject, "relation")
            obj = self.mention(chunk, candidate.object, "relation")
            if subject is None or obj is None:
                rejected += 1
                continue
            evidence = self.anchor(chunk, candidate.evidence)
            predicate = self.anchor(chunk, candidate.predicate)
            if any(
                not evidence.source.start
                <= endpoint.evidence.source.start
                < endpoint.evidence.source.end
                <= evidence.source.end
                for endpoint in (subject, obj)
            ):
                rejected += 1
                continue
            rows.append(Relation(candidate, subject, obj, predicate, evidence))
        return rows, rejected

    def ranges(self, row: Inputs) -> list[tuple[int, int]]:
        return sentences(row.chunk.text)
