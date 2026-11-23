from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.ncm.candidates import (
    COMPLEX,
    DEPRECATED,
    TYPED_LABELS,
    AliasClaim,
    Extractor,
    Inputs,
    Relation,
    label_text,
    normalized,
)
from smartdoc.ncm.contracts import (
    NCM_VERSION,
    Alias,
    AliasReview,
    Assertion,
    Concept,
    ConceptScore,
    Definition,
    Hierarchy,
    Mention,
    Snapshot,
    Weights,
)
from smartdoc.ncm.scoring import rank
from smartdoc.ncm.similarity import duplicate_suggestions, with_lemmas
from smartdoc.structure.contracts import resolve_span

MAX_CHUNKS = 4000
MAX_MENTIONS = 16000
MAX_CONCEPTS = 5000
MAX_ASSERTIONS = 5000
MAX_HIERARCHY = 20000


@dataclass(frozen=True)
class Key:
    normalized: str
    category: str
    sense: str | None


def mention_key(mention: Mention) -> str:
    return normalized(mention.evidence.text)


def mark_conflicts(assertions: list[Assertion]) -> list[Assertion]:
    polarity: dict[tuple, set[bool]] = defaultdict(set)
    for row in assertions:
        if row.validation in {"source_validated", "conflicted"}:
            polarity[(row.subject_id, row.type, row.object_id, row.modality)].add(row.negated)
    return [
        item.model_copy(
            update={
                "validation": "conflicted"
                if len(polarity[(item.subject_id, item.type, item.object_id, item.modality)]) > 1
                else "source_validated"
            }
        )
        if item.validation in {"source_validated", "conflicted"}
        else item
        for item in assertions
    ]


def definitions(concepts: list[Concept], assertions: list[Assertion]) -> list[Concept]:
    by_concept = defaultdict(list)
    for row in assertions:
        if row.type == "DEFINED_BY" and not row.negated and row.validation != "rejected":
            by_concept[row.subject_id].append(
                Definition(
                    quote=row.evidence,
                    expression=row.object,
                    qualified=row.modality is not None or row.validation != "source_validated",
                )
            )
    return [item.model_copy(update={"definitions": by_concept[item.id]}) for item in concepts]


def hierarchy(concepts: list[Concept], assertions: list[Assertion]) -> list[Hierarchy]:
    headings: dict[UUID, tuple[Concept, Mention]] = {}
    for concept in concepts:
        for mention in concept.mentions:
            if mention.kind == "heading" and mention.section_id:
                headings.setdefault(mention.section_id, (concept, mention))

    edges: dict[tuple, Hierarchy] = {}
    for concept in concepts:
        for mention in concept.mentions:
            parent = headings.get(
                mention.parent_section_id if mention.kind == "heading" else mention.section_id
            )
            if parent and parent[0].id != concept.id:
                key = (concept.id, parent[0].id, "section")
                if key not in edges:
                    edges[key] = Hierarchy(
                        child_id=concept.id,
                        parent_id=parent[0].id,
                        kind="section",
                        evidence=[mention.evidence, parent[1].evidence],
                    )
    for row in assertions:
        if row.validation != "source_validated" or row.negated or row.modality:
            continue
        if row.type in {"IS_A", "PART_OF", "INSTANCE_OF", "HAS_PART"}:
            child, parent = (
                (row.object_id, row.subject_id)
                if row.type == "HAS_PART"
                else (row.subject_id, row.object_id)
            )
            kind = "part_of" if row.type == "HAS_PART" else row.type.lower()
            key = (child, parent, kind, row.id)
            edges[key] = Hierarchy(
                child_id=child,
                parent_id=parent,
                kind=kind,
                evidence=[row.evidence],
                assertion_id=row.id,
            )
    if len(edges) > MAX_HIERARCHY:
        raise ExtractionError("ncm_limit", "The document has too many hierarchy contributions.")
    return list(edges.values())


def _scopes(relations: list[Relation]) -> dict[str, set[str | None]]:
    definitions: dict[str, dict[str | None, set[str]]] = defaultdict(lambda: defaultdict(set))
    for relation in relations:
        if (
            relation.candidate.type == "DEFINED_BY"
            and not relation.candidate.negated
            and not relation.candidate.modality
        ):
            definitions[mention_key(relation.subject)][relation.subject.section_id].add(
                mention_key(relation.object)
            )
    return {
        word: {
            str(section) if section is not None else None
            for section, values in pockets.items()
            if len(values) == 1
        }
        for word, pockets in definitions.items()
        if len(set().union(*pockets.values())) > 1
    }


class Canonicalizer:
    def __init__(
        self, mentions: list[Mention], relations: list[Relation], aliases: list[AliasClaim]
    ) -> None:
        self.scopes = _scopes(relations)
        self.types: dict[str, set[str]] = defaultdict(set)
        for mention in mentions:
            if mention.label in TYPED_LABELS:
                self.types[mention_key(mention)].add(mention.label)

        targets: dict[str, set[str]] = defaultdict(set)
        for claim in aliases:
            source, target = mention_key(claim.source), mention_key(claim.target)
            if source != target:
                targets[source].add(target)
        self.aliases = {}
        self.ambiguous = set()
        for source, destinations in targets.items():
            if len(destinations) != 1:
                self.ambiguous.add(source)
                continue
            target = next(iter(destinations))
            labels = self.types[source] | self.types[target]
            if (
                len(labels) > 1
                or target in targets
                or source in self.scopes
                or target in self.scopes
            ):
                self.ambiguous.add(source)
                continue
            self.aliases[source] = target
            self.types[target].update(labels)

    def key(self, mention: Mention) -> Key:
        term = mention_key(mention)
        word = self.aliases.get(term, term)
        labels = self.types[word]
        label = (
            mention.label
            if mention.label in labels
            else next(iter(labels))
            if len(labels) == 1
            else "concept"
        )
        sense = None
        if word in self.scopes:
            scope = str(mention.section_id) if mention.section_id else None
            sense = scope if scope in self.scopes[word] and scope else "unresolved"
        if term in self.ambiguous or (len(labels) > 1 and label == "concept"):
            sense = "unresolved"
        return Key(word, label, sense)


def collect(
    extractor: Extractor,
    rows: Iterable[Inputs],
) -> tuple[list[Mention], list[Relation], list[AliasClaim], list[Mention], int]:
    mentions = []
    relations = []
    aliases = []
    deprecations = []
    rejected = 0
    for index, row in enumerate(rows, 1):
        chunk = row.chunk
        if index > MAX_CHUNKS:
            raise ExtractionError("ncm_limit", "The document exceeds the NCM chunk limit.")
        if (
            resolve_span(extractor.extraction, chunk.primary) != chunk.text
            or row.annotation.source != chunk.primary
        ):
            raise ExtractionError(
                "invalid_provenance", "The saved NLP chunk does not match the extraction."
            )
        ranges = extractor.ranges(row)
        if chunk.element_type in {"code_block", "math_expression", "reference"}:
            continue
        first_mention = len(mentions)
        mentions.extend(extractor.mentions(row))
        for claim in extractor.aliases(chunk, ranges):
            aliases.append(claim)
            mentions.extend((claim.source, claim.target))
        direct, discarded = extractor.relations(row, ranges)
        rejected += discarded
        for candidate in direct:
            relations.append(candidate)
            mentions.extend((candidate.subject, candidate.object))
        for start, end in ranges:
            if (match := DEPRECATED.fullmatch(chunk.text[start:end])) and not COMPLEX.search(
                match["label"]
            ):
                surface = extractor.mention(
                    chunk,
                    extractor.span(chunk, start + match.start("label"), start + match.end("label")),
                    "relation",
                )
                if surface:
                    mentions.append(surface)
                    deprecations.append(
                        surface.model_copy(
                            update={
                                "evidence": extractor.anchor(
                                    chunk, extractor.span(chunk, start, end)
                                )
                            }
                        )
                    )
        mentions[first_mention:] = with_lemmas(mentions[first_mention:], row.annotation.tokens)
        if len(mentions) > MAX_MENTIONS or len(relations) > MAX_ASSERTIONS:
            raise ExtractionError("ncm_limit", "The document exceeds the NCM evidence limit.")
    return mentions, relations, aliases, deprecations, rejected


def build_snapshot(
    document_id: UUID,
    job_id: UUID,
    extraction: Extraction,
    rows: Iterable[Inputs],
    created_at: datetime,
    weights: Weights,
) -> Snapshot:
    extractor = Extractor(document_id, job_id, extraction)
    mentions, relations, aliases, deprecations, rejected = collect(extractor, rows)
    canonical = Canonicalizer(mentions, relations, aliases)
    namespace = uuid5(job_id, NCM_VERSION)
    buckets: dict[Key, list[Mention]] = defaultdict(list)
    for mention in mentions:
        buckets[canonical.key(mention)].append(mention)
    if len(buckets) > MAX_CONCEPTS:
        raise ExtractionError("ncm_limit", "The document exceeds the concept limit.")
    concepts = {}
    for key, sources in buckets.items():
        originals = [item.evidence.text for item in sources if mention_key(item) == key.normalized]
        label = originals[0] if originals else sources[0].evidence.text
        dedup = {
            (
                item.evidence.chunk_id,
                item.evidence.source.start,
                item.evidence.source.end,
                item.kind,
                item.label,
            ): item
            for item in sources
        }
        concepts[key] = Concept(
            id=uuid5(namespace, repr(key)),
            label=label,
            normalized=key.normalized,
            category=key.category,
            sense=key.sense,
            mentions=list(dedup.values()),
            score=ConceptScore(total=0, features={}),
        )
    reviews: dict[str, AliasReview] = {}
    for claim in aliases:
        term = mention_key(claim.source)
        target = concepts[canonical.key(claim.target)]
        if term in canonical.ambiguous:
            review = reviews.setdefault(
                term, AliasReview(surface=claim.source.evidence.text, alternatives=[], evidence=[])
            )
            if target.id not in review.alternatives:
                review.alternatives.append(target.id)
            review.evidence.append(claim.evidence)
        elif term in canonical.aliases:
            target.aliases.append(
                Alias(
                    surface=claim.source.evidence.text,
                    method=claim.method,
                    evidence=[claim.evidence],
                )
            )

    for item in deprecations:
        text = DEPRECATED.fullmatch(item.evidence.text)
        if text:
            key = canonical.key(
                item.model_copy(
                    update={
                        "evidence": item.evidence.model_copy(
                            update={"text": label_text(text["label"])}
                        )
                    }
                )
            )
            if key in concepts:
                concepts[key].deprecation.append(item.evidence)

    assertions = {}
    for row in relations:
        subject = concepts[canonical.key(row.subject)]
        obj = concepts[canonical.key(row.object)]
        if subject.id == obj.id and mention_key(row.subject) != mention_key(row.object):
            rejected += 1
            continue
        candidate = row.candidate
        assertion = Assertion(
            id=uuid5(
                namespace,
                f"{subject.id}:{candidate.type}:{obj.id}:{row.evidence.chunk_id}:{row.evidence.source.start}",
            ),
            subject_id=subject.id,
            object_id=obj.id,
            type=candidate.type,
            subject=row.subject.evidence,
            object=row.object.evidence,
            predicate=row.predicate,
            evidence=row.evidence,
            negated=candidate.negated,
            modality=candidate.modality,
            method=candidate.method,
            validation="needs_review"
            if "unresolved" in {subject.sense, obj.sense}
            else "source_validated",
            confidence="dependency_supported"
            if candidate.method == "dependency-pattern"
            else "direct_pattern",
            created_at=created_at,
        )
        assertions[assertion.id] = assertion
    resolved_assertions = mark_conflicts(list(assertions.values()))
    ranked = rank(
        definitions(list(concepts.values()), resolved_assertions), resolved_assertions, weights
    )
    return Snapshot(
        document_id=document_id,
        concepts=ranked,
        assertions=resolved_assertions,
        hierarchy=hierarchy(ranked, resolved_assertions),
        ambiguous_aliases=list(reviews.values()),
        duplicate_candidates=duplicate_suggestions(ranked),
        rejected_candidates=rejected,
    )
